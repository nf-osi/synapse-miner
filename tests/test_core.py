"""
Tests for the core functionality of the Synapse ID Mining package.
"""

import pytest
import os
from synapse_miner.core import SynapseMiner

# Sample text for testing
SAMPLE_TEXT = """
This is a test article that mentions a Synapse ID syn1234567 in the text.
There is also another Synapse ID syn9876543 mentioned here.
And one more syn1111111 for good measure.

Some IDs that should not match:
syn123 (too short)
syn12345678901234 (too long)
xyn1234567 (wrong prefix)
"""

def test_extract_synapse_ids_with_context():
    """Test extracting Synapse IDs with context."""
    miner = SynapseMiner(context_size=20)
    findings = miner.extract_synapse_ids_with_context(SAMPLE_TEXT, "test_document")
    
    # Should find 3 Synapse IDs
    assert len(findings) == 3
    
    # Check that IDs are correctly extracted
    synapse_ids = [finding["synapse_id"] for finding in findings]
    assert "syn1234567" in synapse_ids
    assert "syn9876543" in synapse_ids
    assert "syn1111111" in synapse_ids
    
    # Check that IDs that don't match are not extracted
    assert "syn123" not in synapse_ids
    assert "syn12345678901234" not in synapse_ids
    assert "xyn1234567" not in synapse_ids
    
    # Check that context is correctly extracted
    for finding in findings:
        assert finding["synapse_id"] in finding["full_context"]
        assert len(finding["context_before"]) <= 20
        assert len(finding["context_after"]) <= 20

def test_deduplication():
    """Test deduplication of Synapse IDs."""
    # Text with duplicate IDs
    text_with_duplicates = """
    This is a test with duplicate IDs.
    Here is syn1234567 mentioned once.
    Here is syn1234567 mentioned again.
    Here is syn9876543 mentioned once.
    """
    
    # With deduplication enabled (default)
    miner_with_dedup = SynapseMiner(deduplication=True)
    findings_with_dedup = miner_with_dedup.extract_synapse_ids_with_context(
        text_with_duplicates, "test_document")
    
    # Should find 2 unique IDs
    assert len(findings_with_dedup) == 2
    
    # With deduplication disabled
    miner_without_dedup = SynapseMiner(deduplication=False)
    findings_without_dedup = miner_without_dedup.extract_synapse_ids_with_context(
        text_with_duplicates, "test_document")
    
    # Should find 3 IDs total (including duplicates)
    assert len(findings_without_dedup) == 3

def test_context_size():
    """Test different context sizes."""
    # Test with a smaller context size
    miner_small_context = SynapseMiner(context_size=10)
    findings_small = miner_small_context.extract_synapse_ids_with_context(
        SAMPLE_TEXT, "test_document")
    
    # Test with a larger context size
    miner_large_context = SynapseMiner(context_size=50)
    findings_large = miner_large_context.extract_synapse_ids_with_context(
        SAMPLE_TEXT, "test_document")
    
    # Both should find the same IDs
    assert len(findings_small) == len(findings_large)
    
    # But the context should be different in size
    for small, large in zip(findings_small, findings_large):
        assert len(small["full_context"]) <= len(large["full_context"])

def test_generate_summary():
    """Test generating summary statistics."""
    miner = SynapseMiner()
    
    # Add some test results
    miner.results = {
        "doc1.pdf": [
            {"synapse_id": "syn1234567", "document": "doc1.pdf"},
            {"synapse_id": "syn9876543", "document": "doc1.pdf"}
        ],
        "doc2.pdf": [
            {"synapse_id": "syn1234567", "document": "doc2.pdf"},
            {"synapse_id": "syn1111111", "document": "doc2.pdf"}
        ]
    }
    
    summary = miner.generate_summary()
    
    # Check summary statistics
    assert summary["total_documents_processed"] == 2
    assert summary["total_synapse_id_mentions"] == 4
    assert summary["unique_synapse_ids"] == 3
    
    # Check top mentioned IDs
    assert summary["top_mentioned_ids"]["syn1234567"] == 2  # In both docs
def test_process_http_files_resume_and_last_file(tmp_path, monkeypatch):
    """Resuming skips the last processed file, and the last processed file is
    returned even when it contains no Synapse IDs."""
    import gzip
    import shutil
    
    files = ["PMC1_PMC100.xml.gz", "PMC101_PMC200.xml.gz", "PMC250_PMC300.xml.gz"]
    listing = "".join(f'<a href="{name}">{name}</a>' for name in files)
    article = "<article><body><p>No Synapse IDs in this article.</p></body></article>"
    source = tmp_path / "source.xml.gz"
    with gzip.open(source, "wt") as f:
        f.write(f"<articles>{article}</articles>")
    
    downloaded = []
    def fake_urlretrieve(url, local_path, reporthook=None):
        downloaded.append(os.path.basename(url))
        shutil.copy(source, local_path)
    
    miner = SynapseMiner()
    monkeypatch.setattr(miner, "_make_request", lambda url: listing)
    monkeypatch.setattr("urllib.request.urlretrieve", fake_urlretrieve)
    
    # Tracking file recorded PMC100 (end of the first file), so resume at PMC101
    last_file = miner.process_http_files("http://example.org/", str(tmp_path / "out.csv"),
                                         start_from="PMC101")
    
    assert downloaded == ["PMC101_PMC200.xml.gz", "PMC250_PMC300.xml.gz"]
    assert last_file == "PMC250_PMC300.xml.gz"
