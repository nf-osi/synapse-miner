"""
Find articles that mention Synapse beyond the Europe PMC open-access download.

Searches NCBI PMC and Europe PMC full text for Synapse links and DOIs, then
mines the NCBI full text of each match with the same parser as the weekly
workflow. NCBI serves NIH author manuscripts, which are not in the
open-access download, and re-reading articles already mined recovers IDs the
parser used to miss.
"""

import logging
from typing import Iterable, List, Optional, Set, Tuple

import pandas as pd

from .core import process_article
from .utils.europepmc_client import EuropePMCClient, normalize_pmcid
from .utils.ncbi_pmc_client import NCBIPMCClient

logger = logging.getLogger(__name__)

DEFAULT_QUERIES = [
    # Synapse links and DOIs
    '"synapse.org" OR "10.7303"',
    # Synapse IDs cited without a link, e.g. "Synapse ID syn123"
    '"Synapse ID" OR "SynID" OR "Synapse accession" OR "Synapse repository" OR "Synapse platform" OR "Synapse database"',
    # Portal names, e.g. "via the NF Data Portal (Synapse, #syn19522967)"
    '"NF Data Portal" OR "AD Knowledge Portal" OR "Sage Bionetworks"',
]


def find_candidates(queries: Iterable[str], ncbi: NCBIPMCClient,
                    epmc: EuropePMCClient) -> Tuple[Set[str], List[dict]]:
    """
    Articles matching any query in NCBI PMC or Europe PMC.

    Returns:
        (PMCIDs, Europe PMC results without a PMCID such as preprints and
        abstract-only records, which have no full text to mine)
    """
    pmcids: Set[str] = set()
    without_pmcid: List[dict] = []
    for query in queries:
        pmcids |= ncbi.search(query)
        for result in epmc.search(query):
            if result.get("pmcid"):
                pmcids.add(normalize_pmcid(result["pmcid"]))
            else:
                without_pmcid.append(result)
    logger.info(f"{len(pmcids)} candidate articles with a PMCID, "
                f"{len(without_pmcid)} without (not mined)")
    return pmcids, without_pmcid


def mine_articles(pmcids: Iterable[str], ncbi: NCBIPMCClient, context_size: int = 25) -> pd.DataFrame:
    """Synapse ID mentions (pmcid, synid, context) in the NCBI full text of each article."""
    rows = []
    articles = 0
    for pmcid, xml in ncbi.iter_fulltexts(pmcids):
        articles += 1
        _, findings = process_article(xml, context_size)
        rows.extend(findings)
    df = pd.DataFrame(rows, columns=["pmcid", "synid", "context"]).drop_duplicates()
    logger.info(f"Mined {articles} articles: {len(df)} mentions in {df['pmcid'].nunique()} articles")
    return df


def search_and_mine(queries: Iterable[str], existing_pmcids: Set[str], ncbi: NCBIPMCClient,
                    epmc: EuropePMCClient, recheck_existing: bool = False,
                    max_articles: Optional[int] = None) -> Tuple[pd.DataFrame, List[dict]]:
    """
    Search, then mine candidates not already in the results table.

    Args:
        queries: Full-text queries for NCBI PMC and Europe PMC
        existing_pmcids: PMCIDs already in the results table ('PMC123')
        recheck_existing: Also re-mine articles already in the table
        max_articles: Limit the number of articles mined (for testing)

    Returns:
        (mined mentions, Europe PMC results without a PMCID)
    """
    candidates, without_pmcid = find_candidates(queries, ncbi, epmc)
    to_mine = sorted(candidates if recheck_existing else candidates - existing_pmcids)
    logger.info(f"Mining {len(to_mine)} articles"
                + ("" if recheck_existing else f" ({len(candidates & existing_pmcids)} already in table skipped)"))
    if max_articles:
        to_mine = to_mine[:max_articles]
    return mine_articles(to_mine, ncbi), without_pmcid
