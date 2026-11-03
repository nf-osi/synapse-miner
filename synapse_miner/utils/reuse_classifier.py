"""
Classify how a publication relates to the Synapse studies it mentions.

Each mention of a Synapse ID is labelled from the wording of the sentence
around it:
  deposit   - the paper put data into Synapse ("have been deposited in",
              "generated in this study", "Data Records" section)
  available - the paper says data "are available at" the ID, which is
              usually its own data but can describe a third-party source
  reuse     - the paper used data already on Synapse ("downloaded from",
              "imported from", "accessed on <date>", "provided by")
  cite      - the ID appears without any of that wording (reference lists,
              review tables, key resource tables)

Mentions are then combined per (paper, study) pair:
  primary   - the paper generated or deposited the study's data
  secondary - the paper reused the study's data
  review    - the paper is a review article
  mention   - the paper cites the study without depositing or reusing data
  unclear   - not enough wording to tell; needs a human look

A study lead among the authors only decides weak cases (plain "available
at" wording, data descriptors, bare citations). Funders count a paper as
secondary when it reanalyses data already on the portal, even when a study
lead is a co-author (e.g. Dehner et al. 2021 using JHU Biobank data).
"""

import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

SYNID_PATTERN = re.compile(r"syn\d{7,12}")

# Wording showing the paper put data into Synapse
_DEPOSIT_CUES = [
    r"\b(?:have|has|had) been (?:deposited|uploaded|submitted|released|shared|stored|made (?:publicly |freely |openly )?available)\b",
    r"\b(?:are|is|were|was) (?:deposited|uploaded|submitted|released)\b",
    r"\bdeposited (?:in|at|on|to|with|into|through|via)\b",
    r"\buploaded (?:to|in|into|on)\b",
    r"\b(?:shared |all )?data (?:are|is|were) stored (?:in|on|at)\b",
    r"\bwill be (?:made )?(?:publicly |freely |openly )?(?:available|shared|released)\b",
    r"\breleased with this (?:article|paper|manuscript|study)\b",
    r"\b(?:generated|produced|collected) (?:in|by|for|during) (?:this|the present|the current) (?:study|work|paper|article)\b",
]

# Wording saying data can be found at the ID, without saying who put it there
_AVAILABLE_CUES = [
    r"\b(?:data|datasets?|files|results|analys[ie]s|sequencing|fastq|counts|codes?)\b[^.;]{0,100}?\b(?:are|is) (?:publicly |freely |openly |also )?(?:available|accessible|hosted) (?:at|on|in|through|via|from|under)\b",
]

# Wording showing the paper used data that was already on Synapse
_REUSE_CUES = [
    r"\bdownload(?:ed|ing)?\b",
    r"\b(?:obtained|retrieved|acquired|sourced|imported|accessed|requested) (?:from|through|via|using)\b",
    r"\baccessed (?:on|in) \d",
    r"\baccess(?:ed)? (?:was|were) (?:provided|granted)\b",
    r"\b(?:were|was|are|is) (?:provided|made available|shared) (?:to us )?by\b",
    r"\bprovided by the\b",
    r"\bpreviously (?:published|described|generated|reported|deposited|released|shared)\b",
    r"\bpublicly available (?:data|datasets?|files)\b[^.;]{0,60}?\b(?:from|at|on|in|through|via)\b",
    r"\bfrom (?:the )?publicly available\b",
]

_CITATION_AFTER_ID = re.compile(r"^\W{0,3}\(?[A-Z][\w'\- ]{0,40} et al\.?,? \d{4}")
_REFERENCE_SECTIONS = re.compile(r"\b(?:references?|bibliography|literature cited)\b", re.I)
_DEPOSIT_SECTIONS = re.compile(r"\bdata records?\b", re.I)
_REVIEW_TYPES = {"review", "review-article", "systematic review", "meta-analysis"}
_DATA_DESCRIPTOR_TYPES = {"data-paper", "dataset", "data paper"}

