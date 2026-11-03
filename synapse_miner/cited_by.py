"""
Build the NF Data Portal "Cited By" table from classified publications.

The table has the same columns as the portal publications table
(syn16857542), so study pages can show it with the same publication cards,
filtered on studyId. It lists papers that reused or cited a study's data
(secondary, review, mention); papers that generated the data (primary)
belong in the publications table instead, and unclear pairs wait for review.
"""

import json
import logging
import math
from typing import Dict, Iterable, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

CITED_BY_RELATIONSHIPS = ("secondary", "review", "mention")

# Same names, types and limits as syn16857542, then columns specific to Cited By
CITED_BY_SCHEMA = [
    {"name": "doi", "columnType": "LARGETEXT"},
    {"name": "diseaseFocus", "columnType": "STRING", "maximumSize": 30, "facetType": "enumeration"},
    {"name": "journal", "columnType": "STRING", "maximumSize": 500, "facetType": "enumeration"},
    {"name": "title", "columnType": "LARGETEXT"},
    {"name": "year", "columnType": "INTEGER", "facetType": "enumeration"},
    {"name": "pmid", "columnType": "STRING", "maximumSize": 50},
    {"name": "author", "columnType": "STRING_LIST", "maximumSize": 50, "maximumListLength": 50,
     "facetType": "enumeration"},
    {"name": "manifestation", "columnType": "STRING_LIST", "maximumSize": 30, "maximumListLength": 5,
     "facetType": "enumeration"},
    {"name": "fundingAgency", "columnType": "STRING_LIST", "maximumSize": 50, "maximumListLength": 8,
     "facetType": "enumeration"},
    {"name": "studyId", "columnType": "STRING_LIST", "maximumSize": 20, "maximumListLength": 5,
     "facetType": "enumeration"},
    {"name": "studyName", "columnType": "STRING_LIST", "maximumSize": 200, "maximumListLength": 5,
     "facetType": "enumeration"},
    {"name": "publicationType", "columnType": "STRING", "maximumSize": 20, "facetType": "enumeration"},
    {"name": "pmcid", "columnType": "STRING", "maximumSize": 20},
    {"name": "isPreprint", "columnType": "BOOLEAN", "facetType": "enumeration"},
    {"name": "confidence", "columnType": "STRING", "maximumSize": 10, "facetType": "enumeration"},
    {"name": "citedSynapseIds", "columnType": "STRING_LIST", "maximumSize": 20, "maximumListLength": 50},
    {"name": "evidence", "columnType": "LARGETEXT"},
]
CITED_BY_COLUMNS = [c["name"] for c in CITED_BY_SCHEMA]
_LIMITS = {c["name"]: c for c in CITED_BY_SCHEMA}


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or value == ""


def _fit_list(name: str, values: Iterable[str]) -> List[str]:
    """Trim a list to the column's item count and item length."""
    spec = _LIMITS[name]
    items = [str(v).strip()[:spec["maximumSize"]] for v in values if not _missing(v) and str(v).strip()]
    return items[:spec["maximumListLength"]]


def _fit(name: str, value) -> Optional[str]:
    if _missing(value):
        return None
    size = _LIMITS[name].get("maximumSize")
    return str(value)[:size] if size else str(value)


def build_cited_by(classified: pd.DataFrame, studies: Dict[str, Dict],
                   relationships: Iterable[str] = CITED_BY_RELATIONSHIPS) -> pd.DataFrame:
    """
    Cited By rows, one per (paper, study), in the publications table format.

    Args:
        classified: Output of classify_publications (or its CSV)
        studies: Output of study_resolver.load_studies
        relationships: Relationships to include

    Returns:
        DataFrame with CITED_BY_COLUMNS; list columns hold Python lists
    """
    keep = classified[classified["relationship"].isin(set(relationships))]
    rows = []
    for row in keep.itertuples(index=False):
        study = studies.get(row.study_id, {})
        disease = study.get("disease_focus", [])
        pmid = None if _missing(row.pmid) else f"PMID:{str(row.pmid).split('.')[0]}"
        authors = [] if _missing(row.authors) else str(row.authors).split("; ")
        rows.append({
            "doi": None if _missing(row.doi) else str(row.doi),
            "diseaseFocus": _fit("diseaseFocus", disease[0] if len(disease) == 1 else
                                 (", ".join(disease) if disease else None)),
            "journal": _fit("journal", row.journal),
            "title": None if _missing(row.title) else str(row.title),
            "year": None if _missing(row.year) else int(float(row.year)),
            "pmid": pmid,
            "author": _fit_list("author", authors),
            "manifestation": _fit_list("manifestation", study.get("manifestation", [])),
            "fundingAgency": _fit_list("fundingAgency", study.get("funding_agency", [])),
            "studyId": [row.study_id],
            "studyName": _fit_list("studyName", [row.study_name]),
            "publicationType": row.relationship,
            "pmcid": _fit("pmcid", row.pmcid),
            "isPreprint": bool(row.is_preprint) if not _missing(row.is_preprint) else False,
            "confidence": _fit("confidence", row.confidence),
            "citedSynapseIds": _fit_list("citedSynapseIds", str(row.synids).split(", ")),
            "evidence": None if _missing(row.evidence) else str(row.evidence),
        })
    df = pd.DataFrame(rows, columns=CITED_BY_COLUMNS)
    df["year"] = df["year"].astype("Int64")
    logger.info(f"Built {len(df)} Cited By rows for {df['studyId'].map(tuple).nunique()} studies")
    return df


def _for_upload(df: pd.DataFrame) -> pd.DataFrame:
    """Encode list columns as JSON arrays, the format Synapse expects in CSV uploads."""
    out = df.copy()
    for spec in CITED_BY_SCHEMA:
        if spec["columnType"].endswith("_LIST"):
            out[spec["name"]] = out[spec["name"]].map(lambda v: json.dumps(list(v)))
    return out


def create_cited_by_table(syn, parent_id: str, name: str = "Portal - Cited By") -> str:
    """Create an empty Cited By table under a project and return its Synapse ID."""
    from synapseclient import Column, Schema
    columns = [Column(**spec) for spec in CITED_BY_SCHEMA]
    table = syn.store(Schema(name=name, columns=columns, parent=parent_id))
    logger.info(f"Created Cited By table {table.id} in {parent_id}")
    return table.id


def replace_cited_by_rows(syn, table_id: str, df: pd.DataFrame) -> None:
    """
    Replace every row of the Cited By table with the given rows.

    The table is generated, so each run rewrites it in full; rows edited by
    hand are overwritten. New rows are stored before old ones are deleted, so
    a failed upload leaves the previous contents in place.
    """
    from synapseclient import Table
    old_row_ids = [str(i) for i in syn.tableQuery(f"SELECT ROW_ID FROM {table_id}")
                   .asDataFrame(rowIdAndVersionInIndex=False)["ROW_ID"]]
    if not df.empty:
        syn.store(Table(table_id, _for_upload(df)))
    logger.info(f"Stored {len(df)} rows in {table_id}")
    for i in range(0, len(old_row_ids), 500):
        chunk = ",".join(old_row_ids[i:i + 500])
        syn.delete(syn.tableQuery(f"SELECT ROW_ID, ROW_VERSION FROM {table_id} WHERE ROW_ID IN ({chunk})"))
    if old_row_ids:
        logger.info(f"Deleted {len(old_row_ids)} previous rows from {table_id}")
