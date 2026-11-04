"""
Add classified papers to the NF Data Portal publication tables.

  primary pairs                        -> Portal - Publications (syn16857542)
  secondary / review / mention pairs   -> Portal - Cited By (syn78484103)
  unclear pairs                        -> neither; they wait for a human look

Both tables share the publications table's columns, so study pages show
them with the same publication cards filtered on studyId; Cited By adds a
few columns at the end. Rows are one per (paper, study) and are only ever
appended: a pair already in either table is skipped, so hand edits and
curated rows are never changed, and every write is snapshotted before and
after (see utils/synapse_safety.py).
"""

import html
import json
import logging
import math
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

import pandas as pd

from .utils.europepmc_client import author_names
from .utils.synapse_safety import run_url, snapshots_around

logger = logging.getLogger(__name__)

PRIMARY_RELATIONSHIPS = ("primary",)
CITED_BY_RELATIONSHIPS = ("secondary", "review", "mention")
# Primary pairs go into the curated publications table only when the wording
# was explicit (high) or backed by a study lead plus a deposit statement (medium)
PRIMARY_CONFIDENCE = ("high", "medium")

# Same names, types and limits as syn16857542 (publicationType is also faceted
# here, to filter secondary/review/mention), then columns specific to Cited By
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
# The publications table (syn16857542) has the first 12 columns
PUBLICATION_COLUMNS = CITED_BY_COLUMNS[:12]
_LIMITS = {c["name"]: c for c in CITED_BY_SCHEMA}


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or value == ""


# Short forms the publications table already uses for studies-view values
# longer than its 30-character manifestation limit
MANIFESTATION_SHORT_FORMS = {
    "Malignant Peripheral Nerve Sheath Tumor": "MPNST",
    "Juvenile Myelomonocytic Leukemia": "JMML",
}


def _fit_list(name: str, values: Iterable[str]) -> List[str]:
    """
    Fit a list to the column's item count and item length.

    Controlled values (manifestation, fundingAgency, studyId) are never cut
    off part way, which would make a new, wrong value: long manifestations
    use their short form, and any other value that is too long is dropped
    with a warning. Free text (author, studyName) is shortened.
    """
    spec = _LIMITS[name]
    size = spec["maximumSize"]
    items = []
    for value in values:
        if _missing(value) or not str(value).strip():
            continue
        value = str(value).strip()
        if name == "manifestation":
            value = MANIFESTATION_SHORT_FORMS.get(value, value)
        if len(value) > size:
            if name in ("author", "studyName"):
                value = value[:size]
            else:
                logger.warning(f"Leaving out {name} value longer than {size} characters: {value!r}")
                continue
        items.append(value)
    return items[:spec["maximumListLength"]]


def _plain_title(value) -> Optional[str]:
    """Title text without Europe PMC's inline markup (e.g. '<i>NF1</i>', '&lt;i&gt;')."""
    if _missing(value):
        return None
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(html.unescape(str(value))))).strip()


def _fit(name: str, value) -> Optional[str]:
    if _missing(value):
        return None
    size = _LIMITS[name].get("maximumSize")
    return str(value)[:size] if size else str(value)


def build_rows(classified: pd.DataFrame, studies: Dict[str, Dict], relationships: Iterable[str],
               confidences: Optional[Iterable[str]] = None) -> pd.DataFrame:
    """
    Portal rows, one per (paper, study), in the Cited By column layout.

    Args:
        classified: Output of classify_publications (or its CSV)
        studies: Output of study_resolver.load_studies
        relationships: Relationships to include
        confidences: Only include these confidence levels (all when None)

    Returns:
        DataFrame with CITED_BY_COLUMNS; list columns hold Python lists
    """
    keep = classified[classified["relationship"].isin(set(relationships))]
    if confidences is not None:
        keep = keep[keep["confidence"].isin(set(confidences))]
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
            "title": _plain_title(row.title),
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
    return df


def build_cited_by(classified: pd.DataFrame, studies: Dict[str, Dict]) -> pd.DataFrame:
    """Cited By rows: secondary, review and mention pairs at any confidence."""
    return build_rows(classified, studies, CITED_BY_RELATIONSHIPS)


def build_primary(classified: pd.DataFrame, studies: Dict[str, Dict]) -> pd.DataFrame:
    """Publications-table rows: primary pairs with high or medium confidence."""
    return build_rows(classified, studies, PRIMARY_RELATIONSHIPS, PRIMARY_CONFIDENCE)


def _pmid_digits(value) -> str:
    return "" if _missing(value) else "".join(ch for ch in str(value).split(".")[0] if ch.isdigit())


def _doi_key(value) -> str:
    return "" if _missing(value) else str(value).strip().lower().replace("https://doi.org/", "")


