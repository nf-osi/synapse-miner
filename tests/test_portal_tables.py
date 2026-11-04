"""
Tests for adding classified papers to the portal publication tables.
"""

import json

import pandas as pd
import pytest

from synapse_miner import portal_tables
from synapse_miner.classify import use_published_versions
from synapse_miner.portal_tables import (
    CITED_BY_COLUMNS, PUBLICATION_COLUMNS, _for_upload, append_rows, build_cited_by,
    build_primary, drop_existing_pairs, left_out_key, load_reported, not_added, pair_keys, review_issue,
    save_reported, update_preprint_rows,
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
    assert title.startswith("Review publication table changes")
    assert "2 rows added" in body
    assert body.index("| medium | mention") < body.index("| high | secondary")


def test_titles_lose_inline_markup():
    classified = pd.DataFrame([_row("syn4939902", "secondary",
                                    title="Loss of <i>NF1</i> in &lt;i&gt;NF2&lt;/i&gt; cells")])
    assert build_cited_by(classified, STUDIES).iloc[0]["title"] == "Loss of NF1 in NF2 cells"


# CDK4/6 inhibition paper: bioRxiv preprint PMID 36778419 -> Sci Adv PMID 38000020
PREPRINT_META = {"pmid": "36778419", "pmcid": "PMC9915673", "updated_in": ["38000020"],
                 "title": "CDK4/6 inhibition ... (preprint)", "authors": []}
PUBLISHED_META = {"pmid": "38000020", "pmcid": "PMC10672174", "doi": "10.1126/sciadv.adg8876",
                  "title": "CDK4/6 inhibition enhances SHP2 inhibitor efficacy", "journal": "Science advances",
                  "year": "2023", "updated_in": [],
                  "authors": [{"firstName": "Angela C", "lastName": "Hirbe"}]}


class FakeEPMC:
    def get_metadata_by_pmid(self, pmids):
        known = {"36778419": PREPRINT_META, "38000020": PUBLISHED_META}
        return {p: known[p] for p in pmids if p in known}


def _preprint_row(**extra):
    return _row("syn4939902", "primary", pmcid="PMC9915673", pmid="36778419", doi="10.1101/2023.02.02.526674",
                title="CDK4/6 inhibition ... (preprint)", journal="bioRxiv", year="2023",
                is_preprint=True, replaces_preprint=None, **extra)


def test_preprint_row_takes_published_version():
    out = use_published_versions(pd.DataFrame([_preprint_row()]),
                                 {"PMC9915673": PREPRINT_META}, FakeEPMC())
    row = out.iloc[0]
    assert (row["pmid"], row["doi"], row["journal"]) == ("38000020", "10.1126/sciadv.adg8876", "Science advances")
    assert row["replaces_preprint"] == "36778419"
    assert row["relationship"] == "primary" and not row["is_preprint"]


def test_preprint_row_dropped_when_published_version_is_classified():
    published = _row("syn4939902", "primary", pmcid="PMC10672174", pmid="38000020", is_preprint=False,
                     replaces_preprint=None)
    out = use_published_versions(pd.DataFrame([_preprint_row(), published]),
                                 {"PMC9915673": PREPRINT_META}, FakeEPMC())
    assert list(out["pmid"]) == ["38000020"]


class FakeQuery:
    def __init__(self, df):
        self.df = df

    def asDataFrame(self, rowIdAndVersionInIndex=True):
        return self.df


class FakeTableSyn(FakeSyn):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows

    def tableQuery(self, sql):
        self.calls.append(("query", sql))
        return FakeQuery(self.rows)


def test_existing_preprint_rows_are_updated_in_place(monkeypatch):
    captured = {}
    monkeypatch.setattr("synapseclient.PartialRowset.from_mapping",
                        lambda mapping, result: captured.setdefault("mapping", mapping))
    syn = FakeTableSyn(pd.DataFrame({"ROW_ID": [7], "pmid": ["PMID:36778419"], "title": ["preprint"],
                                     "studyId": [["syn21984813"]]}))
    updated, manual = update_preprint_rows(syn, "syn78484103", FakeEPMC(), cited_by=True)
    assert manual == []
    assert updated[0]["published_pmid"] == "38000020"
    values = captured["mapping"][7]
    assert values["pmid"] == "PMID:38000020" and values["isPreprint"] is False
    assert values["author"] == ["Angela C Hirbe"]
    # Snapshot, then a fresh query for current row etags, then store, then snapshot
    kinds = [c[0] for c in syn.calls]
    assert kinds == ["query", "snapshot", "query", "store", "snapshot"]


def test_preprint_row_duplicating_its_published_version_is_left_for_a_human(monkeypatch):
    syn = FakeTableSyn(pd.DataFrame({"ROW_ID": [7, 8], "pmid": ["PMID:36778419", "PMID:38000020"],
                                     "title": ["preprint", "published"],
                                     "studyId": [["syn21984813"], ["syn21984813"]]}))
    updated, manual = update_preprint_rows(syn, "syn16857542", FakeEPMC())
    assert updated == []
    assert [m["row_id"] for m in manual] == [7]
    assert not any(c[0] in ("store", "snapshot") for c in syn.calls)


def test_left_out_low_confidence_pairs_open_an_issue_on_their_own():
    classified = pd.DataFrame([_row("syn4939902", "unclear", confidence="low", reason="no full text"),
                               _row("syn11638893", "primary", confidence="low", reason="weak")])
    left_out = not_added(classified, set())
    assert len(left_out) == 2
    empty = build_cited_by(DEHNER, STUDIES).iloc[0:0]
    title, body = review_issue({"syn78484103": empty}, left_out=left_out, left_out_total=5)
    assert title.startswith("Review 2 low-confidence publication pairs")
    assert "Not added: 2 new low-confidence pairs" in body
    assert "3 more were reported in earlier issues" in body
    assert review_issue({"syn78484103": empty}, left_out=left_out.iloc[0:0]) is None
    # A pair already in a table is not reported as left out
    assert len(not_added(classified, pair_keys(pd.DataFrame(
        {"pmid": ["PMID:33591953"], "doi": [None], "studyId": [["syn4939902"]]})))) == 1


def test_issue_reports_replaced_and_duplicate_preprints():
    record = {"table": "syn16857542", "row_id": 7, "preprint_pmid": "36778419",
              "published_pmid": "38000020", "title": "CDK4/6", "studies": ["syn21984813"]}
    empty = build_cited_by(DEHNER, STUDIES).iloc[0:0]
    _, body = review_issue({"syn16857542": empty}, replaced=[record], to_remove=[record])
    assert "Preprints replaced by their published versions (1)" in body
    assert "Preprint rows to remove by hand (1)" in body


def test_reported_pairs_round_trip(tmp_path):
    classified = pd.DataFrame([_row("syn4939902", "unclear", confidence="low", reason="r")])
    keys = {left_out_key(r) for r in not_added(classified, set()).itertuples(index=False)}
    assert keys == {"33591953|syn4939902"}
    path = str(tmp_path / "reported.json")
    assert load_reported(path) == set()
    save_reported(path, keys)
    assert load_reported(path) == keys


def test_long_manifestations_use_short_forms_not_cut_off():
    studies = {"syn4939902": {**STUDIES["syn4939902"],
                              "manifestation": ["Malignant Peripheral Nerve Sheath Tumor",
                                                "Juvenile Myelomonocytic Leukemia",
                                                "Some Other Very Long Manifestation Name",
                                                "Plexiform Neurofibroma"]}}
    row = build_cited_by(pd.DataFrame([_row("syn4939902", "secondary")]), studies).iloc[0]
    assert row["manifestation"] == ["MPNST", "JMML", "Plexiform Neurofibroma"]


def test_doi_stored_as_link():
    from synapse_miner.portal_tables import doi_url
    assert doi_url("10.1126/sciadv.adg8876") == "https://doi.org/10.1126/sciadv.adg8876"
    assert doi_url("https://doi.org/10.1126/sciadv.adg8876") == "https://doi.org/10.1126/sciadv.adg8876"
    assert doi_url(None) is None
    assert build_cited_by(DEHNER, STUDIES).iloc[0]["doi"] == "https://doi.org/10.1172/jci.insight.146351"


@pytest.mark.parametrize("epmc, expected", [
    ("Science advances", "Science Advances"),
    ("Clinical cancer research : an official journal of the American Association for Cancer Research",
     "Clinical Cancer Research"),
    ("Gels (Basel, Switzerland)", "Gels"),
    ("Journal of neuro-oncology", "Journal of Neuro-oncology"),
    ("eLife", "eLife"),
    ("npj precision oncology", "npj Precision Oncology"),
])
def test_journal_title_fallback(epmc, expected):
    from synapse_miner.utils.crossref_client import clean_journal_title
    assert clean_journal_title(epmc) == expected
