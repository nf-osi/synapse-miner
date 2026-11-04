"""
Tests for the tracking and workflow functionality.
"""

import pytest
import json
import tempfile
import os
from pathlib import Path
from synapse_miner.utils import ProcessingTracker

def test_processing_tracker_basic():
    """Test basic tracking functionality."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        tracking_file = f.name
    
    try:
        tracker = ProcessingTracker(tracking_file)
        
        # Initially should return None
        assert tracker.get_last_processed_pmc_id() is None
        
        # Update with a PMC ID
        test_pmc_id = "PMC11890001"
        assert tracker.update_last_processed_pmc_id(test_pmc_id) is True
        
        # Should now return the PMC ID
        assert tracker.get_last_processed_pmc_id() == test_pmc_id
        
        # Test with a new tracker instance (file persistence)
        tracker2 = ProcessingTracker(tracking_file)
        assert tracker2.get_last_processed_pmc_id() == test_pmc_id
        
    finally:
        # Clean up
        if os.path.exists(tracking_file):
            os.remove(tracking_file)

def test_extract_starting_pmc_id():
    """Test extracting PMC ID from filenames."""
    tracker = ProcessingTracker()
    
    # Test valid filenames
    assert tracker.extract_starting_pmc_id("PMC11890001_PMC11900000.xml.gz") == "PMC11890001"
    assert tracker.extract_starting_pmc_id("PMC123456_PMC123500.xml.gz") == "PMC123456"
    assert tracker.extract_starting_pmc_id("PMC1_PMC10.xml.gz") == "PMC1"
    
    # Test invalid filenames
    assert tracker.extract_starting_pmc_id("invalid_filename.xml.gz") is None
    assert tracker.extract_starting_pmc_id("PMC123456.xml.gz") is None
    assert tracker.extract_starting_pmc_id("") is None

def test_tracking_file_structure():
    """Test that tracking file has the correct structure."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        tracking_file = f.name
    
    try:
        tracker = ProcessingTracker(tracking_file)
        test_pmc_id = "PMC11890001"
        tracker.update_last_processed_pmc_id(test_pmc_id)
        
        # Check file contents
        with open(tracking_file, 'r') as f:
            data = json.load(f)
        
        assert 'last_processed_pmc_id' in data
        assert 'updated_at' in data
        assert data['last_processed_pmc_id'] == test_pmc_id
        assert data['updated_at'] is not None
        
    finally:
        if os.path.exists(tracking_file):
            os.remove(tracking_file)

def test_tracker_error_handling():
    """Test tracker error handling for invalid files."""
    # Test reading from non-existent file
    tracker = ProcessingTracker("/non/existent/path/file.json")
    assert tracker.get_last_processed_pmc_id() is None
    
    # Test writing to invalid path
    tracker = ProcessingTracker("/non/existent/path/file.json")
    assert tracker.update_last_processed_pmc_id("PMC123456") is False
def test_extract_ending_pmc_id():
    """Test extracting the ending PMC ID from filenames."""
    tracker = ProcessingTracker()
    
    assert tracker.extract_ending_pmc_id("PMC11890001_PMC11900000.xml.gz") == "PMC11900000"
    assert tracker.extract_ending_pmc_id("PMC13710763_PMC13710763.xml.gz") == "PMC13710763"
    assert tracker.extract_ending_pmc_id("invalid_filename.xml.gz") is None
    assert tracker.extract_ending_pmc_id("PMC123456.xml.gz") is None

