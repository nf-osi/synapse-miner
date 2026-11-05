"""
Add publication-study pairs a person has reviewed to the portal tables.

The weekly workflow leaves low-confidence pairs out and lists them in a review
issue. A reviewer answers with one decision per line, e.g.

    PMID:40585258 (liquid biopsy, syn51115812): primary
    PMID:40744913 (FGFR glioma, syn5698493): secondary

and `synapse-miner add-reviewed` turns those lines into rows. A line ending in
"replaces row 431" fixes that existing row in place instead (e.g. a
placeholder row holding a dataset DOI): its paper columns are overwritten,
fundingAgency is set to its studies' funders (as for new rows), and its study,
disease and manifestation columns are kept: metadata from
Europe PMC (journal names from Crossref), study details from the studies view,
the Synapse IDs the paper cites from the mined-mentions table. Rows are written
like the workflow's own: primary pairs to the publications table, secondary /
review / mention pairs to Cited By, one row per paper, never duplicating a
study already linked to the paper in either table, with snapshots around every
write. Confidence is "reviewed" and evidence points at the review.
"""

import logging
import re
from typing import Dict, Iterable, List, NamedTuple, Optional

import pandas as pd

from .portal_tables import (
    CITED_BY_COLUMNS, CITED_BY_RELATIONSHIPS, PRIMARY_RELATIONSHIPS, PUBLICATION_COLUMNS,
    append_rows, apply_merges, build_rows, group_by_paper, load_pair_keys, load_table_rows,
    plan_writes, _as_list, _doi_key, _fit_list, _pmid_digits,
)
from .utils.synapse_safety import snapshots_around
from .utils.crossref_client import clean_journal_title
from .utils.europepmc_client import author_names

logger = logging.getLogger(__name__)

RELATIONSHIPS = PRIMARY_RELATIONSHIPS + CITED_BY_RELATIONSHIPS
REVIEWED = "reviewed"

# "PMID:40585258 (anything, syn51115812): primary" and looser variants such as
# "40585258 syn51115812 primary" or "PMID 40585258, syn51115812 - secondary"
_DECISION = re.compile(
    r"(?:PMID[:\s]*)?\b(\d{6,9})\b.*?\b(syn\d+)\b.*?\b(" + "|".join(RELATIONSHIPS) + r")\b",
    re.IGNORECASE,
)
_REPLACES = re.compile(r"\breplac\w*\s+(?:ROW_?ID|row)?\s*#?\s*(\d+)\b", re.IGNORECASE)

# Columns a "replaces row N" decision overwrites (plus fundingAgency, from the
# row's studies); study, disease and manifestation columns of the row are kept
PAPER_COLUMNS = ["doi", "journal", "title", "year", "pmid", "author", "publicationType"]
CITED_BY_PAPER_COLUMNS = PAPER_COLUMNS + ["pmcid", "isPreprint", "confidence", "citedSynapseIds", "evidence"]


class Decision(NamedTuple):
    pmid: str
    study_id: str
    relationship: str
    replace_row: Optional[int] = None


def parse_decisions(text: str) -> List[Decision]:
    """One decision per line; lines without a PMID, study ID and relationship are ignored."""
    decisions = []
    for line in text.splitlines():
        match = _DECISION.search(line)
        if match:
            pmid, study, relationship = match.groups()
            replaces = _REPLACES.search(line[match.end():])
            decisions.append(Decision(pmid, study, relationship.lower(),
                                      int(replaces.group(1)) if replaces else None))
    return decisions


def cited_synapse_ids(syn, mentions_table: str, pmcids: Iterable[str]) -> Dict[str, List[str]]:
    """Synapse IDs each paper cites, from the mined-mentions table, keyed by PMCID ('PMC123')."""
    pmcids = sorted({p for p in pmcids if p})
    if not pmcids:
        return {}
    quoted = ", ".join(f"'pmc:{p}'" for p in pmcids)
    df = syn.tableQuery(f"SELECT pmcid, synid FROM {mentions_table} WHERE pmcid IN ({quoted})").asDataFrame()
    cited: Dict[str, List[str]] = {}
    for row in df.itertuples(index=False):
        ids = cited.setdefault(str(row.pmcid).removeprefix("pmc:"), [])
        if row.synid not in ids:
            ids.append(row.synid)
    return cited


