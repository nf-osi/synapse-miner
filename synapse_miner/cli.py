"""
Command-line interface for Synapse ID Mining.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from .core import SynapseMiner
from synapse_miner.utils import ProcessingTracker

# Import combine_results conditionally
try:
    from synapse_miner.utils import combine_results
    COMBINE_AVAILABLE = True
except ImportError:
    combine_results = None
    COMBINE_AVAILABLE = False

# Import SynapseUploader only if available
try:
    from synapse_miner.utils import SynapseUploader
    SYNAPSE_AVAILABLE = True
except ImportError:
    SynapseUploader = None
    SYNAPSE_AVAILABLE = False

def setup_logging(verbose: bool = False) -> None:
    """Set up logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

def main() -> None:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Mine Synapse IDs from scientific articles."
    )
    
    # Common arguments
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "-c", "--context-size",
        type=int,
        default=100,
        help="Number of characters to include around each Synapse ID (default: 100)"
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Process local file
    local_parser = subparsers.add_parser(
        "process",
        help="Process a local XML file"
    )
    local_parser.add_argument(
        "file",
        type=Path,
        help="Path to the XML file to process"
    )
    local_parser.add_argument(
        "-o", "--output",
        type=Path,
        default="results.csv",
        help="Path to save results (default: results.csv)"
    )
    
    # Process HTTP files
    http_parser = subparsers.add_parser(
        "http",
        help="Process XML files from HTTP server"
    )
    http_parser.add_argument(
        "-u", "--url",
        required=True,
        help="Base URL of the HTTP server"
    )
    http_parser.add_argument(
        "-o", "--output",
        required=True,
        help="Path to save results"
    )
    http_parser.add_argument(
        "-s", "--start-from",
        help="Filename to start processing from"
    )
    http_parser.add_argument(
        "-m", "--max-files",
        type=int,
        help="Maximum number of files to process"
    )
    
    # Combine command
    combine_parser = subparsers.add_parser(
        "combine",
        help="Combine multiple batch CSV files into one"
    )
    combine_parser.add_argument(
        "-o", "--output",
        required=True,
        help="Path to save combined results"
    )
    combine_parser.add_argument(
        "-d", "--directory",
        help="Directory containing batch files (default: current directory)"
    )
    combine_parser.add_argument(
        "-p", "--pattern",
        default="results.csv.*.csv",
        help="Glob pattern to match batch files (default: results.csv.*.csv)"
    )
    
    # Automated workflow command
    if SYNAPSE_AVAILABLE:
        workflow_parser = subparsers.add_parser(
            "workflow",
            help="Run automated weekly workflow with Synapse integration"
        )
        workflow_parser.add_argument(
            "-u", "--url",
            default="https://europepmc.org/ftp/oa/",
            help="Base URL of the Europe PMC server (default: https://europepmc.org/ftp/oa/)"
        )
        workflow_parser.add_argument(
            "-o", "--output",
            default="workflow_results.csv",
            help="Base name for output files (default: workflow_results.csv)"
        )
        workflow_parser.add_argument(
            "-t", "--tracking-file",
            default="last_processed_pmc.json",
            help="Path to tracking file (default: last_processed_pmc.json)"
        )
        workflow_parser.add_argument(
            "--folder-id",
            required=True,
            help="Synapse folder ID for uploading batch files (e.g., syn66046437)"
        )
        workflow_parser.add_argument(
            "--table-id", 
            required=True,
            help="Synapse table ID for uploading results (e.g., syn66047339)"
        )
        workflow_parser.add_argument(
            "-m", "--max-files",
            type=int,
            help="Maximum number of files to process (for testing)"
        )
        workflow_parser.add_argument(
            "--synapse-pat",
            help="Synapse Personal Access Token (can also use SERVICE_TOKEN or SYNAPSE_PAT env var)"
        )
    
    # EBI Search XML generation command
    if SYNAPSE_AVAILABLE:
        ebisearch_parser = subparsers.add_parser(
            "ebisearch",
            help="Generate EBI Search XML from Synapse table"
        )
        ebisearch_parser.add_argument(
            "--table-id",
            required=True,
            help="Synapse table ID to query for results (e.g., syn66047339)"
        )
        ebisearch_parser.add_argument(
            "--output-dir",
            default="ebisearch",
            help="Directory to write ebisearch.xml and entity_cache.json (default: ebisearch)"
        )
        ebisearch_parser.add_argument(
            "--cache-file",
            default=None,
            help="Path to entity metadata cache JSON (default: <output-dir>/entity_cache.json)"
        )
        ebisearch_parser.add_argument(
            "--refresh",
            action="store_true",
            help="Re-fetch all entity metadata from Synapse, ignoring and overwriting the cache"
        )
        ebisearch_parser.add_argument(
            "--db-name",
            default="Sage Bionetworks Synapse",
            help="Database name written to the EBI Search XML header"
        )
        ebisearch_parser.add_argument(
            "--db-description",
            default="Datasets available via Synapse, the Sage Bionetworks data sharing platform",
            help="Database description written to the EBI Search XML header"
        )
        ebisearch_parser.add_argument(
            "--synapse-pat",
            help="Synapse Personal Access Token (can also use SYNAPSE_PAT env var)"
        )

    # LabLinks XML generation command
    if SYNAPSE_AVAILABLE:
        labslinks_parser = subparsers.add_parser(
            "labslinks",
            help="Generate EuropePMC LabLinks XML from Synapse table"
        )
        labslinks_parser.add_argument(
            "--table-id",
            required=True,
            help="Synapse table ID to query for results (e.g., syn66047339)"
        )
        labslinks_parser.add_argument(
            "--provider-id",
            required=True,
            type=int,
            help="EuropePMC LabLinks provider ID"
        )
        labslinks_parser.add_argument(
            "--output-dir",
            default="labslinks",
            help="Directory to write links.xml and profile.xml (default: labslinks)"
        )
        labslinks_parser.add_argument(
            "--provider-name",
            default="Sage Bionetworks",
            help="Provider display name (default: Sage Bionetworks)"
        )
        labslinks_parser.add_argument(
            "--provider-description",
            default="Data available via Synapse, the Sage Bionetworks data sharing platform",
            help="Provider description shown alongside links"
        )
        labslinks_parser.add_argument(
            "--provider-email",
            default="act@sagebase.org",
            help="Provider contact email (default: act@sagebase.org)"
        )
        labslinks_parser.add_argument(
            "--synapse-pat",
            help="Synapse Personal Access Token (can also use SERVICE_TOKEN or SYNAPSE_PAT env var)"
        )

    args = parser.parse_args()

    # Set up logging
    setup_logging(args.verbose)
    logger = logging.getLogger("synapse_miner.cli")
    
    # Create miner instance
    miner = SynapseMiner(context_size=args.context_size)
    
    try:
        if args.command == "process":
            # Process local file
            if not args.file.exists():
                logger.error(f"File does not exist: {args.file}")
                sys.exit(1)
                
            logger.info(f"Processing file: {args.file}")
            findings = miner.process_file(str(args.file))
            
            if findings:
                # Save results
                import pandas as pd
                df = pd.DataFrame(findings)
                df.to_csv(args.output, index=False)
                logger.info(f"Saved {len(findings)} findings to {args.output}")
            else:
                logger.warning("No findings to save")
                
        elif args.command == "http":
            # Process HTTP files
            logger.info(f"Processing files from {args.url}")
            miner.process_http_files(
                base_url=args.url,
                output_path=str(args.output),
                start_from=args.start_from,
                max_files=args.max_files
            )
            
        elif args.command == "combine":
            # Combine results
            if not COMBINE_AVAILABLE:
                logger.error("Combine functionality requires pandas. Please install: pip install pandas")
                sys.exit(1)
            combine_results(args.output, args.directory, args.pattern)
            
        elif args.command == "workflow" and SYNAPSE_AVAILABLE:
            # Run automated workflow
            run_automated_workflow(args, logger)

        elif args.command == "ebisearch" and SYNAPSE_AVAILABLE:
            run_ebisearch_workflow(args, logger)

        elif args.command == "labslinks" and SYNAPSE_AVAILABLE:
            # Generate LabLinks XML from Synapse table
            run_labslinks_workflow(args, logger)

        else:
            parser.print_help()
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

