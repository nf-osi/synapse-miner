"""
EBI Search XML generation from Synapse mining results.

Each entry in the output represents a unique Synapse entity. PMC articles
that cite it appear as cross-references. Portal membership is resolved via
the same two-table lookup that powers the Synapse portal banner:
  syn61609402 — data catalog: maps entity IDs to portal appId + link
  syn45291362 — source app config: maps appId to friendlyName

Both tables are fetched once into memory before processing. Entity names
are retrieved in batches of 100 via /entity/header/batch. Portal affiliation
is resolved in-memory using each entity's benefactorId (its parent project)
as the lookup key — eliminating per-entity table queries entirely.
"""

import json
import logging
import os
from datetime import date
from typing import Dict, List, Optional, Set, Tuple

import math

import pandas as pd
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

_DATA_CATALOG_TABLE = "syn61609402"
_SOURCE_APP_CONFIG_TABLE = "syn45291362"
_BATCH_HEADER_SIZE = 100


def _load_portal_catalog(syn) -> Tuple[Dict[str, Tuple[str, Optional[str]]], Dict[str, str]]:
    """
    Fetch the data catalog and source app config tables once into memory.

    Returns:
        catalog: dict mapping cataloged entity ID -> (friendlyName, link)
        app_names: dict mapping appId -> friendlyName (kept for diagnostics)
    """
    logger.info("Loading portal catalog tables into memory ...")

    catalog_df = syn.tableQuery(
        f"SELECT id, appId, link FROM {_DATA_CATALOG_TABLE}"
    ).asDataFrame()
    logger.info(f"  {len(catalog_df)} entries in data catalog ({_DATA_CATALOG_TABLE})")

    name_df = syn.tableQuery(
        f"SELECT appId, friendlyName FROM {_SOURCE_APP_CONFIG_TABLE}"
    ).asDataFrame()
    app_names: Dict[str, str] = dict(zip(name_df["appId"], name_df["friendlyName"]))
    logger.info(f"  {len(app_names)} portal configs ({_SOURCE_APP_CONFIG_TABLE})")

    def _nan_to_none(v):
        return None if (v is None or (isinstance(v, float) and math.isnan(v))) else v

    catalog: Dict[str, Tuple[str, Optional[str]]] = {}
    for _, row in catalog_df.iterrows():
        entity_id = str(row["id"])
        app_id = str(_nan_to_none(row["appId"]) or "")
        link: Optional[str] = str(row["link"]) if _nan_to_none(row.get("link")) else None
        friendly_name = app_names.get(app_id, "Synapse")
        catalog[entity_id] = (friendly_name, link)

    return catalog, app_names


def _fetch_entity_headers_batch(syn, syn_ids: List[str]) -> Dict[str, Optional[Dict]]:
    """
    Batch-fetch EntityHeader for a list of syn IDs via POST /entity/header/batch.

    Each header includes at minimum 'name' and 'benefactorId'. Processed in
    chunks of 100 (Synapse API limit).

    Entities absent from the response are inaccessible (private or deleted) and
    are returned as None. On a chunk-level request failure all entities in that
    chunk are also returned as None.

    Returns:
        dict mapping synId -> {name, benefactorId}, or None if inaccessible
    """
    results: Dict[str, Optional[Dict]] = {}
    total = len(syn_ids)

    for i in range(0, total, _BATCH_HEADER_SIZE):
        chunk = syn_ids[i : i + _BATCH_HEADER_SIZE]
        if (i // _BATCH_HEADER_SIZE) % 10 == 0:
            logger.info(f"  Fetching entity headers {i + 1}–{min(i + _BATCH_HEADER_SIZE, total)} of {total} ...")
        # Pre-mark all as None; successful responses will overwrite
        for sid in chunk:
            results[sid] = None
        try:
            response = syn.restPOST(
                "/entity/header",
                body={"references": [{"targetId": sid} for sid in chunk]},
            )
            for header in response.get("results", []):
                results[header["id"]] = {
                    "name": header.get("name") or header["id"],
                    "benefactorId": header.get("benefactorId"),
                }
        except Exception as e:
            logger.warning(f"Batch header fetch failed for chunk starting at {i}: {e}")
            # All entries in chunk remain None

    return results


def _resolve_portal(
    syn_id: str,
    benefactor_id: Optional[str],
    catalog: Dict[str, Tuple[str, Optional[str]]],
) -> Tuple[str, Optional[str]]:
    """
    Look up portal affiliation in memory.

    Checks the entity itself first (it may be directly registered), then its
    benefactor (typically the parent project). Returns ("Synapse", None) if
    neither is in the catalog.
    """
    for check_id in filter(None, [syn_id, benefactor_id]):
        if check_id in catalog:
            return catalog[check_id]
    return "Synapse", None


def load_cache(cache_path: str) -> Dict:
    """Load the entity metadata cache from a JSON file."""
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load cache from {cache_path}: {e}")
    return {}


def _save_cache(cache: Dict, cache_path: str) -> None:
    """Persist the entity metadata cache to disk."""
    os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2)
    logger.debug(f"Saved cache ({len(cache)} entries) to {cache_path}")


