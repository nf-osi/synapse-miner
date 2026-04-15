"""
Utility functions for generating Europe PMC External Links Service XML files.
"""

import pandas as pd
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
import logging
import os
from lxml import etree
import xml.dom.minidom

logger = logging.getLogger("synapse_miner.xml_generator")

def validate_xml(xml_path: str, xsd_path: str) -> bool:
    """
    Validate an XML file against an XSD schema.
    
    Args:
        xml_path: Path to the XML file
        xsd_path: Path to the XSD schema file
        
    Returns:
        bool: True if validation succeeds, False otherwise
    """
    try:
        logger.info(f"Starting XML validation of {xml_path} against schema {xsd_path}")
        
        # Parse the XSD schema
        logger.debug("Parsing XSD schema...")
        schema_doc = etree.parse(xsd_path)
        schema = etree.XMLSchema(schema_doc)
        logger.debug("XSD schema parsed successfully")
        
        # Parse the XML file
        logger.debug("Parsing XML file...")
        xml_doc = etree.parse(xml_path)
        logger.debug("XML file parsed successfully")
        
        # Validate
        logger.debug("Starting validation...")
        schema.assertValid(xml_doc)
        logger.info(f"XML validation successful for {xml_path}")
        return True
        
    except etree.DocumentInvalid as e:
        logger.error(f"XML validation failed for {xml_path}:")
        logger.error(f"Error details: {e}")
        # Print specific validation errors
        for error in e.error_log:
            logger.error(f"Line {error.line}, Column {error.column}: {error.message}")
        return False
    except etree.XMLSyntaxError as e:
        logger.error(f"XML syntax error in {xml_path}:")
        logger.error(f"Error details: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during XML validation of {xml_path}:")
        logger.error(f"Error details: {e}")
        return False

def pretty_print_xml(xml_path: str) -> None:
    """
    Pretty print an XML file.
    
    Args:
        xml_path: Path to the XML file
    """
    try:
        # Parse the XML file
        dom = xml.dom.minidom.parse(xml_path)
        
        # Pretty print
        pretty_xml = dom.toprettyxml(indent="  ")
        
        # Write back to file
        with open(xml_path, 'w') as f:
            f.write(pretty_xml)
            
    except Exception as e:
        logger.error(f"Error pretty printing XML: {e}")
        raise

def test_xml_validation(xsd_path: str) -> None:
    """
    Test XML validation by generating and validating invalid XML.
    
    Args:
        xsd_path: Path to the XSD schema file
    """
    try:
        # Create a temporary directory for test files
        import tempfile
        test_dir = tempfile.mkdtemp()
        logger.info(f"Created test directory: {test_dir}")
        
        # Generate invalid profile XML (missing required elements)
        invalid_profile = os.path.join(test_dir, "invalid_profile.xml")
        with open(invalid_profile, 'w') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<providers>\n')
            f.write('  <provider>\n')
            f.write('    <id>12345</id>\n')
            f.write('    <!-- Missing required elements -->\n')
            f.write('  </provider>\n')
            f.write('</providers>\n')
        
        # Generate invalid links XML (invalid structure)
        invalid_links = os.path.join(test_dir, "invalid_links.xml")
        with open(invalid_links, 'w') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<links>\n')
            f.write('  <link>\n')
            f.write('    <invalid_element>test</invalid_element>\n')
            f.write('  </link>\n')
            f.write('</links>\n')
        
        # Try to validate the invalid files
        logger.info("Testing validation with invalid profile XML...")
        if validate_xml(invalid_profile, xsd_path):
            logger.error("Validation incorrectly passed for invalid profile XML!")
        else:
            logger.info("Validation correctly failed for invalid profile XML")
        
        logger.info("Testing validation with invalid links XML...")
        if validate_xml(invalid_links, xsd_path):
            logger.error("Validation incorrectly passed for invalid links XML!")
        else:
            logger.info("Validation correctly failed for invalid links XML")
        
        # Clean up
        import shutil
        shutil.rmtree(test_dir)
        logger.info("Test completed and temporary files cleaned up")
        
    except Exception as e:
        logger.error(f"Error during validation test: {e}")
        raise

