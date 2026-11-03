"""
Tests for searching and mining beyond the Europe PMC open-access download.
"""

import xml.etree.ElementTree as ET

import pandas as pd

from synapse_miner.core import process_article
from synapse_miner.search import find_candidates, mine_articles
from synapse_miner.utils.ncbi_pmc_client import _article_pmcid
from synapse_miner.utils.synapse_integration import SynapseUploader

# NCBI PMC full text puts tables in a floats group outside the body
NCBI_ARTICLE = """<article><front><article-meta>
<article-id pub-id-type="pmcid">PMC7073563</article-id>
<article-id pub-id-type="pmcaid">7073563</article-id>
</article-meta></front>
<body><p>Analysis results are in Synapse (syn21177277).</p></body>
<floats-group><table-wrap><table><tr>
<td>A Nerve Sheath Tumor Bank from Patients with NF1 (<italic toggle="yes">syn</italic>4939902)</td>
</tr></table></table-wrap></floats-group>
</article>"""


def test_article_pmcid_from_ncbi_ids():
    assert _article_pmcid(ET.fromstring(NCBI_ARTICLE)) == "PMC7073563"


def test_miner_reads_floats_group():
    pmcid, findings = process_article(NCBI_ARTICLE, 25)
    assert pmcid == "PMC7073563"
    assert {f["synid"] for f in findings} == {"syn21177277", "syn4939902"}


class FakeNCBI:
    def __init__(self, articles, hits=()):
        self.articles = articles
        self.hits = set(hits)

    def search(self, query):
        return self.hits

    def iter_fulltexts(self, pmcids):
        for pmcid in pmcids:
            if pmcid in self.articles:
                yield pmcid, self.articles[pmcid]


class FakeEPMC:
    def search(self, query):
        return [{"id": "PMC1", "source": "MED", "pmcid": "PMC1"},
                {"id": "PPR1", "source": "PPR", "pmcid": None}]


def test_find_candidates_merges_sources():
    pmcids, without = find_candidates(["q"], FakeNCBI({}, hits={"PMC7073563"}), FakeEPMC())
    assert pmcids == {"PMC7073563", "PMC1"}
    assert [r["id"] for r in without] == ["PPR1"]


def test_mine_articles():
    df = mine_articles(["PMC7073563"], FakeNCBI({"PMC7073563": NCBI_ARTICLE}))
    assert set(df["synid"]) == {"syn21177277", "syn4939902"}
    assert set(df["pmcid"]) == {"pmc:PMC7073563"}


class FakeSyn:
    def __init__(self):
        self.stored = None

    def store(self, table):
        self.stored = table


def test_upload_new_pairs_adds_ids_to_existing_articles(monkeypatch):
    uploader = SynapseUploader.__new__(SynapseUploader)
    uploader.syn = FakeSyn()
    existing = pd.DataFrame({"pmcid": ["pmc:PMC7073563"], "synid": ["syn21177277"]})
    monkeypatch.setattr(uploader, "get_all_results", lambda table_id: existing)
    captured = {}
    monkeypatch.setattr("synapse_miner.utils.synapse_integration.Table",
                        lambda table_id, df: captured.setdefault("df", df))

    mined = pd.DataFrame({
        "pmcid": ["pmc:PMC7073563", "pmc:PMC7073563"],
        "synid": ["syn21177277", "syn4939902"],
        "context": ["a", "b"],
    })
    assert uploader.upload_new_pairs_to_table(mined, "syn66047339") == 1
    assert list(captured["df"]["synid"]) == ["syn4939902"]
