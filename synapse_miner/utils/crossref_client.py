"""
Journal names in the publisher's own casing, from Crossref.

Europe PMC gives NLM-style journal titles ("Science advances", "Clinical
cancer research : an official journal of the American Association for
Cancer Research"); the portal publications table uses the publisher's
casing ("Science Advances", "Clinical Cancer Research").
"""

import json
import logging
import os
import re
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

CROSSREF_WORKS = "https://api.crossref.org/works/"
_USER_AGENT = "synapse-miner (https://github.com/nf-osi/synapse-miner)"
# Words kept lowercase inside a title-cased journal name
_SMALL_WORDS = {"a", "an", "and", "as", "at", "for", "in", "of", "on", "or", "the", "to", "with", "de", "la"}


def clean_journal_title(title: Optional[str]) -> Optional[str]:
    """
    Tidy a Europe PMC journal title when Crossref has none: drop NLM
    subtitles (" : an official journal of ...") and places ("(Basel,
    Switzerland)"), and capitalise all-lowercase words other than short
    joining words. Words with their own casing (eLife, iScience, npj, PLoS)
    are kept as they are.
    """
    if not title:
        return title
    title = re.split(r"\s+:\s+", str(title))[0]
    title = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip().rstrip(".")
    words = title.split()
    out = []
    for i, word in enumerate(words):
        if word.islower() and word != "npj" and (i == 0 or word not in _SMALL_WORDS):
            word = word[0].upper() + word[1:]
        out.append(word)
    return " ".join(out)


class CrossrefClient:
    """Looks up journal names by DOI, caching answers (including misses) on disk."""

    def __init__(self, cache_path: Optional[str] = None, timeout: int = 30):
        self.cache_path = cache_path
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = _USER_AGENT
        self._cache: Dict[str, Optional[str]] = {}
        if cache_path and os.path.exists(cache_path):
            with open(cache_path) as f:
                self._cache = json.load(f)

    def journal_title(self, doi: Optional[str]) -> Optional[str]:
        """The journal's name as the publisher registers it, or None."""
        if not doi:
            return None
        key = str(doi).strip().lower().replace("https://doi.org/", "")
        if key not in self._cache:
            try:
                response = self.session.get(CROSSREF_WORKS + key, timeout=self.timeout)
                titles = response.json()["message"].get("container-title") if response.ok else None
                self._cache[key] = titles[0] if titles else None
            except (requests.RequestException, ValueError, KeyError) as e:
                logger.debug(f"Crossref lookup failed for {key}: {e}")
                return None
            self._save()
        return self._cache[key]

    def journal_name(self, doi: Optional[str], fallback: Optional[str]) -> Optional[str]:
        """Crossref's journal name for the DOI, else the cleaned Europe PMC title."""
        return self.journal_title(doi) or clean_journal_title(fallback)

    def _save(self) -> None:
        if self.cache_path:
            os.makedirs(os.path.dirname(os.path.abspath(self.cache_path)), exist_ok=True)
            with open(self.cache_path, "w") as f:
                json.dump(self._cache, f)
