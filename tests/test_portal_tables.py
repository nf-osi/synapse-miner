"""
Tests for adding classified papers to the portal publication tables.
"""

import json

import pandas as pd
import pytest

from synapse_miner import portal_tables
from synapse_miner.portal_tables import (
    CITED_BY_COLUMNS, PUBLICATION_COLUMNS, _for_upload, append_rows, build_cited_by,
    build_primary, drop_existing_pairs, pair_keys, review_issue,
)
from synapse_miner.utils import synapse_safety

STUDIES = {
    "syn4939902": {"study_name": "The Johns Hopkins NF1 biospecimen repository",
                   "funding_agency": ["NTAP"], "disease_focus": ["Neurofibromatosis type 1"],
                   "manifestation": ["MPNST", "Plexiform Neurofibroma"]},
    "syn11638893": {"study_name": "Development of a Preclinical NF1-MPNST Platform",
                    "funding_agency": ["NTAP", " NFRI"], "disease_focus": ["Neurofibromatosis type 1"],
                    "manifestation": ["MPNST"]},
}


def _row(study_id, relationship, confidence="high", **extra):
    row = {"pmcid": "PMC8026192", "pmid": 33591953.0, "doi": "10.1172/jci.insight.146351",
           "title": "Chromosome 8 gain is associated with high-grade transformation in MPNST.",
           "journal": "JCI insight", "year": 2021.0, "authors": "Carina Dehner; Angela C Hirbe",
           "is_preprint": False, "study_id": study_id, "study_name": STUDIES[study_id]["study_name"],
           "relationship": relationship, "confidence": confidence, "synids": "syn18634452",
           "evidence": "[reuse: imported from] ..."}
    row.update(extra)
    return row


# Dehner et al. 2021 deposited into Hirbe's project and reused JHU Biobank data
DEHNER = pd.DataFrame([_row("syn11638893", "primary"), _row("syn4939902", "secondary")])


def test_mixed_paper_splits_across_tables():
    primary = build_primary(DEHNER, STUDIES)
    cited_by = build_cited_by(DEHNER, STUDIES)
    assert list(cited_by.columns) == CITED_BY_COLUMNS
    assert [r for r in primary["studyId"]] == [["syn11638893"]]
    assert [r for r in cited_by["studyId"]] == [["syn4939902"]]
    row = cited_by.iloc[0]
    assert row["publicationType"] == "secondary"
    assert row["pmid"] == "PMID:33591953"
    assert row["year"] == 2021
    assert row["author"] == ["Carina Dehner", "Angela C Hirbe"]
    assert row["diseaseFocus"] == "Neurofibromatosis type 1"


def test_low_confidence_primary_and_unclear_are_left_out():
    classified = pd.DataFrame([_row("syn11638893", "primary", confidence="low"),
                               _row("syn4939902", "unclear", confidence="low"),
                               _row("syn11638893", "review")])
    assert build_primary(classified, STUDIES).empty
    cited_by = build_cited_by(classified, STUDIES)
    assert list(cited_by["publicationType"]) == ["review"]
    # Values are trimmed of stray whitespace from the studies view
    assert cited_by.iloc[0]["fundingAgency"] == ["NTAP", "NFRI"]


def test_existing_pairs_are_skipped_by_pmid_or_doi():
    rows = build_cited_by(DEHNER, STUDIES)
    # Already in the publications table under that study, keyed by PMID string from Synapse
    existing = pair_keys(pd.DataFrame({"pmid": ["PMID:33591953"], "doi": [None],
                                       "studyId": [json.dumps(["syn4939902", "syn56373031"])]}))
    assert drop_existing_pairs(rows, existing).empty
    # Same paper under a different study is a new pair
    other = pair_keys(pd.DataFrame({"pmid": [None], "doi": ["10.1172/JCI.INSIGHT.146351"],
                                    "studyId": [["syn11638893"]]}))
    assert len(drop_existing_pairs(rows, other)) == 1


def test_publication_rows_upload_only_publication_columns():
    upload = _for_upload(build_primary(DEHNER, STUDIES), PUBLICATION_COLUMNS)
    assert list(upload.columns) == PUBLICATION_COLUMNS
    assert json.loads(upload.iloc[0]["studyId"]) == ["syn11638893"]


class FakeSyn:
    def __init__(self, fail_snapshot=False):
        self.calls = []
        self.fail_snapshot = fail_snapshot

    def create_snapshot_version(self, table_id, comment=None):
        if self.fail_snapshot:
            raise RuntimeError("snapshot failed")
        self.calls.append(("snapshot", table_id, comment))
        return len(self.calls)

    def store(self, table):
        self.calls.append(("store", table))
        return table


def test_append_snapshots_before_and_after(monkeypatch):
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "nf-osi/synapse-miner")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setattr("synapseclient.Table", lambda table_id, df: ("table", table_id, len(df)))
    syn = FakeSyn()
    assert append_rows(syn, "syn78484103", build_cited_by(DEHNER, STUDIES), CITED_BY_COLUMNS, "test adds 1") == 1
    kinds = [c[0] for c in syn.calls]
    assert kinds == ["snapshot", "store", "snapshot"]
    before, after = syn.calls[0][2], syn.calls[2][2]
    assert " before: test adds 1 https://github.com/nf-osi/synapse-miner/actions/runs/123" in before
    assert " after: " in after
    assert len(before) <= 256


def test_no_write_without_before_snapshot(monkeypatch):
    monkeypatch.setattr("synapseclient.Table", lambda table_id, df: ("table", table_id, len(df)))
    syn = FakeSyn(fail_snapshot=True)
    with pytest.raises(RuntimeError):
        append_rows(syn, "syn78484103", build_cited_by(DEHNER, STUDIES), CITED_BY_COLUMNS, "x")
    assert syn.calls == []


def test_nothing_new_means_no_write_and_no_issue():
    syn = FakeSyn()
    empty = build_cited_by(DEHNER, STUDIES).iloc[0:0]
    assert append_rows(syn, "syn78484103", empty, CITED_BY_COLUMNS, "x") == 0
    assert syn.calls == []
    assert review_issue({"syn78484103": empty, "syn16857542": empty}) is None


def test_review_issue_lists_lower_confidence_first():
    classified = pd.DataFrame([_row("syn4939902", "secondary", confidence="high"),
                               _row("syn11638893", "mention", confidence="medium",
                                    title="A lower confidence mention")])
    title, body = review_issue({"syn78484103": build_cited_by(classified, STUDIES)})
    assert title.startswith("Review 2 new publication rows")
    assert body.index("| medium | mention") < body.index("| high | secondary")


def test_titles_lose_inline_markup():
    classified = pd.DataFrame([_row("syn4939902", "secondary",
                                    title="Loss of <i>NF1</i> in &lt;i&gt;NF2&lt;/i&gt; cells")])
    assert build_cited_by(classified, STUDIES).iloc[0]["title"] == "Loss of NF1 in NF2 cells"
