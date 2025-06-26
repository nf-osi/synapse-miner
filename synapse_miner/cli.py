"""
Command-line interface for Synapse ID Mining.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from .core import SynapseMiner
from synapse_miner.utils import combine_results, ProcessingTracker

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
            help="Synapse Personal Access Token (can also use SYNAPSE_PAT env var)"
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
            combine_results(args.output, args.directory, args.pattern)
            
        elif args.command == "workflow" and SYNAPSE_AVAILABLE:
            # Run automated workflow
            run_automated_workflow(args, logger)
            
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
        synapse_uploader = SynapseUploader(
            pat=args.synapse_pat or os.getenv('SYNAPSE_PAT')
        )
        
        # Create miner instance  
        miner = SynapseMiner(context_size=args.context_size)
        
        # Determine start file based on last processed PMC ID
        start_from = None
        if last_pmc_id:
            # Convert PMC ID to approximate pattern for finding next batch
            # Extract numeric part and use it to find the next available batch
            import re
            pmc_match = re.search(r'PMC(\d+)', last_pmc_id)
            if pmc_match:
                pmc_num = int(pmc_match.group(1))
                # Use the PMC ID pattern that core.py expects
                start_from = f"PMC{pmc_num}_PMC"
                logger.info(f"Will start from batches with PMC ID >= {pmc_num}")
            else:
                logger.warning(f"Could not parse PMC ID: {last_pmc_id}")
                start_from = last_pmc_id
            
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
        miner.process_http_files(
            base_url=args.url,
            output_path=args.output,
            start_from=start_from,
            max_files=args.max_files
        )
        
        # Find generated batch files
        batch_files = glob.glob(batch_pattern)
        batch_files.sort()  # Process in order
        
        if not batch_files:
            logger.warning("No batch files were generated")
            return
            
        logger.info(f"Found {len(batch_files)} batch files to upload")
        
        # Upload batch files and results to Synapse
        success = synapse_uploader.batch_upload_workflow(
            batch_files=batch_files,
            folder_id=args.folder_id,
            table_id=args.table_id
        )
        
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

if __name__ == "__main__":
    main()