def generate_europepmc_xml(
    results_file: str,
    europepmc_id: int,
    nlm_id: int,
    provider_name: str,
    provider_description: str,
    provider_email: str,
    output_dir: str,
    xsd_path: Optional[str] = None
) -> None:
    """
    Generate Europe PMC and NLM LinkOut files from mining results.
    
    Args:
        results_file: Path to the combined results CSV file
        europepmc_id: Europe PMC provider ID
        nlm_id: NLM LinkOut provider ID
        provider_name: Name of the provider/resource
        provider_description: Description of the resource
        provider_email: Contact email address
        output_dir: Directory to save the generated files
        xsd_path: Optional path to XSD schema for validation
    """
    try:
        # Create output directories
        europepmc_dir = os.path.join(output_dir, "europepmc")
        nlm_dir = os.path.join(output_dir, "nlm")
        os.makedirs(europepmc_dir, exist_ok=True)
        os.makedirs(nlm_dir, exist_ok=True)
        
        # Read the results file
        logger.info(f"Reading results from {results_file}")
        df = pd.read_csv(results_file)
        logger.info(f"Found {len(df)} results to process")
        
        # Generate Europe PMC files
        logger.info("Generating Europe PMC files...")
        profile_path = os.path.join(europepmc_dir, "profile.xml")
        links_path = os.path.join(europepmc_dir, "links.xml")
        
        generate_profile_xml(
            provider_id=europepmc_id,
            provider_name=provider_name,
            provider_description=provider_description,
            provider_email=provider_email,
            output_path=profile_path
        )
        
        generate_links_xml(
            df=df,
            provider_id=europepmc_id,
            output_path=links_path
        )
        
        # Generate NLM LinkOut files
        logger.info("Generating NLM LinkOut files...")
        provider_path = os.path.join(nlm_dir, "providerinfo.xml")
        resources_path = os.path.join(nlm_dir, "resources.csv")
        
        generate_nlm_provider_xml(
            provider_id=nlm_id,
            provider_name=provider_name,
            provider_name_abbr=provider_name[:10],  # Use first 10 chars as abbreviation
            subject_type="gene/protein/disease-specific",
            attribute="registration required",
            url="https://www.synapse.org",
            brief=provider_description,
            output_path=provider_path
        )
        
        generate_nlm_resources_csv(
            df=df,
            provider_id=nlm_id,
            output_path=resources_path
        )
        
        # Pretty print XML files
        logger.info("Pretty printing XML files...")
        pretty_print_xml(profile_path)
        pretty_print_xml(links_path)
        pretty_print_xml(provider_path)
        
        # Validate Europe PMC files if schema is provided
        if xsd_path:
            print("\n" + "="*80)
            print("VALIDATING EUROPE PMC XML FILES")
            print("="*80)
            
            print(f"\nValidating profile.xml against schema {xsd_path}")
            if not validate_xml(profile_path, xsd_path):
                raise ValueError("Profile XML validation failed")
            else:
                print("✓ Profile XML validation successful")
            
            print(f"\nValidating links.xml against schema {xsd_path}")
            if not validate_xml(links_path, xsd_path):
                raise ValueError("Links XML validation failed")
            else:
                print("✓ Links XML validation successful")
            
            print("="*80)
            print("ALL VALIDATIONS COMPLETED SUCCESSFULLY")
            print("="*80 + "\n")
        else:
            logger.warning("No XSD schema provided - skipping validation")
        
        logger.info(f"Successfully generated files in {output_dir}")
        logger.info(f"Europe PMC files in: {europepmc_dir}")
        logger.info(f"NLM LinkOut files in: {nlm_dir}")
        
    except Exception as e:
        logger.error(f"Error generating files: {e}")
        raise

def generate_profile_xml(
    provider_id: int,
    provider_name: str,
    provider_description: str,
    provider_email: str,
    output_path: str
) -> None:
    """
    Generate the providers XML file.
    
    Args:
        provider_id: Europe PMC provider ID
        provider_name: Name of the provider/resource
        provider_description: Description of the resource
        provider_email: Contact email address
        output_path: Path to save the XML file
    """
    # Create root element
    providers = ET.Element("providers")
    
    # Create provider element
    provider = ET.SubElement(providers, "provider")
    
    # Add required elements
    id_elem = ET.SubElement(provider, "id")
    id_elem.text = str(provider_id)
    
    name_elem = ET.SubElement(provider, "resourceName")
    name_elem.text = provider_name
    
    desc_elem = ET.SubElement(provider, "description")
    desc_elem.text = provider_description
    
    email_elem = ET.SubElement(provider, "email")
    email_elem.text = provider_email
    
    # Create XML tree and write to file
    tree = ET.ElementTree(providers)
    tree.write(
        output_path,
        encoding="UTF-8",
        xml_declaration=True,
        method="xml"
    )
    
    logger.info(f"Generated profile XML at {output_path}")

