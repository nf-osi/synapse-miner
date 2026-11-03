"""
Map Synapse IDs found in articles to the NF Data Portal studies they belong to.

A study is a Synapse project listed in the portal's studies view. An entity
belongs to a study when it is the study project or sits inside it. Entity
headers (fetched 100 at a time) give each entity's benefactor, which is its
project unless a folder inside has its own sharing settings; only those
entities need a per-entity path lookup.
"""

import json
import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List, Optional

import pandas as pd

from .ebisearch_generator import _fetch_entity_headers_batch

logger = logging.getLogger(__name__)

STUDIES_VIEW = "syn52677631"
PUBLICATIONS_TABLE = "syn16857542"


def _as_list(value) -> List[str]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return [str(v) for v in parsed] if isinstance(parsed, list) else [value]
        except json.JSONDecodeError:
            return [value]
    return [str(v) for v in value]


def load_studies(syn, view_id: str = STUDIES_VIEW) -> Dict[str, Dict]:
    """Portal studies keyed by project ID, with name, leads, funders and institutions."""
    df = syn.tableQuery(
        f"SELECT id, studyName, studyLeads, fundingAgency, institutions, initiative FROM {view_id}"
    ).asDataFrame()
    studies = {}
    for _, row in df.iterrows():
        studies[str(row["id"])] = {
            "study_id": str(row["id"]),
            "study_name": row["studyName"],
            "study_leads": _as_list(row["studyLeads"]),
            "funding_agency": _as_list(row["fundingAgency"]),
            "institutions": _as_list(row["institutions"]),
            "initiative": None if pd.isna(row["initiative"]) else row["initiative"],
        }
    logger.info(f"Loaded {len(studies)} studies from {view_id}")
    return studies


def load_tracked_publications(syn, table_id: str = PUBLICATIONS_TABLE) -> Dict[str, Dict]:
    """
    Publications already tracked by the portal.

    Returns:
        dict mapping 'pmid:<id>' and 'doi:<lowercase doi>' -> {study_ids, publication_type}
    """
    df = syn.tableQuery(f"SELECT pmid, doi, studyId, publicationType FROM {table_id}").asDataFrame()
    tracked: Dict[str, Dict] = {}
    for _, row in df.iterrows():
        keys = []
        pmid = "".join(ch for ch in str(row["pmid"]) if ch.isdigit()) if not pd.isna(row["pmid"]) else ""
        if pmid:
            keys.append(f"pmid:{pmid}")
        if not pd.isna(row["doi"]) and str(row["doi"]).strip():
            keys.append(f"doi:{str(row['doi']).strip().lower().replace('https://doi.org/', '')}")
        for key in keys:
            entry = tracked.setdefault(key, {"study_ids": set(), "publication_type": set()})
            entry["study_ids"].update(_as_list(row["studyId"]))
            entry["publication_type"].update(_as_list(row["publicationType"]))
    return tracked


class StudyResolver:
    """Resolves Synapse IDs to portal study IDs, with an on-disk cache."""

    def __init__(self, syn, studies: Dict[str, Dict], cache_path: Optional[str] = None,
                 max_workers: int = 8):
        """
        Args:
            syn: Logged-in synapseclient.Synapse
            studies: Output of load_studies
            cache_path: JSON file caching synId -> project ID (None when inaccessible)
            max_workers: Parallel path lookups
        """
        self.syn = syn
        self.studies = studies
        self.cache_path = cache_path
        self.max_workers = max_workers
        self.cache: Dict[str, Optional[str]] = {}
        if cache_path and os.path.exists(cache_path):
            with open(cache_path) as f:
                self.cache = json.load(f)

    def _project_from_path(self, synid: str) -> Optional[str]:
        try:
            path = self.syn.restGET(f"/entity/{synid}/path")["path"]
            # path[0] is the root; path[1] is the project
            return path[1]["id"] if len(path) > 1 else None
        except Exception as e:
            logger.debug(f"Could not get path for {synid}: {e}")
            return None

    def resolve(self, synids: Iterable[str]) -> Dict[str, Optional[str]]:
        """
        Project ID for each Synapse ID (None when private, deleted or unknown).

        Only IDs not already cached are looked up.
        """
        ids = list(dict.fromkeys(synids))
        uncached = [s for s in ids if s not in self.cache]
        if uncached:
            logger.info(f"Resolving {len(uncached)} Synapse IDs to projects ...")
            headers = _fetch_entity_headers_batch(self.syn, uncached)
            need_path = []
            for synid in uncached:
                header = headers.get(synid)
                if header is None:
                    self.cache[synid] = None
                elif synid in self.studies:
                    self.cache[synid] = synid
                elif header.get("benefactorId") in self.studies:
                    self.cache[synid] = header["benefactorId"]
                else:
                    need_path.append(synid)
            if need_path:
                logger.info(f"Looking up project paths for {len(need_path)} entities ...")
                with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                    for synid, project in zip(need_path, pool.map(self._project_from_path, need_path)):
                        self.cache[synid] = project
            self._save()
            inaccessible = sum(self.cache[s] is None for s in uncached)
            logger.info(f"Resolved {len(uncached) - inaccessible}/{len(uncached)} IDs "
                        f"({inaccessible} private, deleted or invalid)")
        return {s: self.cache.get(s) for s in ids}

    def study_for(self, synid: str) -> Optional[str]:
        """Portal study ID for a resolved Synapse ID, or None when not in a portal study."""
        project = self.cache.get(synid)
        return project if project in self.studies else None

    def _save(self) -> None:
        if self.cache_path:
            os.makedirs(os.path.dirname(os.path.abspath(self.cache_path)), exist_ok=True)
            with open(self.cache_path, "w") as f:
                json.dump(self.cache, f)
