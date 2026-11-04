"""
Tests for classifying how publications relate to Synapse studies.

Sentences come from papers NTAP labelled by hand (nf-osi/synapse-miner#18).
"""

import pytest

from synapse_miner.core import process_article
from synapse_miner.utils.reuse_classifier import (
    Mention, classify_mention, classify_pair, extract_mentions,
    has_paper_level_deposit, lead_authors_on_paper, split_sentences,
)


@pytest.mark.parametrize("sentence, synid, expected", [
    # Dehner et al. 2021 - reused JHU Biobank data
    ("John Hopkin's CNV data from PN was directly imported from Synapse "
     "(https://www.synapse.org/#!Synapse:syn18634452).", "syn18634452", "reuse"),
    # Zamora et al. 2023 - "available ... (accessed on)" is reuse, not deposit
    ("Quantitative High-Throughput Screening data are available for the MIPE4.0 library of small "
     "molecules from https://www.synapse.org/#!Synapse:syn5522627 (accessed on 1 May 2023).",
     "syn5522627", "reuse"),
    # Brown et al. 2022
    ("The experimental data were provided by the NFhackathon 2020 competition, which were downloaded "
     "from https://www.synapse.org (syn4940963 and syn22336443, accessed on 1 October 2020).",
     "syn22336443", "reuse"),
    # Mazuelas et al. 2024 - deposit
    ("RNA-Seq data have been deposited at the NF Data Portal in Synapse "
     "(https://doi.org/10.7303/syn11374353) and are available under a data access agreement.",
     "syn11374353", "deposit"),
    # Li et al. 2026 - plain availability wording
    ("The processed genomics data are available at syn29529772 (RNA-seq), syn29346753 (WES), "
     "and syn35832496 (WGS).", "syn29346753", "available"),
    # Xiao et al. 2025 - review table citation
    ("syn11638893 (Hirbe et al., 2022) [45]", "syn11638893", "cite"),
])
def test_classify_mention(sentence, synid, expected):
    kind, _ = classify_mention(sentence, synid)
    assert kind == expected


def test_nearest_cue_wins_within_a_sentence():
    sentence = ("Raw counts were downloaded from syn1111111 and the processed results "
                "have been deposited in syn2222222.")
    assert classify_mention(sentence, "syn1111111")[0] == "reuse"
    assert classify_mention(sentence, "syn2222222")[0] == "deposit"


def test_reference_list_is_citation():
    kind, cue = classify_mention("Banerjee, J. et al. Synapse, 10.7303/syn53132831.1 (2025).",
                                 "syn53132831", section="References")
    assert (kind, cue) == ("cite", "reference list")


def test_split_sentences_keeps_et_al_and_dois():
    text = "Data from Smith et al. were used. See doi.org/10.7303/syn1234567. Done here."
    assert split_sentences(text) == [
        "Data from Smith et al. were used.", "See doi.org/10.7303/syn1234567.", "Done here."]


ARTICLE = """<article><body>
<sec><title>Sequencing Data Collection</title>
<p>Raw fastq files were downloaded from Synapse and quantified with Salmon.</p>
<table-wrap><table><tr><td>A Nerve Sheath Tumor Bank from Patients with NF1 (<italic>syn</italic>4939902)</td></tr></table></table-wrap>
</sec>
<sec><title>Data availability</title>
<p>Our new RNA-seq data have been deposited in Synapse (syn7777777).</p>
</sec>
<back><ref-list><ref><mixed-citation>Lab A. Synapse, 10.7303/syn7777777 (2024).</mixed-citation></ref></ref-list></back>
</body></article>"""


def test_extract_mentions_uses_section_context_and_inline_markup():
    mentions = {(m.synid, m.kind) for m in extract_mentions(ARTICLE)}
    # Bare table entry takes the reuse wording of its section
    assert ("syn4939902", "reuse") in mentions
    assert ("syn7777777", "deposit") in mentions
    assert ("syn7777777", "cite") in mentions


def test_miner_reads_ids_split_by_inline_markup():
    article = ("<article><front><article-meta><article-id pub-id-type='pmc'>PMC1</article-id>"
               "</article-meta></front>" + ARTICLE.split("<article>", 1)[1])
    _, findings = process_article(article, 25)
    assert "syn4939902" in {f["synid"] for f in findings}


def test_paper_level_deposit_without_id():
    xml = ("<article><body><p>Raw and processed RNAseq data is deposited on Synapse at "
           "https://www.synapse.org/cNForganoids.</p></body></article>")
    assert has_paper_level_deposit(xml)


def test_lead_author_matching():
    authors = [
        {"lastName": "Wallace", "firstName": "Margaret R", "initials": "MR"},
        {"lastName": "Patritti Cram", "firstName": "Jennifer", "initials": "J"},
        {"lastName": "Sundby", "firstName": "R Taylor", "initials": "RT"},
        {"lastName": "Hirbe", "firstName": "Angela C", "initials": "AC"},
    ]
    leads = ["Peggy Wallace", "Jennifer Patritti Cram", "Taylor Sundby", "Angela Hirbe", "Marc Ferrer"]
    assert lead_authors_on_paper(leads, authors) == leads[:4]


def _mention(kind):
    return Mention("syn1234567", "", "", kind)


@pytest.mark.parametrize("kinds, pub_types, leads, expected", [
    # Dehner 2021 / Banerjee 2020: reuse wins even with a study lead as co-author
    (["reuse"], ["research-article"], ["Christine Pratilas"], "secondary"),
    (["deposit", "reuse"], ["research-article"], [], "primary"),
    (["cite"], ["review-article", "Review"], ["Angela Hirbe"], "review"),
    # Banerjee 2025 / Pollard 2020 data descriptors
    (["cite"], ["Dataset", "data-paper"], ["Christine Pratilas"], "primary"),
    (["available"], ["research-article"], ["Peggy Wallace"], "primary"),
    (["available"], ["research-article"], [], "unclear"),
    (["cite"], ["research-article"], ["Angela Hirbe"], "unclear"),
    (["cite"], ["research-article"], [], "mention"),
])
def test_classify_pair(kinds, pub_types, leads, expected):
    result = classify_pair([_mention(k) for k in kinds], pub_types, leads)
    assert result.relationship == expected


def test_classify_pair_without_fulltext_says_so():
    result = classify_pair([_mention("cite")], ["research-article"], ["Angela Hirbe"], has_fulltext=False)
    assert result.relationship == "unclear"
    assert "no full text" in result.reason