_DEPOSIT_RE = [re.compile(c, re.I) for c in _DEPOSIT_CUES]
_AVAILABLE_RE = [re.compile(c, re.I) for c in _AVAILABLE_CUES]
_REUSE_RE = [re.compile(c, re.I) for c in _REUSE_CUES]

# Short sentence splitter that keeps common abbreviations and DOIs together
_ABBREVIATIONS = r"(?<!\bet al)(?<!\be\.g)(?<!\bi\.e)(?<!\bFig)(?<!\bfig)(?<!\bvs)(?<!\bno)(?<!\bdoi)(?<!\bapprox)"
_SENTENCE_END = re.compile(_ABBREVIATIONS + r"[.;!?](?=\s+[A-Z(\[])")

NICKNAMES = {
    "peggy": "margaret", "maggie": "margaret", "meg": "margaret", "bill": "william",
    "will": "william", "bob": "robert", "rob": "robert", "bert": "robert",
    "liz": "elizabeth", "beth": "elizabeth", "betsy": "elizabeth", "kate": "katherine",
    "katie": "katherine", "kathy": "katherine", "jim": "james", "jimmy": "james",
    "mike": "michael", "tom": "thomas", "dick": "richard", "rick": "richard",
    "dave": "david", "dan": "daniel", "joe": "joseph", "chris": "christopher",
    "tony": "anthony", "ted": "edward", "ed": "edward", "jeff": "jeffrey",
    "steve": "steven", "sue": "susan", "jen": "jennifer", "jenny": "jennifer",
    "andy": "andrew", "nick": "nicholas", "pat": "patricia", "larry": "lawrence",
    "fred": "frederick", "al": "albert", "matt": "matthew", "sam": "samuel",
}


@dataclass
class Mention:
    """One sentence in a paper that mentions a Synapse ID."""
    synid: str
    section: str
    sentence: str
    kind: str = "cite"
    cue: str = ""


@dataclass
class PairResult:
    """How one paper relates to one Synapse study."""
    relationship: str
    confidence: str
    reason: str
    mentions: List[Mention] = field(default_factory=list)
    lead_authors: List[str] = field(default_factory=list)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_mentions(fulltext_xml: str, synids: Optional[Iterable[str]] = None) -> List[Mention]:
    """
    Find every sentence in a JATS full-text article that mentions a Synapse ID.

    Args:
        fulltext_xml: Europe PMC / PMC JATS XML for the article
        synids: Only keep mentions of these IDs (all IDs when None)

    Returns:
        Mentions in document order, one per (ID, sentence)
    """
    wanted = set(synids) if synids is not None else None
    root = ET.fromstring(fulltext_xml.encode("utf-8") if isinstance(fulltext_xml, str) else fulltext_xml)
    mentions: List[Mention] = []
    section_text: Dict[str, List[str]] = {}
    seen = set()

    def visit(el, section: str):
        tag = el.tag.split("}")[-1]
        if tag in ("sec", "app", "notes", "ack", "ref-list", "fn-group", "back"):
            title = el.find("title")
            if title is not None and "".join(title.itertext()).strip():
                section = _clean("".join(title.itertext()))
            elif tag == "ref-list":
                section = "References"
        if tag in ("p", "td", "th", "fn", "mixed-citation", "element-citation"):
            text = "".join(el.itertext())
            section_text.setdefault(section or "", []).append(text)
            if SYNID_PATTERN.search(text):
                for sentence in split_sentences(text):
                    for synid in dict.fromkeys(SYNID_PATTERN.findall(sentence)):
                        key = (synid, sentence)
                        if (wanted is None or synid in wanted) and key not in seen:
                            seen.add(key)
                            mentions.append(Mention(synid, section or "", sentence))
            return
        for child in el:
            visit(child, section)

    visit(root, "")
    for mention in mentions:
        mention.kind, mention.cue = classify_mention(mention.sentence, mention.synid, mention.section)
        if mention.kind == "cite" and not mention.cue:
            # A bare mention (e.g. "Study name (syn123)" in a list of sources)
            # takes the wording of its section when that section is one-sided
            mention.kind, mention.cue = _section_context(" ".join(section_text.get(mention.section, [])))
    return mentions