def reviewed_pairs(decisions: List[Decision], metadata: Dict[str, Dict], cited: Dict[str, List[str]],
                   evidence: str, crossref=None) -> pd.DataFrame:
    """
    Classified-style rows (the columns build_rows reads) for reviewed decisions.

    Args:
        decisions: Parsed decisions
        metadata: Europe PMC metadata keyed by PMID (EuropePMCClient.get_metadata_by_pmid)
        cited: Synapse IDs cited per PMCID (cited_synapse_ids)
        evidence: Where the review happened, stored in the evidence column
        crossref: Optional CrossrefClient for the journal's own casing
    """
    rows = []
    for d in decisions:
        meta = metadata.get(d.pmid)
        if not meta:
            raise ValueError(f"No Europe PMC record for PMID {d.pmid}")
        journal = meta.get("journal")
        journal = crossref.journal_name(meta.get("doi"), journal) if crossref else clean_journal_title(journal)
        synids = cited.get(meta.get("pmcid") or "", []) or [d.study_id]
        rows.append({
            "pmcid": meta.get("pmcid"),
            "pmid": d.pmid,
            "doi": meta.get("doi"),
            "title": meta.get("title"),
            "journal": journal,
            "year": meta.get("year"),
            "authors": "; ".join(author_names(meta)),
            "is_preprint": any(str(t).lower() == "preprint" for t in meta.get("pub_types", [])),
            "study_id": d.study_id,
            "synids": ", ".join(synids),
            "relationship": d.relationship,
            "confidence": REVIEWED,
            "evidence": evidence,
            "replace_row": d.replace_row,
        })
    return pd.DataFrame(rows)


def add_reviewed(syn, decisions: List[Decision], evidence: str, epmc, studies: Dict[str, Dict],
                 publications_table: str, cited_by_table: str, mentions_table: str,
                 crossref=None, dry_run: bool = False) -> Dict[str, Dict]:
    """
    Write reviewed decisions to the portal tables.

    Returns:
        {"publications": {...}, "cited_by": {...}} with the rows appended
        ("new", a DataFrame) and existing rows linked to more studies
        ("merges", {ROW_ID: change}) for each table
    """
    unknown = sorted({d.study_id for d in decisions} - set(studies))
    if unknown:
        raise ValueError(f"Not portal studies (not in the studies view): {', '.join(unknown)}")
    metadata = epmc.get_metadata_by_pmid([d.pmid for d in decisions])
    cited = cited_synapse_ids(syn, mentions_table, [m.get("pmcid") for m in metadata.values()])
    pairs = reviewed_pairs(decisions, metadata, cited, evidence, crossref)

    existing = load_pair_keys(syn, publications_table) | load_pair_keys(syn, cited_by_table)
    replacing = pairs["replace_row"].notna()
    plan = {}
    for label, table_id, relationships, columns, match_relationship in (
        ("publications", publications_table, PRIMARY_RELATIONSHIPS, PUBLICATION_COLUMNS, False),
        ("cited_by", cited_by_table, CITED_BY_RELATIONSHIPS, CITED_BY_COLUMNS, True),
    ):
        target = load_table_rows(syn, table_id)
        rows = group_by_paper(build_rows(pairs[~replacing], studies, relationships))
        new_rows, merges = plan_writes(rows, target, existing, match_relationship)
        replacements = plan_replacements(pairs[replacing], studies, relationships, target, existing,
                                         CITED_BY_PAPER_COLUMNS if match_relationship else PAPER_COLUMNS)
        plan[label] = {"table": table_id, "new": new_rows, "merges": merges, "columns": columns,
                       "replacements": replacements}

    for label, p in plan.items():
        logger.info(f"{p['table']} ({label}): {len(p['new'])} new rows, "
                    f"{len(p['merges'])} existing rows linked to more studies, "
                    f"{len(p['replacements'])} rows fixed in place")
    if dry_run:
        return plan
    for label, p in plan.items():
        source = f"reviewed pairs ({evidence})"
        apply_merges(syn, p["table"], p["merges"],
                     f"add-reviewed links {len(p['merges'])} existing rows to more studies: {source}")
        append_rows(syn, p["table"], p["new"], p["columns"],
                    f"add-reviewed adds {len(p['new'])} rows: {source}")
        apply_replacements(syn, p["table"], p["replacements"],
                           f"add-reviewed fixes rows {', '.join(map(str, p['replacements']))}: {source}")
    return plan


