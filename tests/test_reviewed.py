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


def test_parse_replaces():
    assert parse_decisions("PMID:36283200 (syn74287631): primary, replaces PMID:34711849") == [
        Decision("36283200", "syn74287631", "primary", "pmid:34711849")]
    assert parse_decisions("PMID:36283200 syn74287631 primary replace PMID 34711849")[0].replaces == "pmid:34711849"
    # A placeholder row with no PMID is named by its DOI
    assert parse_decisions("PMID:36283200 (syn74287631): primary, replaces DOI:10.7937/TCIA.9YTJ-5Q73.")[0] \
        .replaces == "doi:10.7937/tcia.9ytj-5q73"
    assert parse_decisions("PMID:1234567 syn2 primary replaces DOI: https://doi.org/10.1/X")[0].replaces == "doi:10.1/x"


def test_plan_replacements_overwrites_paper_columns_only():
    import pytest
    from synapse_miner.reviewed import PAPER_COLUMNS, plan_replacements
    decisions = [Decision("1", "syn10", "primary", "doi:10.7937/tcia.x")]
    pairs = reviewed_pairs(decisions, {"1": _meta("1", "PMC1")}, {}, "Reviewed in https://x/1")
    target = pd.DataFrame([{"ROW_ID": 431, "pmid": "PMID:", "doi": "10.7937/TCIA.X", "studyId": ["syn10"]},
                           {"ROW_ID": 5, "pmid": "PMID:9", "doi": None, "studyId": ["syn99"]}])
    funded = {"syn10": {"funding_agency": ["Wellcome Trust", "EPSRC"]}}
    changes = plan_replacements(pairs, funded, ["primary"], target, set(), PAPER_COLUMNS)
    assert set(changes) == {431}
    # Funders come from the study, not the row (which may hold the column default)
    assert changes[431]["fundingAgency"] == ["Wellcome Trust", "EPSRC"]
    assert changes[431]["pmid"] == "PMID:1"
    assert changes[431]["doi"] == "https://doi.org/10.1/1"
    assert changes[431]["year"] == 2025 and type(changes[431]["year"]) is int
    assert "studyId" not in changes[431]
    # A study with no funders leaves the row's funders alone
    assert "fundingAgency" not in plan_replacements(pairs, {"syn10": {}}, ["primary"], target, set(),
                                                    PAPER_COLUMNS)[431]
    # Replacing a row with the paper it already holds refreshes it
    holding = target.assign(pmid=["PMID:1", "PMID:9"])
    refresh = reviewed_pairs([Decision("1", "syn10", "primary", "pmid:1")], {"1": _meta("1", "PMC1")}, {}, "x")
    assert set(plan_replacements(refresh, funded, ["primary"], holding, {("pmid:1", "syn10")}, PAPER_COLUMNS)) == {431}
    # Only a row linked to the study and holding the named paper can be replaced
    for replaces in ("pmid:9", "pmid:404"):
        wrong = [Decision("1", "syn10", "primary", replaces)]
        with pytest.raises(ValueError, match="No row linked"):
            plan_replacements(reviewed_pairs(wrong, {"1": _meta("1", "PMC1")}, {}, "x"), {"syn10": {}},
                              ["primary"], target, set(), PAPER_COLUMNS)
    # Two rows holding it is ambiguous
    twice = pd.concat([target, target.iloc[[0]].assign(ROW_ID=432)])
    with pytest.raises(ValueError, match="Rows 431, 432"):
        plan_replacements(pairs, {"syn10": {}}, ["primary"], twice, set(), PAPER_COLUMNS)
    # Nor one whose paper is already linked to the study
    with pytest.raises(ValueError, match="already linked"):
        plan_replacements(pairs, {"syn10": {}}, ["primary"], target, {("pmid:1", "syn10")}, PAPER_COLUMNS)


def test_plan_funder_fixes():
    from synapse_miner.reviewed import plan_funder_fixes
    target = pd.DataFrame([
        {"ROW_ID": 1, "studyId": ["syn1"], "fundingAgency": ["NTAP", "CTF", "GFF"]},
        {"ROW_ID": 2, "studyId": [], "fundingAgency": ["NTAP", "CTF", "GFF"]},
        {"ROW_ID": 3, "studyId": ["syn2"], "fundingAgency": ["NIH-NCI"]},
        {"ROW_ID": 4, "studyId": ["syn1", "syn2"], "fundingAgency": ["NTAP"]},
    ])
    studies = {"syn1": {"funding_agency": ["Wellcome Trust"]}, "syn2": {"funding_agency": ["NIH-NCI"]}}
    assert plan_funder_fixes(target, studies, [1, 2, 3, 4, 99]) == {
        1: {"fundingAgency": ["Wellcome Trust"]},       # default replaced
        4: {"fundingAgency": ["Wellcome Trust", "NIH-NCI"]},  # union of the row's studies
    }  # 2 has no study, 3 already matches, 99 is not in the table
