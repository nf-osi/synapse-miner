"""Test for PMC ID bioregistry prefix functionality."""

import pytest
import sys
import os

# Add the project root to path
sys.path.insert(0, os.path.abspath('.'))

from synapse_miner.core import process_article

# Sample XML with PMC ID and Synapse IDs for testing
SAMPLE_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink" article-type="research-article">
    <front>
        <article-meta>
            <article-id pub-id-type="pmcid">PMC1234567</article-id>
            <title-group>
                <article-title>Test Article</article-title>
            </title-group>
            <abstract>
                <p>This article mentions a Synapse dataset syn1234567.</p>
            </abstract>
        </article-meta>
    </front>
</article>'''

def test_pmc_id_bioregistry_prefix():
    """Test that PMC IDs are output with the bioregistry 'pmc:' prefix."""
    pmc_id, findings = process_article(SAMPLE_XML, context_size=25)
    
    # Should extract PMC ID from XML
    assert pmc_id is not None
    
    # Should find at least one Synapse ID
    assert len(findings) >= 1
    
    # Each finding should have PMC ID with 'pmc:' prefix
    for finding in findings:
        assert 'pmcid' in finding
        assert finding['pmcid'].startswith('pmc:')
        assert 'PMC' in finding['pmcid']  # Should still contain the PMC part
        
    # First finding should have the correct format
    first_finding = findings[0]
    expected_pmcid = 'pmc:PMC1234567'
    assert first_finding['pmcid'] == expected_pmcid

def test_pmc_id_different_formats():
    """Test PMC ID extraction with different formats in XML."""
    # Test with numeric-only PMC ID
    xml_numeric = SAMPLE_XML.replace('PMC1234567', '1234567')
    pmc_id, findings = process_article(xml_numeric, context_size=25)
    
    if findings:  # Only test if we found something
        assert findings[0]['pmcid'] == 'pmc:PMC1234567'
    
    # Test with different pub-id-type
    xml_pmc_type = SAMPLE_XML.replace('pub-id-type="pmcid"', 'pub-id-type="pmc"')
    pmc_id, findings = process_article(xml_pmc_type, context_size=25)
    
    if findings:  # Only test if we found something
        assert findings[0]['pmcid'] == 'pmc:PMC1234567'

if __name__ == "__main__":
    # Run the tests
    test_pmc_id_bioregistry_prefix()
    test_pmc_id_different_formats()
    print("All tests passed!")