def generate_links_xml(
    df: pd.DataFrame,
    provider_id: int,
    output_path: str
) -> None:
    """
    Generate the links XML file.
    
    Args:
        df: DataFrame containing pmcid and synid columns
        provider_id: Europe PMC provider ID
        output_path: Path to save the XML file
    """
    # Create root element
    links = ET.Element("links")
    
    # Deduplicate on (pmcid, synid) pairs
    seen = set()
    for _, row in df.iterrows():
        pmcid = row.get('pmcid')
        synid = row.get('synid')

        if not pmcid or not synid:
            logger.warning(f"Skipping row with missing data: {row}")
            continue

        # Strip bioregistry prefix (stored as 'pmc:PMC1234567', XML needs 'PMC1234567')
        if isinstance(pmcid, str) and pmcid.startswith('pmc:'):
            pmcid = pmcid[4:]

        pair = (pmcid, synid)
        if pair in seen:
            continue
        seen.add(pair)

        # Create link element
        link = ET.SubElement(links, "link")
        link.set("providerId", str(provider_id))

        # Create resource element
        resource = ET.SubElement(link, "resource")

        # Add URL
        url = ET.SubElement(resource, "url")
        url.text = f"https://www.synapse.org/Synapse/{synid}"

        # Add title
        title = ET.SubElement(resource, "title")
        title.text = "View data on Synapse"

        # Create record element
        record = ET.SubElement(link, "record")

        # Add source and id
        source = ET.SubElement(record, "source")
        source.text = "PMC"

        id_elem = ET.SubElement(record, "id")
        id_elem.text = pmcid
    
    # Create XML tree and write to file
    tree = ET.ElementTree(links)
    tree.write(
        output_path,
        encoding="UTF-8",
        xml_declaration=True,
        method="xml"
    )
    
    logger.info(f"Generated links XML at {output_path}")

def generate_nlm_provider_xml(
    provider_id: int,
    provider_name: str,
    provider_name_abbr: str,
    subject_type: str,
    attribute: str,
    url: str,
    brief: str,
    output_path: str
) -> None:
    """
    Generate NLM LinkOut provider XML file.
    
    Args:
        provider_id: NCBI-assigned provider ID
        provider_name: Full name of the provider
        provider_name_abbr: Abbreviated name
        subject_type: Subject type (e.g., "gene/protein/disease-specific")
        attribute: Access requirements (e.g., "registration required")
        url: Provider's website URL
        brief: Brief description
        output_path: Path to save the XML file
    """
    try:
        # Create the XML structure
        root = ET.Element("Provider")
        
        # Add required elements
        ET.SubElement(root, "ProviderId").text = str(provider_id)
        ET.SubElement(root, "Name").text = provider_name
        ET.SubElement(root, "NameAbbr").text = provider_name_abbr
        ET.SubElement(root, "SubjectType").text = subject_type
        ET.SubElement(root, "Attribute").text = attribute
        ET.SubElement(root, "Url").text = url
        ET.SubElement(root, "Brief").text = brief
        
        # Create the XML tree
        tree = ET.ElementTree(root)
        
        # Add XML declaration and DOCTYPE
        xml_declaration = '<?xml version="1.0"?>\n'
        doctype = '<!DOCTYPE Provider PUBLIC "-//NLM//DTD LinkOut 1.0//EN" "https://www.ncbi.nlm.nih.gov/projects/linkout/doc/LinkOut.dtd">\n'
        
        # Write to file with proper formatting
        with open(output_path, 'wb') as f:
            f.write(xml_declaration.encode('utf-8'))
            f.write(doctype.encode('utf-8'))
            tree.write(f, encoding='utf-8', xml_declaration=False)
            
        # Pretty print the XML
        pretty_print_xml(output_path)
        
    except Exception as e:
        logger.error(f"Error generating NLM provider XML: {e}")
        raise

def generate_nlm_resources_csv(
    df: pd.DataFrame,
    provider_id: int,
    output_path: str
) -> None:
    """
    Generate NLM LinkOut resources CSV file.
    
    Args:
        df: DataFrame containing mining results
        provider_id: NCBI-assigned provider ID
        output_path: Path to save the CSV file
    """
    try:
        # Log the available columns for debugging
        logger.info(f"Available columns in DataFrame: {df.columns.tolist()}")
        
        # Create resources DataFrame with required fields
        resources = pd.DataFrame({
            'PrId': [provider_id] * len(df),
            'DB': ['pubmed'] * len(df),  # We're linking to PubMed articles
            'UID': df['pmcid'],  # PMC ID
            'URL': [f"https://www.synapse.org/#!Synapse:{synid}" for synid in df['synid']],  # Link to Synapse
            'SubjectType': [''] * len(df),  # Will be inherited from provider info
            'Attribute': ['registration required'] * len(df)  # Synapse requires registration
        })
        
        # Remove any rows with missing PMC IDs
        resources = resources.dropna(subset=['UID'])
        
        # Save to CSV
        resources.to_csv(output_path, index=False)
        logger.info(f"Generated NLM resources CSV at {output_path}")
        logger.info(f"Created {len(resources)} resource entries")
        
    except Exception as e:
        logger.error(f"Error generating NLM resources CSV: {e}")
        raise 