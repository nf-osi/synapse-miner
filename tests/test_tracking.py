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