def _as_list(value) -> List[str]:
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    if _missing(value):
        return []
    try:
        parsed = json.loads(value)
        return [str(v) for v in parsed] if isinstance(parsed, list) else [str(value)]
    except (TypeError, json.JSONDecodeError):
        return [str(value)]


def pair_keys(df: pd.DataFrame) -> Set[Tuple[str, str]]:
    """('pmid:<n>' or 'doi:<doi>', studyId) for every study each row lists."""
    keys = set()
    for row in df.itertuples(index=False):
        ids = [f"pmid:{p}" for p in [_pmid_digits(row.pmid)] if p]
        ids += [f"doi:{d}" for d in [_doi_key(row.doi)] if d]
        for study_id in _as_list(row.studyId):
            keys.update((paper, study_id) for paper in ids)
    return keys


def load_pair_keys(syn, table_id: str) -> Set[Tuple[str, str]]:
    """Paper-study pairs already in a portal publication table."""
    df = syn.tableQuery(f"SELECT pmid, doi, studyId FROM {table_id}").asDataFrame()
    keys = pair_keys(df)
    logger.info(f"{table_id} already has {len(keys)} paper-study keys from {len(df)} rows")
    return keys


def drop_existing_pairs(df: pd.DataFrame, existing: Set[Tuple[str, str]]) -> pd.DataFrame:
    """Rows whose paper-study pair is in neither table yet."""
    if df.empty:
        return df
    new = [not (pair_keys(df.iloc[[i]]) & existing) for i in range(len(df))]
    return df[new].reset_index(drop=True)


