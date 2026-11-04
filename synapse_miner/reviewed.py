"""
Add publication-study pairs a person has reviewed to the portal tables.

The weekly workflow leaves low-confidence pairs out and lists them in a review
issue. A reviewer answers with one decision per line, e.g.

    PMID:40585258 (liquid biopsy, syn51115812): primary
    PMID:40744913 (FGFR glioma, syn5698493): secondary

and `synapse-miner add-reviewed` turns those lines into rows: metadata from
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
    plan_writes,
)
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


class Decision(NamedTuple):
    pmid: str
    study_id: str
    relationship: str


def parse_decisions(text: str) -> List[Decision]:
    """One decision per line; lines without a PMID, study ID and relationship are ignored."""
    decisions = []
    for line in text.splitlines():
        match = _DECISION.search(line)
        if match:
            pmid, study, relationship = match.groups()
            decisions.append(Decision(pmid, study, relationship.lower()))
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
    plan = {}
    for label, table_id, relationships, columns, match_relationship in (
        ("publications", publications_table, PRIMARY_RELATIONSHIPS, PUBLICATION_COLUMNS, False),
        ("cited_by", cited_by_table, CITED_BY_RELATIONSHIPS, CITED_BY_COLUMNS, True),
    ):
        rows = group_by_paper(build_rows(pairs, studies, relationships))
        new_rows, merges = plan_writes(rows, load_table_rows(syn, table_id), existing, match_relationship)
        plan[label] = {"table": table_id, "new": new_rows, "merges": merges, "columns": columns}

    for label, p in plan.items():
        logger.info(f"{p['table']} ({label}): {len(p['new'])} new rows, "
                    f"{len(p['merges'])} existing rows linked to more studies")
    if dry_run:
        return plan
    for label, p in plan.items():
        source = f"reviewed pairs ({evidence})"
        apply_merges(syn, p["table"], p["merges"],
                     f"add-reviewed links {len(p['merges'])} existing rows to more studies: {source}")
        append_rows(syn, p["table"], p["new"], p["columns"],
                    f"add-reviewed adds {len(p['new'])} rows: {source}")
    return plan


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
    return "\n".join(lines) or "Nothing to add: every reviewed pair is already in the tables"
