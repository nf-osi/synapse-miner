"""
EBI Search XML generation from Synapse mining results.

Each entry in the output represents a unique Synapse entity. PMC articles
that cite it appear as cross-references. Portal membership is resolved via
the same two-table lookup that powers the Synapse portal banner:
  syn61609402 — data catalog: maps entity/ancestor IDs to portal appId + link
  syn45291362 — source app config: maps appId to friendlyName
"""

import json
import logging
import os
from datetime import date
from typing import Dict, Optional, Tuple

import pandas as pd
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

_DATA_CATALOG_TABLE = "syn61609402"
_SOURCE_APP_CONFIG_TABLE = "syn45291362"


def _parse_date(iso_str: str) -> str:
    """Extract YYYY-MM-DD from an ISO 8601 timestamp string."""
    if iso_str:
        return iso_str[:10]
    return ""


def _get_entity_info(syn, syn_id: str) -> Dict:
    """Fetch name, description, and creation date from the Synapse REST API."""
    try:
        entity = syn.restGET(f"/entity/{syn_id}")
        return {
            "name": entity.get("name") or syn_id,
            "description": entity.get("description") or "",
            "created_on": _parse_date(entity.get("createdOn", "")),
        }
    except Exception as e:
        logger.warning(f"Could not fetch entity info for {syn_id}: {e}")
        return {"name": syn_id, "description": "", "created_on": ""}


def _get_portal_info(syn, syn_id: str) -> Tuple[str, Optional[str]]:
    """
    Resolve which portal (if any) a Synapse entity belongs to.

    Walks the entity's ancestor path and queries syn61609402 for a matching
    appId, then looks up the human-readable portal name in syn45291362.
    Returns ("Synapse", None) when the entity has no portal affiliation.
    """
    try:
        path_data = syn.restGET(f"/entity/{syn_id}/path")
        # Index 0 is always the Synapse root folder; skip it.
        path_ids = [h["id"] for h in path_data.get("path", [])[1:]]
    except Exception as e:
        logger.warning(f"Could not fetch entity path for {syn_id}: {e}")
        return "Synapse", None

    if not path_ids:
        return "Synapse", None

    try:
        ids_csv = ",".join(f"'{pid}'" for pid in path_ids)
        catalog_results = syn.tableQuery(
            f"SELECT appId, link FROM {_DATA_CATALOG_TABLE} WHERE id IN ({ids_csv})"
        )
        catalog_df = catalog_results.asDataFrame()
    except Exception as e:
        logger.warning(f"Could not query data catalog for {syn_id}: {e}")
        return "Synapse", None

    if catalog_df.empty:
        return "Synapse", None

    app_id = catalog_df.iloc[0]["appId"]
    link = catalog_df.iloc[0].get("link") or None

    try:
        name_results = syn.tableQuery(
            f"SELECT friendlyName FROM {_SOURCE_APP_CONFIG_TABLE} WHERE appId = '{app_id}'"
        )
        name_df = name_results.asDataFrame()
        friendly_name = name_df.iloc[0]["friendlyName"] if not name_df.empty else "Synapse"
    except Exception as e:
        logger.warning(f"Could not fetch portal name for appId {app_id}: {e}")
        friendly_name = "Synapse"

    return friendly_name, link


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
    syn_to_pmcs: Dict[str, set] = {}
    for _, row in df.iterrows():
        syn_id = row.get("synid")
        pmc_id = row.get("pmcid")
        if syn_id and pmc_id:
            syn_to_pmcs.setdefault(syn_id, set()).add(pmc_id)

    unique_syn_ids = sorted(syn_to_pmcs.keys())
    logger.info(f"Building EBI Search XML for {len(unique_syn_ids)} unique Synapse IDs")

    # Fetch metadata for any syn IDs absent from the cache
    uncached = [s for s in unique_syn_ids if s not in cache]
    if uncached:
        logger.info(f"Fetching metadata for {len(uncached)} uncached entities ...")
        for i, syn_id in enumerate(uncached, 1):
            if i % 100 == 0:
                logger.info(f"  {i}/{len(uncached)} ...")
                _save_cache(cache, cache_path)

            entity_info = _get_entity_info(syn, syn_id)
            repository, portal_link = _get_portal_info(syn, syn_id)

            cache[syn_id] = {
                "name": entity_info["name"],
                "description": entity_info["description"],
                "created_on": entity_info["created_on"],
                "repository": repository,
                "portal_link": portal_link,
            }

        _save_cache(cache, cache_path)
        logger.info("Metadata fetch complete")

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
