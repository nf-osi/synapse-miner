"""
NCBI PubMed Central (E-utilities) client for full-text search and retrieval.

NCBI serves full text for NIH author manuscripts as well as open-access
articles, so it covers papers that the Europe PMC open-access download and
REST full-text endpoint do not.
"""

import logging
import os
import time
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, Iterator, List, Optional, Set

import requests

from .europepmc_client import normalize_pmcid

logger = logging.getLogger(__name__)

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_FETCH_BATCH_SIZE = 50
_TOOL = "synapse-miner"


class NCBIPMCClient:
    """Searches PMC full text and fetches JATS articles in batches."""

    def __init__(self, cache_dir: Optional[str] = None, api_key: Optional[str] = None,
                 email: Optional[str] = None, retries: int = 3, timeout: int = 120):
        """
        Args:
            cache_dir: Directory caching one JATS file per article (no caching when None)
            api_key: NCBI API key (allows 10 requests/s instead of 3); defaults to NCBI_API_KEY
            email: Contact email sent with requests, as NCBI asks; defaults to NCBI_EMAIL
            retries: Attempts per request before giving up
            timeout: Seconds per request
        """
        self.cache_dir = cache_dir
        self.api_key = api_key or os.getenv("NCBI_API_KEY")
        self.email = email or os.getenv("NCBI_EMAIL")
        self.retries = retries
        self.timeout = timeout
        self.delay = 0.11 if self.api_key else 0.34
        self.session = requests.Session()
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def _params(self, **params) -> Dict:
        params["tool"] = _TOOL
        if self.api_key:
            params["api_key"] = self.api_key
        if self.email:
            params["email"] = self.email
        return params

    def _request(self, method: str, endpoint: str, **params) -> requests.Response:
        delay = 2
        for attempt in range(self.retries):
            time.sleep(self.delay)
            try:
                if method == "POST":
                    response = self.session.post(f"{EUTILS}/{endpoint}", data=self._params(**params),
                                                 timeout=self.timeout)
                else:
                    response = self.session.get(f"{EUTILS}/{endpoint}", params=self._params(**params),
                                                timeout=self.timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {response.status_code}")
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                if attempt == self.retries - 1:
                    raise
                logger.debug(f"Retrying NCBI {endpoint} after error: {e}")
                time.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")

    def search(self, query: str, page_size: int = 5000) -> Set[str]:
        """PMCIDs ('PMC123') of all PMC articles matching a full-text query."""
        found: Set[str] = set()
        start = 0
        while True:
            result = self._request("GET", "esearch.fcgi", db="pmc", term=query, retmode="json",
                                   retmax=page_size, retstart=start).json()["esearchresult"]
            ids = result.get("idlist", [])
            found.update(f"PMC{i}" for i in ids)
            start += len(ids)
            if not ids or start >= int(result.get("count", 0)):
                break
        logger.info(f"NCBI PMC: {len(found)} articles match {query}")
        return found

    def _cache_path(self, pmcid: str) -> Optional[str]:
        return os.path.join(self.cache_dir, f"{pmcid}.xml") if self.cache_dir else None

    def iter_fulltexts(self, pmcids: Iterable[str]) -> Iterator[tuple]:
        """
        Yield (pmcid, JATS XML string) for each article NCBI returns.

        Articles whose publisher only allows front matter are still yielded;
        they simply have no body text. Cached articles are not re-fetched.
        """
        ids = list(dict.fromkeys(normalize_pmcid(p) for p in pmcids))
        to_fetch: List[str] = []
        for pmcid in ids:
            path = self._cache_path(pmcid)
            if path and os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    yield pmcid, f.read()
            else:
                to_fetch.append(pmcid)

        for i in range(0, len(to_fetch), _FETCH_BATCH_SIZE):
            chunk = to_fetch[i:i + _FETCH_BATCH_SIZE]
            try:
                response = self._request("POST", "efetch.fcgi", db="pmc", retmode="xml",
                                         id=",".join(p[3:] for p in chunk))
                root = ET.fromstring(response.content)
            except (requests.RequestException, ET.ParseError) as e:
                logger.error(f"NCBI efetch failed for {len(chunk)} articles starting {chunk[0]}: {e}")
                continue
            for article in root.findall("article"):
                pmcid = _article_pmcid(article)
                if not pmcid:
                    continue
                xml = ET.tostring(article, encoding="unicode")
                path = self._cache_path(pmcid)
                if path:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(xml)
                yield pmcid, xml
            logger.info(f"Fetched NCBI full text for {min(i + _FETCH_BATCH_SIZE, len(to_fetch))}/{len(to_fetch)} articles")

    def get_fulltext(self, pmcid: str) -> Optional[str]:
        """JATS XML for one article with a body, or None."""
        for _, xml in self.iter_fulltexts([pmcid]):
            return xml if "<body" in xml else None
        return None


def _article_pmcid(article: ET.Element) -> Optional[str]:
    for article_id in article.iter("article-id"):
        if article_id.get("pub-id-type") in ("pmc", "pmcid") and article_id.text:
            return normalize_pmcid(article_id.text.strip())
    return None