def test_get_resume_pmc_id():
    """Test that resumption starts just past the last processed PMC ID."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        tracking_file = f.name
    
    try:
        tracker = ProcessingTracker(tracking_file)
        assert tracker.get_resume_pmc_id() is None
        
        tracker.update_last_processed_pmc_id("PMC11900000")
        assert tracker.get_resume_pmc_id() == "PMC11900001"
        
        tracker.update_last_processed_pmc_id("not-a-pmc-id")
        assert tracker.get_resume_pmc_id() is None
        
    finally:
        if os.path.exists(tracking_file):
            os.remove(tracking_file)


def test_failed_files_persist_and_merge(tmp_path):
    """Failed files are stored with the resume point and kept across updates."""
    tracker = ProcessingTracker(str(tmp_path / "t.json"))
    assert tracker.get_failed_files() == {}
    tracker.update_last_processed_pmc_id("PMC200", failed_files={"PMC1_PMC100.xml.gz": 1})
    assert tracker.get_failed_files() == {"PMC1_PMC100.xml.gz": 1}
    # None keeps both the resume point and the failed list
    tracker.update_last_processed_pmc_id(None)
    assert tracker.get_last_processed_pmc_id() == "PMC200"
    assert tracker.get_failed_files() == {"PMC1_PMC100.xml.gz": 1}
    # An empty dict clears the list
    tracker.update_last_processed_pmc_id("PMC300", failed_files={})
    assert tracker.get_failed_files() == {}
    assert "failed_files" not in json.loads((tmp_path / "t.json").read_text())


def test_retry_list_counts_and_gives_up():
    import logging
    from synapse_miner.cli import retry_list, MAX_FILE_ATTEMPTS
    log = logging.getLogger("test")
    before = {"A": 1, "B": MAX_FILE_ATTEMPTS - 1, "C": 2}
    # A failed again, B hits the limit, C succeeded (absent), D is new, E vanished
    assert retry_list(before, ["A", "B", "D"], ["E"], log) == {"A": 2, "D": 1}


def test_process_http_files_retries_and_keeps_resume_point(tmp_path, monkeypatch):
    """Retried files run first, failures are reported, and only new files move the resume point."""
    import urllib.request
    from synapse_miner.core import SynapseMiner

    names = ["PMC1_PMC100.xml.gz", "PMC101_PMC200.xml.gz", "PMC201_PMC300.xml.gz", "PMC301_PMC400.xml.gz"]
    listing = "".join(f'<a href="{n}">{n}</a>' for n in names)
    miner = SynapseMiner()
    monkeypatch.setattr(miner, "_make_request", lambda url: listing)
    monkeypatch.setattr(miner, "_process_xml_file", lambda *a, **k: [])
    monkeypatch.setattr("synapse_miner.core.time.sleep", lambda s: None)
    order = []

    def fake_retrieve(url, path, reporthook=None):
        order.append(url.rsplit("/", 1)[-1])
        if "PMC301_" in url:
            raise OSError("Connection refused")
        open(path, "wb").close()

    monkeypatch.setattr(urllib.request, "urlretrieve", fake_retrieve)
    last = miner.process_http_files("https://example.org/oa/", str(tmp_path / "out.csv"),
                                    start_from="PMC201",
                                    retry_files=["PMC1_PMC100.xml.gz", "PMC9_PMC9.xml.gz"])
    assert order[0] == "PMC1_PMC100.xml.gz"
    assert "PMC101_PMC200.xml.gz" not in order
    assert last == "PMC201_PMC300.xml.gz"
    assert miner.failed_files == ["PMC301_PMC400.xml.gz"]
    assert miner.missing_retry_files == ["PMC9_PMC9.xml.gz"]


def test_process_http_files_nothing_new_past_resume_point(tmp_path, monkeypatch):
    """With no file past the resume point, only retries run: never the archive from the start."""
    import urllib.request
    from synapse_miner.core import SynapseMiner

    names = ["PMC1_PMC100.xml.gz", "PMC101_PMC200.xml.gz"]
    miner = SynapseMiner()
    monkeypatch.setattr(miner, "_make_request",
                        lambda url: "".join(f'<a href="{n}">{n}</a>' for n in names))
    monkeypatch.setattr(miner, "_process_xml_file", lambda *a, **k: [])
    order = []
    monkeypatch.setattr(urllib.request, "urlretrieve",
                        lambda url, path, reporthook=None: (order.append(url.rsplit("/", 1)[-1]),
                                                            open(path, "wb").close()))
    out = str(tmp_path / "out.csv")
    assert miner.process_http_files("https://example.org/oa/", out, start_from="PMC201") is None
    assert order == []
    assert miner.process_http_files("https://example.org/oa/", out, start_from="PMC201",
                                    retry_files=["PMC101_PMC200.xml.gz"]) is None
    assert order == ["PMC101_PMC200.xml.gz"]


def test_pmc_number():
    from synapse_miner.cli import pmc_number
    assert pmc_number("PMC13710763") == 13710763
    assert pmc_number("junk") == 0
