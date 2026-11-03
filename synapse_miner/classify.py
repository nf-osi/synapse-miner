"""
Classify mined publications by how they relate to NF Data Portal studies.

Input is the mined mentions table (pmcid, synid, context). Output has one row
per (paper, study): whether the paper generated/deposited the study's data
(primary), reused it (secondary), is a review, or is unclear, with the
sentences that support the label.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Optional

import pandas as pd

from .utils.europepmc_client import EuropePMCClient, normalize_pmcid
from .utils.ncbi_pmc_client import NCBIPMCClient
from .utils.reuse_classifier import (
    Mention, classify_mention, classify_pair, extract_mentions,
    has_paper_level_deposit, lead_authors_on_paper,
)
from .utils.study_resolver import StudyResolver

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = [
    "pmcid", "pmid", "doi", "title", "journal", "year", "authors", "is_preprint",
    "study_id", "study_name",
    "funding_agency", "relationship", "confidence", "reason", "lead_authors_on_paper",
    "synids", "evidence", "has_fulltext", "in_publications_table",
    "linked_to_study_in_publications_table",
]

_KIND_ORDER = {"deposit": 0, "reuse": 1, "available": 2, "cite": 3}


def _format_evidence(mentions: List[Mention], limit: int = 3, width: int = 400) -> str:
    """The most informative sentences, deposit/reuse first, as '[kind: cue] sentence'."""
    ranked = sorted(mentions, key=lambda m: (_KIND_ORDER.get(m.kind, 3), not m.cue))
    lines, seen = [], set()
    for m in ranked:
        if m.sentence in seen:
            continue
        seen.add(m.sentence)
        sentence = m.sentence if len(m.sentence) <= width else m.sentence[:width - 1] + "…"
        label = f"{m.kind}: {m.cue}" if m.cue else m.kind
        lines.append(f"[{label}] {sentence}")
        if len(lines) == limit:
            break
    return "\n".join(lines)


def _author_names(meta: Dict) -> str:
    """'First Last' names joined by '; ', as in the portal publications table."""
    names = []
    for author in meta.get("authors", []):
        first, last = author.get("firstName"), author.get("lastName")
        name = f"{first} {last}" if first and last else author.get("fullName")
        if name:
            names.append(name)
    return "; ".join(names)


def _tracked_entry(meta: Dict, tracked: Dict[str, Dict]) -> Optional[Dict]:
    keys = []
    if meta.get("pmid"):
        keys.append(f"pmid:{meta['pmid']}")
    if meta.get("doi"):
        keys.append(f"doi:{meta['doi'].lower()}")
    for key in keys:
        if key in tracked:
            return tracked[key]
    return None


def classify_publications(mentions_df: pd.DataFrame, studies: Dict[str, Dict],
                          tracked: Dict[str, Dict], resolver: StudyResolver,
                          epmc: EuropePMCClient,
                          funders: Optional[List[str]] = None,
                          ncbi: Optional[NCBIPMCClient] = None) -> pd.DataFrame:
    """
    Label each (paper, study) pair found in the mined mentions.

    Args:
        mentions_df: Rows with pmcid, synid and context
        studies: Output of study_resolver.load_studies
        tracked: Output of study_resolver.load_tracked_publications
        resolver: StudyResolver for mapping Synapse IDs to studies
        epmc: Europe PMC client for metadata and full text
        funders: Only keep studies funded by one of these agencies
        ncbi: NCBI PMC client used for full text Europe PMC does not serve
              (e.g. NIH author manuscripts)

    Returns:
        DataFrame with OUTPUT_COLUMNS, one row per (paper, study)
    """
    df = mentions_df.copy()
    df["pmcid"] = df["pmcid"].map(normalize_pmcid)
    resolver.resolve(df["synid"].unique())
    df["study_id"] = df["synid"].map(resolver.study_for)
    df = df[df["study_id"].notna()]
    if funders:
        wanted = {f.lower() for f in funders}
        df = df[df["study_id"].map(
            lambda s: any(f.lower() in wanted for f in studies[s]["funding_agency"]))]
    logger.info(f"{df['pmcid'].nunique()} articles cite {df['study_id'].nunique()} portal studies "
                f"({len(df)} mentions)")
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    pmcids = sorted(df["pmcid"].unique())
    metadata = epmc.get_metadata(pmcids)
    fulltexts = epmc.get_fulltexts(pmcids)
    missing = [p for p in pmcids if fulltexts.get(p) is None]
    if ncbi and missing:
        for pmcid, xml in ncbi.iter_fulltexts(missing):
            if "<body" in xml:
                fulltexts[pmcid] = xml
        logger.info(f"NCBI PMC supplied full text for "
                    f"{sum(fulltexts.get(p) is not None for p in missing)}/{len(missing)} more articles")

    contexts = defaultdict(list)
    for row in df.itertuples():
        contexts[(row.pmcid, row.synid)].append(str(getattr(row, "context", "") or ""))

    rows = []
    for pmcid, paper in df.groupby("pmcid"):
        meta = metadata.get(pmcid, {"pmcid": pmcid, "authors": [], "pub_types": []})
        xml = fulltexts.get(pmcid)
        synids = set(paper["synid"])
        try:
            fulltext_mentions = extract_mentions(xml, synids) if xml else []
        except Exception as e:
            logger.warning(f"Could not parse full text for {pmcid}: {e}")
            xml, fulltext_mentions = None, []
        paper_deposit = has_paper_level_deposit(xml) if xml else False
        tracked_entry = _tracked_entry(meta, tracked)

        for study_id, study_rows in paper.groupby("study_id"):
            study = studies[study_id]
            study_synids = sorted(set(study_rows["synid"]))
            mentions = [m for m in fulltext_mentions if m.synid in study_synids]
            found = {m.synid for m in mentions}
            for synid in study_synids:
                if synid in found:
                    continue
                # Fall back to the mined context when full text lacks the ID
                for context in contexts[(pmcid, synid)]:
                    kind, cue = classify_mention(context, synid)
                    mentions.append(Mention(synid, "mined context", context, kind, cue))
            leads = lead_authors_on_paper(study["study_leads"], meta.get("authors", []))
            result = classify_pair(mentions, meta.get("pub_types", []), leads,
                                   paper_level_deposit=paper_deposit, has_fulltext=xml is not None)
            rows.append({
                "pmcid": pmcid,
                "pmid": meta.get("pmid"),
                "doi": meta.get("doi"),
                "title": meta.get("title"),
                "journal": meta.get("journal"),
                "year": meta.get("year"),
                "authors": _author_names(meta),
                "is_preprint": any(str(t).lower() == "preprint" for t in meta.get("pub_types", [])),
                "study_id": study_id,
                "study_name": study["study_name"],
                "funding_agency": ", ".join(study["funding_agency"]),
                "relationship": result.relationship,
                "confidence": result.confidence,
                "reason": result.reason,
                "lead_authors_on_paper": ", ".join(leads),
                "synids": ", ".join(study_synids),
                "evidence": _format_evidence(result.mentions),
                "has_fulltext": xml is not None,
                "in_publications_table": tracked_entry is not None,
                "linked_to_study_in_publications_table":
                    bool(tracked_entry and study_id in tracked_entry["study_ids"]),
            })

    out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    counts = out["relationship"].value_counts().to_dict()
    logger.info(f"Classified {len(out)} paper-study pairs: {counts}")
    return out