def split_sentences(text: str) -> List[str]:
    """Split a paragraph into sentences without breaking 'et al.' or DOIs."""
    text = _clean(text)
    parts, start = [], 0
    for match in _SENTENCE_END.finditer(text):
        parts.append(text[start:match.end()].strip())
        start = match.end()
    parts.append(text[start:].strip())
    return [p for p in parts if p]


def _nearest_cue(sentence: str, position: int, patterns: Sequence[re.Pattern]) -> Tuple[Optional[int], str]:
    best, best_cue = None, ""
    for pattern in patterns:
        for match in pattern.finditer(sentence):
            distance = min(abs(match.start() - position), abs(match.end() - position))
            if best is None or distance < best:
                best, best_cue = distance, match.group(0)
    return best, best_cue


def classify_mention(sentence: str, synid: str, section: str = "") -> Tuple[str, str]:
    """
    Label one sentence as 'deposit', 'available', 'reuse' or 'cite' for the given ID.

    When a sentence has more than one kind of wording, the cue closest to the
    ID wins (reuse on ties), so "downloaded from syn1 and deposited results in
    syn2" labels each ID correctly.

    Returns:
        (kind, cue) where cue is the matched wording or section name
    """
    if _REFERENCE_SECTIONS.search(section or ""):
        return "cite", "reference list"
    position = sentence.find(synid)
    if position < 0:
        position = 0
    after = sentence[position + len(synid):]
    if _CITATION_AFTER_ID.match(after) and not _nearest_cue(sentence, position, _DEPOSIT_RE)[1]:
        return "cite", "author-year citation"

    candidates = []
    for order, (kind, patterns) in enumerate(
            (("reuse", _REUSE_RE), ("deposit", _DEPOSIT_RE), ("available", _AVAILABLE_RE))):
        distance, cue = _nearest_cue(sentence, position, patterns)
        if distance is not None:
            candidates.append((distance, order, kind, cue))
    if candidates:
        _, _, kind, cue = min(candidates)
        return kind, cue
    if _DEPOSIT_SECTIONS.search(section or ""):
        return "deposit", f"section: {section}"
    return "cite", ""


def _section_context(text: str) -> Tuple[str, str]:
    """Label a section 'reuse' or 'deposit' when only one kind of wording appears in it."""
    reuse = next((m.group(0) for p in _REUSE_RE for m in [p.search(text)] if m), "")
    deposit = next((m.group(0) for p in _DEPOSIT_RE for m in [p.search(text)] if m), "")
    if reuse and not deposit:
        return "reuse", f"section context: {reuse}"
    if deposit and not reuse:
        return "deposit", f"section context: {deposit}"
    return "cite", ""


def has_paper_level_deposit(fulltext_xml: Optional[str]) -> bool:
    """
    True when the paper states anywhere that its data are on Synapse or the NF
    Data Portal without giving a Synapse ID (e.g. "deposited on Synapse at
    https://www.synapse.org/cNForganoids").
    """
    if not fulltext_xml:
        return False
    text = _clean("".join(ET.fromstring(fulltext_xml.encode("utf-8")).itertext()))
    for sentence in split_sentences(text):
        if re.search(r"synapse|nf data portal", sentence, re.I) and any(
                p.search(sentence) for p in _DEPOSIT_RE + _AVAILABLE_RE):
            if not any(p.search(sentence) for p in _REUSE_RE):
                return True
    return False


def _name_key(name: str) -> Tuple[str, str]:
    """(last name, first name) normalised to lowercase ASCII."""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    parts = [p for p in re.split(r"[\s.]+", name.replace("-", " ")) if p]
    if not parts:
        return "", ""
    return parts[-1], parts[0]


