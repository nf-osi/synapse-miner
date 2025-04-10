"""
Command-line interface for Synapse ID Mining.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from .core import SynapseMiner

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
        default="https://europepmc.org/ftp/oa/",
        help="Base URL of the HTTP server (default: https://europepmc.org/ftp/oa/)"
    )
    http_parser.add_argument(
        "-o", "--output",
        type=Path,
        default="results.csv",
        help="Path to save results (default: results.csv)"
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
            
        else:
            parser.print_help()
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()