def run_automated_workflow(args, logger):
    """Run the automated weekly workflow with Synapse integration."""
    import os
    import glob
    from pathlib import Path
    
    try:
        # Initialize tracker
        tracker = ProcessingTracker(args.tracking_file)
        
        # Get last processed PMC ID
        last_pmc_id = tracker.get_last_processed_pmc_id()
        if last_pmc_id:
            logger.info(f"Resuming from last processed PMC ID: {last_pmc_id}")
        else:
            logger.info("No previous processing state found, starting from beginning")
        
        # Initialize Synapse uploader
        try:
            # Prioritize SERVICE_TOKEN, then fall back to SYNAPSE_PAT for backward compatibility
            token = args.synapse_pat or os.getenv('SERVICE_TOKEN') or os.getenv('SYNAPSE_PAT')
            synapse_uploader = SynapseUploader(pat=token)
        except Exception as e:
            logger.error(f"Failed to initialize Synapse client: {e}")
            logger.error("Please check your SERVICE_TOKEN or SYNAPSE_PAT environment variable or --synapse-pat argument")
            sys.exit(1)
        
        # Create miner instance  
        miner = SynapseMiner(context_size=args.context_size)
        
        # Determine start file based on last processed PMC ID
        start_from = None
        if last_pmc_id:
            # Simply use the last processed PMC ID as start_from
            # The core.py will handle finding the next available batch
            start_from = last_pmc_id
            logger.info(f"Will start from PMC ID >= {last_pmc_id}")
            
        # Clean up any existing batch files from previous runs
        batch_pattern = f"{args.output}.*.csv"
        existing_batch_files = glob.glob(batch_pattern)
        for batch_file in existing_batch_files:
            try:
                os.remove(batch_file)
                logger.info(f"Removed old batch file: {batch_file}")
            except Exception as e:
                logger.warning(f"Could not remove old batch file {batch_file}: {e}")
        
        # Process files from HTTP server
        logger.info(f"Starting processing from URL: {args.url}")
        try:
            miner.process_http_files(
                base_url=args.url,
                output_path=args.output,
                start_from=start_from,
                max_files=args.max_files
            )
        except Exception as e:
            logger.error(f"Failed to process files from HTTP server: {e}")
            sys.exit(1)
        
        # Find generated batch files
        batch_files = glob.glob(batch_pattern)
        batch_files.sort()  # Process in order
        
        if not batch_files:
            logger.warning("No batch files were generated")
            return
            
        logger.info(f"Found {len(batch_files)} batch files to upload")
        
        # Upload batch files and results to Synapse
        try:
            success = synapse_uploader.batch_upload_workflow(
                batch_files=batch_files,
                folder_id=args.folder_id,
                table_id=args.table_id
            )
        except Exception as e:
            logger.error(f"Failed during Synapse upload workflow: {e}")
            sys.exit(1)
        
        if success:
            # Update tracking file with the last processed batch
            # Extract PMC ID from the last batch file processed
            last_batch_file = batch_files[-1]
            filename = Path(last_batch_file).name
            
            # Extract the XML filename from the batch filename
            # Format: results.csv.{xml_filename}.csv
            parts = filename.split('.')
            if len(parts) >= 3:
                xml_filename = '.'.join(parts[2:-1])  # Get middle parts
                last_processed_pmc = tracker.extract_starting_pmc_id(xml_filename)
                
                if last_processed_pmc:
                    tracker.update_last_processed_pmc_id(last_processed_pmc)
                    logger.info(f"Updated tracking file with last processed PMC ID: {last_processed_pmc}")
                else:
                    logger.warning(f"Could not extract PMC ID from filename: {xml_filename}")
            
            logger.info("Workflow completed successfully")
        else:
            logger.error("Workflow failed during Synapse upload")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Error in automated workflow: {e}")
        sys.exit(1)

