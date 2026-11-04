"""Tests for adding reviewed paper-study pairs."""

import pandas as pd

from synapse_miner.portal_tables import build_rows, group_by_paper
from synapse_miner.reviewed import Decision, parse_decisions, reviewed_pairs


def test_parse_decisions_from_issue_reply():
    text = """Thanks, my calls:
PMID:40585258 (liquid biopsy, syn51115812): primary
PMID:40744913 (FGFR glioma, syn5698493): Secondary
- 41796852 syn31619419 review
no decision on this line syn123
"""
    assert parse_decisions(text) == [
        Decision("40585258", "syn51115812", "primary"),
        Decision("40744913", "syn5698493", "secondary"),
        Decision("41796852", "syn31619419", "review"),
    ]


def test_parse_decisions_ignores_unknown_relationship():
    assert parse_decisions("PMID:40585258 (syn51115812): unclear") == []


def _meta(pmid, pmcid, **kw):
    return {"pmid": pmid, "pmcid": pmcid, "doi": f"10.1/{pmid}", "title": f"Paper {pmid}.",
            "journal": "nature communications", "year": "2025", "pub_types": kw.get("pub_types", []),
            "authors": [{"fullName": "Doe J", "firstName": "Jane", "lastName": "Doe"}]}


def test_reviewed_pairs_become_portal_rows():
    decisions = [Decision("1", "syn10", "primary"), Decision("2", "syn20", "secondary")]
    metadata = {"1": _meta("1", "PMC1", pub_types=["Preprint"]), "2": _meta("2", None)}
    pairs = reviewed_pairs(decisions, metadata, {"PMC1": ["syn10", "syn11"]}, "Reviewed in https://x/1")
    assert list(pairs["confidence"]) == ["reviewed", "reviewed"]
    assert list(pairs["is_preprint"]) == [True, False]
    # No mined mentions for a paper without a PMCID: the study itself is the cited ID
    assert list(pairs["synids"]) == ["syn10, syn11", "syn20"]

    studies = {"syn10": {"disease_focus": ["Neurofibromatosis type 1"], "manifestation": ["MPNST"],
                         "funding_agency": ["NTAP"]},
               "syn20": {}}
    primary = group_by_paper(build_rows(pairs, studies, ["primary"]))
    assert primary.iloc[0]["pmid"] == "PMID:1"
    assert primary.iloc[0]["studyName"] == ["syn10"]
    assert primary.iloc[0]["journal"] == "Nature Communications"
    assert primary.iloc[0]["author"] == ["Jane Doe"]
    cited_by = group_by_paper(build_rows(pairs, studies, ["secondary"]))
    assert cited_by.iloc[0]["publicationType"] == "secondary"
    assert "Reviewed in https://x/1" in cited_by.iloc[0]["evidence"]


def test_reviewed_pairs_needs_metadata():
    import pytest
    with pytest.raises(ValueError, match="PMID 9"):
        reviewed_pairs([Decision("9", "syn1", "primary")], {}, {}, "x")