def _plain(value):
    """numpy/pandas scalars and lists as plain Python values for a table update."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if value is None or (not isinstance(value, (list, str)) and pd.isna(value)):
        return None
    return value.item() if hasattr(value, "item") else value


def plan_replacements(pairs: pd.DataFrame, studies: Dict[str, Dict], relationships: Iterable[str],
                      target: pd.DataFrame, existing, columns: List[str]) -> Dict[int, Dict]:
    """
    {ROW_ID: {column: new value}} for decisions that replace an existing row.

    The row must already be linked to the decision's study, and the paper must
    not already be linked to that study in another row (that would duplicate
    it); replacing a row with the paper it already holds refreshes it.
    fundingAgency becomes the funders of the row's studies, unless none of
    them has any.
    """
    if pairs.empty:
        return {}
    built = build_rows(pairs, studies, relationships)
    changes = {}
    for decision, row in zip(pairs[pairs["relationship"].isin(set(relationships))].itertuples(index=False),
                             built.itertuples(index=False)):
        row_id = int(decision.replace_row)
        current = target[target["ROW_ID"].astype(int) == row_id]
        if current.empty:
            raise ValueError(f"ROW_ID {row_id} is not in the table that {decision.relationship} pairs go to")
        if decision.study_id not in _as_list(current.iloc[0]["studyId"]):
            raise ValueError(f"ROW_ID {row_id} is not linked to {decision.study_id}; not replacing it")
        ids = {f"pmid:{_pmid_digits(row.pmid)}", f"doi:{_doi_key(row.doi)}"}
        current_ids = {f"pmid:{_pmid_digits(current.iloc[0].get('pmid'))}",
                       f"doi:{_doi_key(current.iloc[0].get('doi'))}"} - {"pmid:", "doi:"}
        if not (ids & current_ids) and any((i, decision.study_id) in existing for i in ids):
            raise ValueError(f"PMID {decision.pmid} is already linked to {decision.study_id}")
        changes[row_id] = {c: _plain(getattr(row, c)) for c in columns}
        funders = []
        for study in _as_list(current.iloc[0]["studyId"]):
            funders += [f for f in studies.get(study, {}).get("funding_agency", []) if f not in funders]
        if funders:
            changes[row_id]["fundingAgency"] = _fit_list("fundingAgency", funders)
    return changes


def apply_replacements(syn, table_id: str, changes: Dict[int, Dict], action: str) -> int:
    """Overwrite the paper columns of existing rows, snapshotted. Returns rows changed."""
    if not changes:
        return 0
    from synapseclient import PartialRowset
    columns = sorted({c for change in changes.values() for c in change})
    ids = ",".join(str(i) for i in changes)
    with snapshots_around(syn, table_id, action):
        # Quoted: "year" is an SQL keyword
        quoted = ", ".join(f'"{c}"' for c in columns)
        fresh = syn.tableQuery(f"SELECT {quoted} FROM {table_id} WHERE ROW_ID IN ({ids})")
        syn.store(PartialRowset.from_mapping(changes, fresh))
    logger.info(f"Fixed {len(changes)} rows in place in {table_id}")
    return len(changes)


def describe(plan: Dict[str, Dict]) -> str:
    """Plain-text summary of a plan for the console."""
    lines = []
    for label, p in plan.items():
        for row in p["new"].itertuples(index=False):
            lines.append(f"{p['table']} new row: {row.pmid} {row.title[:70]!r} studies={row.studyId} "
                         f"type={row.publicationType} journal={row.journal!r} year={row.year} "
                         f"authors={len(row.author)} funders={row.fundingAgency}")
        for row_id, change in p["merges"].items():
            lines.append(f"{p['table']} ROW_ID {row_id}: add studies {change['added']}")
        for row_id, change in p.get("replacements", {}).items():
            lines.append(f"{p['table']} ROW_ID {row_id} fixed in place: {change['pmid']} "
                         f"{str(change['title'])[:70]!r} journal={change['journal']!r} year={change['year']} "
                         f"doi={change['doi']} authors={len(change['author'] or [])}")
    return "\n".join(lines) or "Nothing to add: every reviewed pair is already in the tables"


def plan_funder_fixes(target: pd.DataFrame, studies: Dict[str, Dict], row_ids: Iterable[int]) -> Dict[int, Dict]:
    """
    {ROW_ID: {"fundingAgency": [...]}} setting each row's funders to its studies' funders.

    Rows with no study, whose studies have no funders, or that already match
    are skipped.
    """
    changes = {}
    for row_id in row_ids:
        current = target[target["ROW_ID"].astype(int) == int(row_id)]
        if current.empty:
            logger.warning(f"ROW_ID {row_id} is not in the table; skipping it")
            continue
        funders = []
        for study in _as_list(current.iloc[0]["studyId"]):
            funders += [f for f in studies.get(study, {}).get("funding_agency", []) if f not in funders]
        funders = _fit_list("fundingAgency", funders)
        if funders and set(funders) != set(_as_list(current.iloc[0]["fundingAgency"])):
            changes[int(row_id)] = {"fundingAgency": funders}
    return changes