def generate_ebisearch_xml(
    syn,
    df: pd.DataFrame,
    output_path: str,
    cache_path: str,
    refresh: bool = False,
    db_name: str = "Sage Bionetworks Synapse",
    db_description: str = (
        "Datasets available via Synapse, the Sage Bionetworks data sharing platform"
    ),
) -> None:
    """
    Generate an EBI Search-format XML file from a DataFrame of (pmcid, synid) pairs.

    Each XML entry represents one unique Synapse entity with its PMC citations
    as cross-references and its portal affiliation as the repository field.

    Portal tables are fetched once into memory. Entity names are retrieved in
    batches of 100. All lookups are then done in memory — no per-entity table
    queries.

    Args:
        syn: Authenticated synapseclient.Synapse instance.
        df: DataFrame with at least 'pmcid' and 'synid' columns.
        output_path: Where to write the XML file.
        cache_path: Path to the JSON metadata cache.
        refresh: When True, re-fetch all metadata and overwrite the cache.
        db_name: <name> element for the EBI Search database section.
        db_description: <description> element for the database section.
    """
    cache = {} if refresh else load_cache(cache_path)

    # Normalise pmcid: strip the bioregistry 'pmc:' prefix stored in the table
    df = df.copy()
    if "pmcid" in df.columns:
        df["pmcid"] = df["pmcid"].str.replace(r"^pmc:", "", regex=True)

    # Group all citing PMC IDs by Synapse entity ID
    syn_to_pmcs: Dict[str, Set[str]] = {}
    for _, row in df.iterrows():
        syn_id = row.get("synid")
        pmc_id = row.get("pmcid")
        if syn_id and pmc_id:
            syn_to_pmcs.setdefault(syn_id, set()).add(pmc_id)

    all_syn_ids = sorted(syn_to_pmcs.keys())
    logger.info(f"Found {len(all_syn_ids)} unique Synapse IDs in table")

    uncached = [s for s in all_syn_ids if s not in cache]

    if uncached:
        logger.info(f"{len(uncached)} entities not in cache — fetching metadata ...")

        # --- Load portal tables once ---
        catalog, _ = _load_portal_catalog(syn)

        # --- Batch-fetch entity headers ---
        logger.info(f"Batch-fetching entity headers ({_BATCH_HEADER_SIZE} per request) ...")
        headers = _fetch_entity_headers_batch(syn, uncached)

        # --- Populate cache; skip inaccessible (private/deleted) entities ---
        inaccessible = [s for s in uncached if headers.get(s) is None]
        if inaccessible:
            logger.info(
                f"Skipping {len(inaccessible)} inaccessible (private/deleted) entities"
            )

        for syn_id in uncached:
            header = headers.get(syn_id)
            if header is None:
                continue  # not accessible — exclude from XML

            name = header.get("name") or syn_id
            benefactor_id = header.get("benefactorId")
            repository, portal_link = _resolve_portal(syn_id, benefactor_id, catalog)

            cache[syn_id] = {
                "name": name,
                "description": name,
                "created_on": "",
                "repository": repository,
                "portal_link": portal_link,
            }

        _save_cache(cache, cache_path)
        logger.info("Metadata fetch complete")

    # Only include entities that are accessible (present in cache)
    unique_syn_ids = [s for s in all_syn_ids if s in cache]
    skipped = len(all_syn_ids) - len(unique_syn_ids)
    if skipped:
        logger.info(f"Excluding {skipped} inaccessible entities from XML ({len(unique_syn_ids)} remaining)")
    logger.info(f"Building EBI Search XML for {len(unique_syn_ids)} entities")

    release_date = date.today().isoformat()

    database = ET.Element("database")
    ET.SubElement(database, "name").text = db_name
    ET.SubElement(database, "description").text = db_description
    ET.SubElement(database, "release").text = release_date
    ET.SubElement(database, "release_date").text = release_date
    ET.SubElement(database, "entry_count").text = str(len(unique_syn_ids))

    entries_el = ET.SubElement(database, "entries")

    for syn_id in unique_syn_ids:
        meta = cache.get(syn_id, {})
        name = meta.get("name") or syn_id
        description = meta.get("description") or name
        created_on = meta.get("created_on") or ""
        repository = meta.get("repository") or "Synapse"
        portal_link = meta.get("portal_link")
        full_link = portal_link or f"https://www.synapse.org/Synapse/{syn_id}"

        entry = ET.SubElement(entries_el, "entry")
        entry.set("id", syn_id)

        ET.SubElement(entry, "name").text = name
        ET.SubElement(entry, "description").text = description

        if created_on:
            dates_el = ET.SubElement(entry, "dates")
            date_el = ET.SubElement(dates_el, "date")
            date_el.set("type", "submission")
            date_el.set("value", created_on)

        xrefs_el = ET.SubElement(entry, "cross_references")
        for pmc_id in sorted(syn_to_pmcs[syn_id]):
            ref = ET.SubElement(xrefs_el, "ref")
            ref.set("dbname", "PMC")
            ref.set("dbkey", pmc_id)

        additional_el = ET.SubElement(entry, "additional_fields")

        repo_field = ET.SubElement(additional_el, "field")
        repo_field.set("name", "repository")
        repo_field.text = repository

        link_field = ET.SubElement(additional_el, "field")
        link_field.set("name", "full_dataset_link")
        link_field.text = full_link

    tree = ET.ElementTree(database)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    tree.write(output_path, encoding="UTF-8", xml_declaration=True)

    logger.info(f"Wrote {len(unique_syn_ids)} entries to {output_path}")