def _for_upload(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    """Keep the table's columns and encode list columns as JSON arrays for the CSV upload."""
    out = df[columns].copy()
    for spec in CITED_BY_SCHEMA:
        if spec["name"] in columns and spec["columnType"].endswith("_LIST"):
            out[spec["name"]] = out[spec["name"]].map(lambda v: json.dumps(list(v)))
    return out


def append_rows(syn, table_id: str, df: pd.DataFrame, columns: List[str], action: str) -> int:
    """Append rows to a table, with a snapshot before and after. Returns rows added."""
    if df.empty:
        logger.info(f"No new rows for {table_id}")
        return 0
    from synapseclient import Table
    with snapshots_around(syn, table_id, action):
        syn.store(Table(table_id, _for_upload(df, columns)))
    logger.info(f"Appended {len(df)} rows to {table_id}")
    return len(df)


def create_cited_by_table(syn, parent_id: str, name: str = "Portal - Cited By") -> str:
    """Create an empty Cited By table under a project and return its Synapse ID."""
    from synapseclient import Column, Schema
    columns = [Column(**spec) for spec in CITED_BY_SCHEMA]
    table = syn.store(Schema(name=name, columns=columns, parent=parent_id))
    logger.info(f"Created Cited By table {table.id} in {parent_id}")
    return table.id


_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
# GitHub rejects issue bodies over 65,536 characters
_MAX_ISSUE_BODY = 60000


def not_added(classified: pd.DataFrame, existing: Set[Tuple[str, str]]) -> pd.DataFrame:
    """
    Pairs left out of both tables for low confidence: unclear pairs and
    low-confidence primary pairs not already in either table.
    """
    low = classified[(classified["relationship"] == "unclear") |
                     ((classified["relationship"] == "primary") & (classified["confidence"] == "low"))]
    if low.empty:
        return low
    keep = []
    for row in low.itertuples(index=False):
        ids = [f"pmid:{p}" for p in [_pmid_digits(row.pmid)] if p] + \
              [f"doi:{d}" for d in [_doi_key(row.doi)] if d]
        keep.append(not any((paper, row.study_id) in existing for paper in ids))
    return low[keep]


def left_out_key(row) -> str:
    """Stable key for a left-out pair: '<pmid, else pmcid, else doi>|<study>'."""
    paper = _pmid_digits(row.pmid) or (row.pmcid if not _missing(row.pmcid) else "") or _doi_key(row.doi)
    return f"{paper}|{row.study_id}"


def load_reported(path: str) -> Set[str]:
    """Left-out pair keys already reported in an issue."""
    try:
        with open(path) as f:
            return set(json.load(f).get("reported", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_reported(path: str, keys: Set[str]) -> None:
    with open(path, "w") as f:
        json.dump({"reported": sorted(keys)}, f, indent=2)
        f.write("\n")


def update_preprint_rows(syn, table_id: str, epmc, cited_by: bool = False) -> Tuple[List[Dict], List[Dict]]:
    """
    Point rows for preprints at their published versions, in place.

    PubMed links a preprint to its published version ("Update in"). For each
    row whose PMID is such a preprint, the paper columns (pmid, doi, title,
    journal, year, author; plus pmcid and isPreprint in Cited By) are
    replaced with the published version's; study columns are left alone.
    If the table already has the published version for the same study, the
    preprint row would become a duplicate, so it is reported for removal by
    hand instead (this package never deletes rows).

    Rows are changed with a partial-row update targeted by ROW_ID and
    checked against each row's etag, not Table.upsert_rows: upsert cannot
    key on studyId (a list column), needs its key values to be unique (a
    paper has one row per study), and cannot change its key (the PMID is
    what changes here).

    Returns:
        (rows updated, rows to remove by hand), each a list of dicts with
        table, row_id, preprint_pmid, published_pmid, title and studies
    """
    from synapseclient import PartialRowset
    current = syn.tableQuery(f"SELECT pmid, title, studyId FROM {table_id}") \
                 .asDataFrame(rowIdAndVersionInIndex=False)
    current["pmid_digits"] = current["pmid"].map(_pmid_digits)
    meta = epmc.get_metadata_by_pmid([p for p in current["pmid_digits"] if p])
    published_of = {p: m["updated_in"][0] for p, m in meta.items() if m.get("updated_in")}
    if not published_of:
        return [], []
    published = epmc.get_metadata_by_pmid(set(published_of.values()))
    have = {(p, s) for p, studies in zip(current["pmid_digits"], current["studyId"]) for s in _as_list(studies)}

    changes, updated, manual = {}, [], []
    for row in current.itertuples(index=False):
        published_pmid = published_of.get(row.pmid_digits)
        if not published_pmid:
            continue
        studies = _as_list(row.studyId)
        record = {"table": table_id, "row_id": int(row.ROW_ID), "preprint_pmid": row.pmid_digits,
                  "published_pmid": published_pmid, "title": _plain_title(row.title), "studies": studies}
        if any((published_pmid, s) in have for s in studies):
            manual.append(record)
            continue
        m = published.get(published_pmid)
        if not m:
            logger.warning(f"No metadata for PMID {published_pmid}, the published version of {row.pmid}")
            continue
        values = {
            "pmid": f"PMID:{published_pmid}",
            "doi": m.get("doi"),
            "title": _plain_title(m.get("title")),
            "journal": _fit("journal", m.get("journal")),
            "year": int(m["year"]) if m.get("year") else None,
            "author": _fit_list("author", author_names(m)),
        }
        if cited_by:
            values.update({"pmcid": _fit("pmcid", m.get("pmcid")), "isPreprint": False})
        changes[int(row.ROW_ID)] = values
        updated.append({**record, "title": values["title"]})

    if changes:
        ids = ",".join(str(i) for i in changes)
        columns = ", ".join(f'"{c}"' for c in next(iter(changes.values())))
        with snapshots_around(syn, table_id, f"classify replaces {len(changes)} preprints with published versions"):
            # Query after the "before" snapshot so the row etags are current
            fresh = syn.tableQuery(f"SELECT {columns} FROM {table_id} WHERE ROW_ID IN ({ids})")
            syn.store(PartialRowset.from_mapping(changes, fresh))
        logger.info(f"Replaced {len(changes)} preprint rows in {table_id} with their published versions")
    if manual:
        logger.warning(f"{len(manual)} preprint rows in {table_id} duplicate their published version; "
                       "remove them by hand")
    return updated, manual


def _paper_link(pmid: str, title: str) -> str:
    title = (title or "")[:90].replace("|", "/")
    return f"[{title}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/) PMID:{pmid}"


def review_issue(additions: Dict[str, pd.DataFrame], replaced: Optional[List[Dict]] = None,
                 to_remove: Optional[List[Dict]] = None,
                 left_out: Optional[pd.DataFrame] = None,
                 left_out_total: Optional[int] = None) -> Optional[Tuple[str, str]]:
    """
    Title and Markdown body for an issue listing this run's changes, or None
    when the run changed nothing.

    Args:
        additions: table ID -> rows appended to it in this run (lowest confidence listed first)
        replaced: preprint rows updated to their published versions
        to_remove: preprint rows that duplicate their published version
        left_out: low-confidence pairs left out of both tables that have not
            been reported in an earlier issue
        left_out_total: all low-confidence pairs currently left out, including
            ones reported before (defaults to len(left_out))
    """
    replaced, to_remove = replaced or [], to_remove or []
    left_out = left_out if left_out is not None else pd.DataFrame()
    total = sum(len(df) for df in additions.values())
    if not (total or replaced or to_remove or not left_out.empty):
        return None
    left_out_total = len(left_out) if left_out_total is None else left_out_total
    url = run_url()
    summary = ([f"{total} rows added"] if total else []) \
              + ([f"{len(replaced)} preprints replaced by their published versions"] if replaced else []) \
              + ([f"{len(to_remove)} preprint rows to remove by hand"] if to_remove else []) \
              + ([f"{len(left_out)} new low-confidence pairs not added"] if not left_out.empty else [])
    lines = [
        f"This run of the NF Data Portal publication pipeline: {', '.join(summary)}. "
        + ("Please check the additions, especially the lower-confidence rows at the top of each table, "
           "and fix or remove any that are wrong. " if total else "")
        + ("Add any left-out pairs that belong by hand." if not left_out.empty else ""),
        "",
        "- **primary** rows go to the publications table: the paper generated or deposited the study's data.",
        "- **secondary / review / mention** rows go to the Cited By table: the paper reused, "
        "reviewed or cited the study's data.",
        "",
    ]
    if url:
        lines += [f"Workflow run: {url} (its `classified_publications.csv` artifact has every pair)", ""]
    for table_id, df in additions.items():
        if df.empty:
            continue
        ordered = df.assign(_order=df["confidence"].map(_CONFIDENCE_ORDER).fillna(-1)) \
                    .sort_values(["_order", "year"], ascending=[True, False])
        lines += [f"### Added to [{table_id}](https://www.synapse.org/Synapse:{table_id}/tables/) ({len(df)} rows)", "",
                  "| Confidence | Relationship | Paper | Study | Evidence |", "|---|---|---|---|---|"]
        for row in ordered.itertuples(index=False):
            paper_id = row.pmid or (f"doi:{row.doi}" if row.doi else row.pmcid)
            link = f"https://doi.org/{row.doi}" if row.doi else f"https://europepmc.org/article/PMC/{row.pmcid}"
            title = str(row.title or "")[:90].replace("|", "/")
            evidence = str(row.evidence or "").split("\n")[0][:200].replace("|", "/")
            preprint = " (preprint)" if row.isPreprint else ""
            lines.append(f"| {row.confidence} | {row.publicationType} | [{title}]({link}) {paper_id}{preprint} "
                         f"| {row.studyId[0]} {row.studyName[0][:60] if row.studyName else ''} | {evidence} |")
        lines.append("")
    if replaced:
        lines += [f"### Preprints replaced by their published versions ({len(replaced)})", "",
                  "| Table | Preprint | Published version | Studies |", "|---|---|---|---|"]
        lines += [f"| {r['table']} | PMID:{r['preprint_pmid']} | {_paper_link(r['published_pmid'], r['title'])} "
                  f"| {', '.join(r['studies'])} |" for r in replaced]
        lines.append("")
    if to_remove:
        lines += [f"### Preprint rows to remove by hand ({len(to_remove)})", "",
                  "These preprints' published versions are already in the same table for the same study, "
                  "so the preprint row is a duplicate. Automation never deletes rows.", "",
                  "| Table | ROW_ID | Preprint | Published version | Studies |", "|---|---|---|---|---|"]
        lines += [f"| {r['table']} | {r['row_id']} | {_paper_link(r['preprint_pmid'], r['title'])} "
                  f"| PMID:{r['published_pmid']} | {', '.join(r['studies'])} |" for r in to_remove]
        lines.append("")
    if not left_out.empty:
        earlier = left_out_total - len(left_out)
        lines += [f"### Not added: {len(left_out)} new low-confidence pairs", "",
                  "These were left out of both tables (unclear, or primary with low confidence). "
                  "Add any that belong by hand."
                  + (f" {earlier} more were reported in earlier issues and are still left out; all "
                     f"{left_out_total} are in the run's `classified_publications.csv`." if earlier > 0 else ""),
                  "", "<details><summary>Show them</summary>", "",
                  "| Relationship | Paper | Study | Reason | Evidence |", "|---|---|---|---|---|"]
        for row in left_out.itertuples(index=False):
            pmid = _pmid_digits(row.pmid)
            paper = _paper_link(pmid, _plain_title(row.title)) if pmid else f"{row.pmcid} {_plain_title(row.title) or ''}"[:120]
            study_name = str(getattr(row, "study_name", "") or "")[:60]
            evidence = str(row.evidence or "").split("\n")[0][:250].replace("|", "/")
            lines.append(f"| {row.relationship} ({row.confidence}) | {paper} | {row.study_id} {study_name} "
                         f"| {str(row.reason).replace('|', '/')} | {evidence} |")
        lines += ["", "</details>", ""]
    title = (f"Review publication table changes ({pd.Timestamp.today().date().isoformat()})"
             if (total or replaced or to_remove) else
             f"Review {len(left_out)} low-confidence publication pairs ({pd.Timestamp.today().date().isoformat()})")
    body = "\n".join(lines)
    if len(body) > _MAX_ISSUE_BODY:
        cut = body.rfind("\n", 0, _MAX_ISSUE_BODY - 200)
        body = body[:cut] + "\n\n_List truncated to fit GitHub's issue size limit; see the run's CSV artifacts._"
    return title, body
