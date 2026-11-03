"""
Europe PMC REST client for article metadata and full text.

Responses are cached on disk so repeated classification runs only fetch
articles they have not seen before.
"""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List, Optional

import requests

logger = logging.getLogger(__name__)

EUROPEPMC_REST = "https://www.ebi.ac.uk/europepmc/webservices/rest"
_METADATA_BATCH_SIZE = 50
_USER_AGENT = "synapse-miner (https://github.com/nf-osi/synapse-miner)"


def normalize_pmcid(pmcid: str) -> str:
    """'pmc:PMC123' / 'PMC123' / '123' -> 'PMC123'."""
    value = str(pmcid).strip()
    if value.lower().startswith("pmc:"):
        value = value[4:]
    return value if value.upper().startswith("PMC") else f"PMC{value}"


class EuropePMCClient:
    """Fetches article metadata and JATS full text from Europe PMC."""

    def __init__(self, cache_dir: Optional[str] = None, max_workers: int = 4,
                 retries: int = 3, timeout: int = 60):
        """
        Args:
            cache_dir: Directory for cached responses (no caching when None)
            max_workers: Parallel requests for full text
            retries: Attempts per request before giving up
            timeout: Seconds per request
        """
        self.cache_dir = cache_dir
        self.max_workers = max_workers
        self.retries = retries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = _USER_AGENT
        if cache_dir:
            os.makedirs(os.path.join(cache_dir, "fulltext"), exist_ok=True)
        self._metadata = self._load_json("metadata.json")

    def _load_json(self, name: str) -> Dict:
        if not self.cache_dir:
            return {}
        path = os.path.join(self.cache_dir, name)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Ignoring unreadable cache {path}: {e}")
        return {}

    def _save_metadata(self) -> None:
        if self.cache_dir:
            with open(os.path.join(self.cache_dir, "metadata.json"), "w") as f:
                json.dump(self._metadata, f)

    def _get(self, url: str, params: Optional[Dict] = None) -> Optional[requests.Response]:
        """GET with retries on network errors and 429/5xx; returns None on 404."""
        delay = 2
        for attempt in range(self.retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                if response.status_code == 404:
                    return None
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {response.status_code}")
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                if attempt == self.retries - 1:
                    raise
                logger.debug(f"Retrying {url} after error: {e}")
                time.sleep(delay)
                delay *= 2
        return None

    def search(self, query: str) -> List[Dict]:
        """All Europe PMC search results for a query (id, source, pmcid, pmid, doi, title)."""
        results, cursor = [], "*"
        while True:
            response = self._get(f"{EUROPEPMC_REST}/search", params={
                "query": query, "format": "json", "resultType": "lite",
                "pageSize": 1000, "cursorMark": cursor,
            })
            page = response.json() if response else {}
            batch = page.get("resultList", {}).get("result", [])
            results.extend(batch)
            next_cursor = page.get("nextCursorMark")
            if not batch or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        logger.info(f"Europe PMC: {len(results)} articles match {query}")
        return [{k: r.get(k) for k in ("id", "source", "pmcid", "pmid", "doi", "title", "pubYear")}
                for r in results]

    def get_metadata(self, pmcids: Iterable[str]) -> Dict[str, Dict]:
        """
        Article metadata keyed by PMCID.

        Each value has pmcid, pmid, doi, title, journal, year, pub_date,
        pub_types, is_open_access, authors (Europe PMC author dicts) and
        updated_in (PMIDs of the published versions of a preprint).
        PMCIDs Europe PMC does not know are omitted.
        """
        wanted = [normalize_pmcid(p) for p in pmcids]
        # Entries cached before updated_in was recorded are fetched again
        missing = [p for p in dict.fromkeys(wanted)
                   if p not in self._metadata or "updated_in" not in self._metadata[p]]
        for i in range(0, len(missing), _METADATA_BATCH_SIZE):
            chunk = missing[i:i + _METADATA_BATCH_SIZE]
            query = " OR ".join(f"PMCID:{p}" for p in chunk)
            response = self._get(f"{EUROPEPMC_REST}/search", params={
                "query": query, "format": "json", "resultType": "core",
                "pageSize": 1000,
            })
            results = response.json().get("resultList", {}).get("result", []) if response else []
            for article in results:
                pmcid = article.get("pmcid")
                if pmcid:
                    self._metadata[pmcid] = _summarize(article)
            # A PMCID merged into another record (e.g. an author manuscript and
            # the published version) comes back under the other PMCID, so look
            # those up one at a time and store them under the requested ID
            for pmcid in chunk:
                if pmcid in self._metadata and "updated_in" in self._metadata[pmcid]:
                    continue
                single = self._get(f"{EUROPEPMC_REST}/search", params={
                    "query": f"PMCID:{pmcid}", "format": "json", "resultType": "core"})
                found = single.json().get("resultList", {}).get("result", []) if single else []
                if found:
                    self._metadata[pmcid] = _summarize(found[0])
            logger.info(f"Fetched metadata for {min(i + _METADATA_BATCH_SIZE, len(missing))}/{len(missing)} articles")
            self._save_metadata()
        return {p: self._metadata[p] for p in wanted if p in self._metadata}

    def get_metadata_by_pmid(self, pmids: Iterable[str]) -> Dict[str, Dict]:
        """
        Article metadata keyed by PMID, for papers that may have no PMCID
        (e.g. the published version of a preprint in a paywalled journal).
        """
        wanted = [str(p).split(".")[0] for p in pmids if str(p).strip()]
        by_pmid = self._metadata.setdefault("_by_pmid", {})
        missing = [p for p in dict.fromkeys(wanted) if p not in by_pmid]
        for i in range(0, len(missing), _METADATA_BATCH_SIZE):
            chunk = missing[i:i + _METADATA_BATCH_SIZE]
            query = " OR ".join(f"EXT_ID:{p}" for p in chunk)
            response = self._get(f"{EUROPEPMC_REST}/search", params={
                "query": f"({query}) AND SRC:MED", "format": "json", "resultType": "core",
                "pageSize": 1000,
            })
            for article in (response.json().get("resultList", {}).get("result", []) if response else []):
                if article.get("pmid"):
                    by_pmid[article["pmid"]] = _summarize(article)
            self._save_metadata()
        return {p: by_pmid[p] for p in wanted if p in by_pmid}

    def get_fulltext(self, pmcid: str) -> Optional[str]:
        """JATS full-text XML, or None when Europe PMC has no full text."""
        pmcid = normalize_pmcid(pmcid)
        path = os.path.join(self.cache_dir, "fulltext", f"{pmcid}.xml") if self.cache_dir else None
        missing_marker = f"{path}.missing" if path else None
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
        if missing_marker and os.path.exists(missing_marker):
            return None
        try:
            response = self._get(f"{EUROPEPMC_REST}/{pmcid}/fullTextXML")
        except requests.RequestException as e:
            # Europe PMC answers 500 for some non-open-access articles
            logger.debug(f"No full text for {pmcid}: {e}")
            response = None
        if response is None:
            if missing_marker:
                open(missing_marker, "w").close()
            return None
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(response.text)
        return response.text

    def get_fulltexts(self, pmcids: Iterable[str]) -> Dict[str, Optional[str]]:
        """Full text for many articles, fetched in parallel."""
        ids = list(dict.fromkeys(normalize_pmcid(p) for p in pmcids))
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            texts = list(pool.map(self.get_fulltext, ids))
        found = sum(t is not None for t in texts)
        logger.info(f"Full text available for {found}/{len(ids)} articles")
        return dict(zip(ids, texts))


def author_names(meta: Dict) -> List[str]:
    """'First Last' author names, as in the portal publications table."""
    names = []
    for author in meta.get("authors", []):
        first, last = author.get("firstName"), author.get("lastName")
        name = f"{first} {last}" if first and last else author.get("fullName")
        if name:
            names.append(name)
    return names


def _summarize(article: Dict) -> Dict:
    """Keep the Europe PMC fields the classifier needs."""
    authors = article.get("authorList", {}).get("author", [])
    return {
        "pmcid": article.get("pmcid"),
        "pmid": article.get("pmid"),
        "doi": article.get("doi"),
        "title": article.get("title"),
        "journal": (article.get("journalInfo") or {}).get("journal", {}).get("title")
                   or article.get("bookOrReportDetails", {}).get("publisher"),
        "year": article.get("pubYear"),
        "pub_date": article.get("firstPublicationDate"),
        "pub_types": article.get("pubTypeList", {}).get("pubType", []),
        "is_open_access": article.get("isOpenAccess") == "Y",
        # PubMed links a preprint to its published version ("Update in")
        "updated_in": [c.get("id") for c in
                       (article.get("commentCorrectionList") or {}).get("commentCorrection", [])
                       if c.get("type") == "Update in" and c.get("source") == "MED" and c.get("id")],
        "authors": [
            {
                "fullName": a.get("fullName"),
                "firstName": a.get("firstName"),
                "lastName": a.get("lastName"),
                "initials": a.get("initials"),
                "orcid": (a.get("authorId") or {}).get("value")
                         if (a.get("authorId") or {}).get("type") == "ORCID" else None,
            }
            for a in authors
        ],
    }