def run_labslinks_workflow(args, logger):
    """Generate EuropePMC LabLinks XML from the Synapse results table."""
    import os
    from synapse_miner.utils.xml_generator import generate_profile_xml, generate_links_xml

    # Initialize Synapse uploader
    try:
        token = args.synapse_pat or os.getenv('SERVICE_TOKEN') or os.getenv('SYNAPSE_PAT')
        synapse_uploader = SynapseUploader(pat=token)
    except Exception as e:
        logger.error(f"Failed to initialize Synapse client: {e}")
        sys.exit(1)

    # Pull all (pmcid, synid) pairs from the table
    try:
        df = synapse_uploader.get_all_results(args.table_id)
    except Exception as e:
        logger.error(f"Failed to query Synapse table {args.table_id}: {e}")
        sys.exit(1)

    if df.empty:
        logger.warning("No data found in Synapse table — nothing to generate")
        return

    logger.info(f"Retrieved {len(df)} rows; generating LabLinks XML in '{args.output_dir}'")

    os.makedirs(args.output_dir, exist_ok=True)

    profile_path = os.path.join(args.output_dir, "profile.xml")
    generate_profile_xml(
        provider_id=args.provider_id,
        provider_name=args.provider_name,
        provider_description=args.provider_description,
        provider_email=args.provider_email,
        output_path=profile_path,
    )
    logger.info(f"Wrote {profile_path}")

    links_path = os.path.join(args.output_dir, "links.xml")
    generate_links_xml(
        df=df,
        provider_id=args.provider_id,
        output_path=links_path,
    )
    logger.info(f"Wrote {links_path}")
    logger.info("Done — upload both files to the EuropePMC LabsLink FTP site")


def run_ebisearch_workflow(args, logger):
    """Generate an EBI Search XML file from the Synapse results table."""
    import os
    from synapse_miner.utils.ebisearch_generator import generate_ebisearch_xml

    token = args.synapse_pat or os.getenv('SYNAPSE_PAT')
    try:
        synapse_uploader = SynapseUploader(pat=token)
    except Exception as e:
        logger.error(f"Failed to initialize Synapse client: {e}")
        import sys
        sys.exit(1)

    try:
        df = synapse_uploader.get_all_results(args.table_id)
    except Exception as e:
        logger.error(f"Failed to query Synapse table {args.table_id}: {e}")
        import sys
        sys.exit(1)

    if df.empty:
        logger.warning("No data found in Synapse table — nothing to generate")
        return

    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    cache_file = args.cache_file or os.path.join(output_dir, "entity_cache.json")
    output_path = os.path.join(output_dir, "ebisearch.xml")

    if args.refresh:
        logger.info("--refresh set: ignoring existing cache and re-fetching all metadata")

    generate_ebisearch_xml(
        syn=synapse_uploader.syn,
        df=df,
        output_path=output_path,
        cache_path=cache_file,
        refresh=args.refresh,
        db_name=args.db_name,
        db_description=args.db_description,
    )
    logger.info(f"Done — EBI Search XML written to {output_path}")


if __name__ == "__main__":
    main()