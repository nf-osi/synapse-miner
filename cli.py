
"""
Command-line interface for the Synapse ID Mining package.
"""

import argparse
import sys
import os
from typing import List
import logging

from .core import SynapseMiner

logger = logging.getLogger("synapse_miner.cli")

def parse_args(args: List[str] = None) -> argparse.Namespace:
    """
    Parse command-line arguments.
    
    Args:
        args: Command-line arguments (defaults to sys.argv[1:])
        
    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Mine scientific articles for Synapse IDs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        "input",
        help="Path to a file or directory to process"
    )
    
    parser.add_argument(
        "--output", "-o",
        default="synapse_mining_results.csv",
        help="Output file path"
    )
    
    parser.add_argument(
        "--format", "-f",
        choices=["csv", "json"],
        default="csv",
        help="Output format"
    )
    
    parser.add_argument(
        "--context", "-c",
        type=int,
        default=100,
        help="Number of characters to extract around Synapse IDs"
    )
    
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Disable deduplication of identical Synapse IDs within a document"
    )
    
    parser.add_argument(
        "--extensions", "-e",
        nargs="+",
        default=[".pdf", ".txt", ".xml", ".html"],
        help="File extensions to process"
    )
    
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="Process files sequentially instead of in parallel"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="count",
        default=0,
        help="Increase verbosity (can be used multiple times)"
    )
    
    return parser.parse_args(args)

def setup_logging(verbosity: int) -> None:
    """
    Set up logging based on verbosity level.
    
    Args:
        verbosity: Verbosity level (0=WARNING, 1=INFO, 2+=DEBUG)
    """
    log_level = logging.WARNING
    if verbosity == 1:
        log_level = logging.INFO
    elif verbosity >= 2:
        log_level = logging.DEBUG
        
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("synapse_miner.log"),
            logging.StreamHandler()
        ]
    )

def main(args: List[str] = None) -> int:
    """
    Main entry point for the CLI.
    
    Args:
        args: Command-line arguments (defaults to sys.argv[1:])
        
    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    parsed_args = parse_args(args)
    setup_logging(parsed_args.verbose)
    
    try:
        # Initialize the miner
        miner = SynapseMiner(
            context_size=parsed_args.context,
            deduplication=not parsed_args.no_dedup
        )
        
        # Process input (file or directory)
        if os.path.isfile(parsed_args.input):
            logger.info(f"Processing file: {parsed_args.input}")
            findings = miner.process_file(parsed_args.input)
            if findings:
                file_name = os.path.basename(parsed_args.input)
                miner.results[file_name] = findings
        elif os.path.isdir(parsed_args.input):
            logger.info(f"Processing directory: {parsed_args.input}")
            miner.results = miner.process_directory(
                parsed_args.input,
                extensions=parsed_args.extensions,
                parallel=not parsed_args.sequential
            )
        else:
            logger.error(f"Input path does not exist: {parsed_args.input}")
            return 1
        
        # Generate and print summary
        summary = miner.generate_summary()
        print("\nSynapse ID Mining Summary:")
        print(f"Documents processed: {summary['total_documents_processed']}")
        print(f"Total Synapse ID mentions: {summary['total_synapse_id_mentions']}")
        print(f"Unique Synapse IDs: {summary['unique_synapse_ids']}")
        
        if summary['top_mentioned_ids']:
            print("\nTop mentioned Synapse IDs:")
            for synapse_id, count in summary['top_mentioned_ids'].items():
                print(f"  {synapse_id}: found in {count} documents")
        
        # Save results
        if parsed_args.format.lower() == 'csv':
            miner.save_results_to_csv(parsed_args.output)
        else:
            miner.save_results_to_json(parsed_args.output)
            
        logger.info(f"Results saved to {parsed_args.output}")
        return 0
        
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())