def lead_authors_on_paper(study_leads: Iterable[str], authors: Iterable[Dict]) -> List[str]:
    """
    Study leads who appear in the author list.

    Matches on last name plus first initial, allowing common nicknames
    ("Peggy Wallace" matches "Wallace MR" / "Margaret R Wallace").

    Args:
        study_leads: Names like "Christine Pratilas"
        authors: Europe PMC author dicts with lastName and firstName/initials
    """
    author_keys = set()
    for author in authors:
        # Last word of the surname, so "Patritti Cram" matches lead "Jennifer Patritti Cram"
        last = _name_key(author.get("lastName") or "")[0]
        if not last:
            continue
        # Any given name or initial counts, so a lead who goes by a middle
        # name ("Taylor Sundby" for "R Taylor Sundby") still matches
        given = _name_key(author.get("firstName") or "")
        names = re.split(r"[\s.]+", unicodedata.normalize("NFKD", author.get("firstName") or "")
                         .encode("ascii", "ignore").decode().lower().replace("-", " "))
        initials = list((author.get("initials") or "").lower())
        for initial in {n[:1] for n in names if n} | set(initials) | {given[1][:1]}:
            if initial:
                author_keys.add((last, initial))
    found = []
    for lead in study_leads:
        last, first = _name_key(lead)
        if not last:
            continue
        candidates = {first[:1], NICKNAMES.get(first, first)[:1]}
        if any((last, initial) in author_keys for initial in candidates if initial):
            found.append(lead)
    return found


def is_review(pub_types: Iterable[str]) -> bool:
    """True when Europe PMC publication types mark the paper as a review."""
    return any(str(t).strip().lower() in _REVIEW_TYPES for t in pub_types)


def is_data_descriptor(pub_types: Iterable[str]) -> bool:
    """True when Europe PMC publication types mark the paper as a data descriptor."""
    return any(str(t).strip().lower() in _DATA_DESCRIPTOR_TYPES for t in pub_types)


def classify_pair(mentions: List[Mention], pub_types: Iterable[str],
                  lead_authors: List[str], paper_level_deposit: bool = False,
                  has_fulltext: bool = True) -> PairResult:
    """
    Combine one paper's mentions of one study into a relationship label.

    Args:
        mentions: Mentions of this study's Synapse IDs in the paper
        pub_types: Europe PMC publication types for the paper
        lead_authors: Study leads found among the paper's authors
        paper_level_deposit: Paper says its data are on Synapse without an ID
        has_fulltext: Whether full text was available to read
    """
    kinds = {m.kind for m in mentions}

    def result(relationship, confidence, reason):
        if relationship == "unclear" and not has_fulltext:
            reason += " (no full text; judged from the mined snippet)"
        return PairResult(relationship, confidence, reason, mentions, lead_authors)

    if is_review(pub_types):
        return result("review", "high", "review article")
    if is_data_descriptor(pub_types) and lead_authors:
        return result("primary", "high", "data descriptor by a study lead")
    if "deposit" in kinds:
        return result("primary", "high",
                      "deposits data" + (" and also reuses it" if "reuse" in kinds else ""))
    if "reuse" in kinds:
        return result("secondary", "high", "reuses data")
    if "available" in kinds:
        if lead_authors:
            return result("primary", "high", "data availability statement by a study lead")
        return result("unclear", "low", "says data are available at the ID; no study lead among authors")
    if lead_authors and paper_level_deposit:
        return result("primary", "medium", "study lead is an author and paper deposits data on Synapse")
    if lead_authors:
        return result("unclear", "low", "study lead is an author; no deposit or reuse wording")
    if not has_fulltext:
        return result("unclear", "low", "no deposit or reuse wording")
    return result("mention", "medium", "cites the study without deposit or reuse wording")
