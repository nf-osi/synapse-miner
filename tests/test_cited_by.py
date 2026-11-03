"""
Tests for building the Cited By table from classified publications.
"""

import json

import pandas as pd

from synapse_miner.cited_by import CITED_BY_COLUMNS, _for_upload, build_cited_by

STUDIES = {
    "syn4939902": {"study_name": "The Johns Hopkins NF1 biospecimen repository",
                   "funding_agency": ["NTAP"], "disease_focus": ["Neurofibromatosis type 1"],
                   "manifestation": ["MPNST", "Plexiform Neurofibroma"]},
    "syn11638893": {"study_name": "Development of a Preclinical NF1-MPNST Platform",
                    "funding_agency": ["NTAP", " NFRI"], "disease_focus": ["Neurofibromatosis type 1"],
                    "manifestation": ["MPNST"]},
}


def _row(study_id, relationship, **extra):
    row = {"pmcid": "PMC8026192", "pmid": 33591953.0, "doi": "10.1172/jci.insight.146351",
           "title": "Chromosome 8 gain is associated with high-grade transformation in MPNST.",
           "journal": "JCI insight", "year": 2021.0, "authors": "Carina Dehner; Angela C Hirbe",
           "is_preprint": False, "study_id": study_id, "study_name": STUDIES[study_id]["study_name"],
           "relationship": relationship, "confidence": "high", "synids": "syn18634452",
           "evidence": "[reuse: imported from] ..."}
    row.update(extra)
    return row


def test_mixed_paper_keeps_only_its_secondary_study():
    # Dehner et al. 2021 deposited into Hirbe's project and reused JHU Biobank data
    classified = pd.DataFrame([_row("syn11638893", "primary"), _row("syn4939902", "secondary")])
    cited_by = build_cited_by(classified, STUDIES)
    assert list(cited_by.columns) == CITED_BY_COLUMNS
    assert len(cited_by) == 1
    row = cited_by.iloc[0]
    assert row["studyId"] == ["syn4939902"]
    assert row["publicationType"] == "secondary"
    assert row["pmid"] == "PMID:33591953"
    assert row["year"] == 2021
    assert row["author"] == ["Carina Dehner", "Angela C Hirbe"]
    assert row["fundingAgency"] == ["NTAP"]
    assert row["diseaseFocus"] == "Neurofibromatosis type 1"


def test_unclear_and_primary_are_left_out():
    classified = pd.DataFrame([_row("syn4939902", "unclear"), _row("syn11638893", "primary"),
                               _row("syn11638893", "review")])
    cited_by = build_cited_by(classified, STUDIES)
    assert list(cited_by["publicationType"]) == ["review"]
    # Values are trimmed of stray whitespace from the studies view
    assert cited_by.iloc[0]["fundingAgency"] == ["NTAP", "NFRI"]


def test_list_columns_upload_as_json_arrays():
    cited_by = build_cited_by(pd.DataFrame([_row("syn4939902", "secondary")]), STUDIES)
    upload = _for_upload(cited_by)
    assert json.loads(upload.iloc[0]["studyId"]) == ["syn4939902"]
    assert json.loads(upload.iloc[0]["author"]) == ["Carina Dehner", "Angela C Hirbe"]
