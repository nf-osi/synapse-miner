"""
Synapse integration utilities for uploading results and managing tables.
"""

import logging
import pandas as pd
from pathlib import Path
from typing import List, Optional, Set

logger = logging.getLogger(__name__)

try:
    import synapseclient
    from synapseclient import File, Table
    SYNAPSE_AVAILABLE = True
except ImportError:
    logger.warning("synapseclient not available. Synapse integration disabled.")
    SYNAPSE_AVAILABLE = False

class SynapseUploader:
    """Handles uploading results to Synapse."""
    
    def __init__(self, username: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initialize Synapse client.
        
        Args:
            username: Synapse username (optional, can use environment vars)
            api_key: Synapse API key (optional, can use environment vars)
        """
        if not SYNAPSE_AVAILABLE:
            raise ImportError("synapseclient is required for Synapse integration")
            
        self.syn = synapseclient.Synapse()
        try:
            if username and api_key:
                self.syn.login(email=username, apiKey=api_key)
            else:
                # Try to login using cached credentials or environment variables
                self.syn.login()
            logger.info("Successfully logged into Synapse")
        except Exception as e:
            logger.error(f"Failed to login to Synapse: {e}")
            raise
    
    def upload_batch_file(self, file_path: str, parent_folder_id: str, 
                         description: Optional[str] = None) -> Optional[str]:
        """
        Upload a batch CSV file to Synapse folder.
        
        Args:
            file_path: Path to the CSV file to upload
            parent_folder_id: Synapse ID of the parent folder
            description: Optional description for the file
            
        Returns:
            Synapse ID of uploaded file, or None if failed
        """
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                logger.error(f"File does not exist: {file_path}")
                return None
                
            # Create File entity
            file_entity = File(
                path=str(file_path),
                parent=parent_folder_id,
                description=description or f"Batch results from {file_path.name}"
            )
            
            # Upload to Synapse
            uploaded_file = self.syn.store(file_entity)
            logger.info(f"Uploaded {file_path.name} to Synapse: {uploaded_file.id}")
            return uploaded_file.id
            
        except Exception as e:
            logger.error(f"Error uploading file {file_path}: {e}")
            return None
    
    def get_existing_pmc_ids(self, table_id: str) -> Set[str]:
        """
        Get existing PMC IDs from Synapse table to avoid duplicates.
        
        Args:
            table_id: Synapse ID of the table
            
        Returns:
            Set of PMC IDs already in the table
        """
        try:
            # Query to get all PMC IDs from the table
            query = f"SELECT pmcid FROM {table_id}"
            results = self.syn.tableQuery(query)
            df = results.asDataFrame()
            
            if 'pmcid' in df.columns:
                existing_ids = set(df['pmcid'].astype(str))
                logger.info(f"Found {len(existing_ids)} existing PMC IDs in table {table_id}")
                return existing_ids
            else:
                logger.warning(f"No 'pmcid' column found in table {table_id}")
                return set()
                
        except Exception as e:
            logger.error(f"Error querying existing PMC IDs from table {table_id}: {e}")
            return set()
    
    def upload_new_results_to_table(self, csv_path: str, table_id: str, 
                                   check_duplicates: bool = True) -> bool:
        """
        Upload new results to Synapse table, filtering out duplicates.
        
        Args:
            csv_path: Path to CSV file with results
            table_id: Synapse ID of the target table
            check_duplicates: Whether to check for existing PMC IDs
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Read the CSV file
            df = pd.read_csv(csv_path)
            
            if df.empty:
                logger.info(f"No data to upload from {csv_path}")
                return True
                
            original_count = len(df)
            
            # Filter out duplicates if requested
            if check_duplicates:
                existing_ids = self.get_existing_pmc_ids(table_id)
                if existing_ids:
                    # Filter out rows where pmcid already exists
                    if 'pmcid' in df.columns:
                        df = df[~df['pmcid'].astype(str).isin(existing_ids)]
                        logger.info(f"Filtered out {original_count - len(df)} duplicate PMC IDs")
                    else:
                        logger.warning("No 'pmcid' column found in CSV data")
            
            if df.empty:
                logger.info("No new data to upload after filtering duplicates")
                return True
            
            # Upload to table
            table = self.syn.store(Table(table_id, df))
            logger.info(f"Successfully uploaded {len(df)} new rows to table {table_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error uploading results to table {table_id}: {e}")
            return False
    
    def batch_upload_workflow(self, batch_files: List[str], folder_id: str, 
                            table_id: str) -> bool:
        """
        Complete workflow for uploading multiple batch files.
        
        Args:
            batch_files: List of paths to batch CSV files
            folder_id: Synapse folder ID for storing individual files
            table_id: Synapse table ID for aggregated results
            
        Returns:
            True if all uploads successful, False otherwise
        """
        try:
            success_count = 0
            
            for batch_file in batch_files:
                logger.info(f"Processing batch file: {batch_file}")
                
                # Upload individual batch file to folder
                file_id = self.upload_batch_file(batch_file, folder_id)
                if not file_id:
                    logger.error(f"Failed to upload batch file: {batch_file}")
                    continue
                
                # Upload new results to table
                if not self.upload_new_results_to_table(batch_file, table_id):
                    logger.error(f"Failed to upload results to table from: {batch_file}")
                    continue
                    
                success_count += 1
                logger.info(f"Successfully processed batch file: {batch_file}")
            
            logger.info(f"Completed batch upload: {success_count}/{len(batch_files)} successful")
            return success_count == len(batch_files)
            
        except Exception as e:
            logger.error(f"Error in batch upload workflow: {e}")
            return False