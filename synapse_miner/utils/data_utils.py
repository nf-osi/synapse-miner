"""
Data utility functions for the Synapse ID Mining package.
"""

import os
import pandas as pd
import glob
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

def combine_results(output_path: str, 
                    directory: Optional[str] = None, 
                    pattern: str = "results.csv.*.csv") -> str:
    """
    Combine multiple batch CSV files into a single CSV file.
    
    Args:
        output_path: Path to save the combined results
        directory: Directory containing the batch files (defaults to current directory)
        pattern: Glob pattern to match batch files
        
    Returns:
        Path to the combined CSV file
    """
    try:
        # Use current directory if not specified
        directory = directory or "."
        
        # Find all files matching the pattern
        path = Path(directory)
        batch_files = sorted(list(path.glob(pattern)))
        
        logger.info(f"Found {len(batch_files)} batch files matching pattern '{pattern}'")
        
        if not batch_files:
            logger.warning(f"No files found matching pattern '{pattern}' in directory '{directory}'")
            return None
            
        # Combine all batch files
        all_data = []
        unique_synids = set()
        total_rows = 0
        
        for file in batch_files:
            try:
                df = pd.read_csv(file)
                # Extract source XML file name from the batch file name
                # Format is: results.csv.{xml_filename}.csv
                source_file = '.'.join(file.name.split('.')[2:-1])  # Get all parts except first two and last
                # Add source file column
                df['source_file'] = source_file
                total_rows += len(df)
                if 'synid' in df.columns:
                    unique_synids.update(df['synid'].unique())
                all_data.append(df)
                logger.info(f"Added {len(df)} rows from {file.name}")
            except Exception as e:
                logger.error(f"Error reading file {file}: {e}")
                continue
                
        if not all_data:
            logger.warning("No data found in any of the batch files")
            return None
            
        # Combine all dataframes
        combined_df = pd.concat(all_data, ignore_index=True)
        
        # Remove duplicates based on all columns except source_file
        combined_df = combined_df.drop_duplicates(subset=[col for col in combined_df.columns if col != 'source_file'])
        
        # Save to output file
        combined_df.to_csv(output_path, index=False)
        
        logger.info(f"Combined {len(batch_files)} files into {output_path}")
        logger.info(f"Total rows: {total_rows} (before deduplication)")
        logger.info(f"Final rows: {len(combined_df)} (after deduplication)")
        logger.info(f"Unique Synapse IDs: {len(unique_synids)}")
        
        return output_path
        
    except Exception as e:
        logger.error(f"Error combining results: {e}")
        return None 