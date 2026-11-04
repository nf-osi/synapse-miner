"""
Tracking utilities for managing processing state.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class ProcessingTracker:
    """Manages tracking of processing state for batch operations."""
    
    def __init__(self, tracking_file: str = "last_processed_pmc.json"):
        """
        Initialize tracker with tracking file path.
        
        Args:
            tracking_file: Path to the tracking file
        """
        self.tracking_file = Path(tracking_file)
        
    def get_last_processed_pmc_id(self) -> Optional[str]:
        """
        Get the last processed PMC ID from tracking file.
        
        Returns:
            The last PMC ID covered by the last processed batch file (older
            tracking files stored the batch's starting PMC ID instead), or None
            if not found
        """
        try:
            if self.tracking_file.exists():
                with open(self.tracking_file, 'r') as f:
                    data = json.load(f)
                    return data.get('last_processed_pmc_id')
            return None
        except Exception as e:
            logger.error(f"Error reading tracking file: {e}")
            return None
    
    def _read(self) -> dict:
        """The tracking file's contents, or {} if it is missing or unreadable."""
        try:
            if self.tracking_file.exists():
                with open(self.tracking_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error reading tracking file: {e}")
        return {}

    def get_failed_files(self) -> Dict[str, int]:
        """
        Batch files that failed in earlier runs and should be retried.

        Returns:
            {filename: number of runs in which it has failed}
        """
        failed = self._read().get('failed_files') or {}
        if isinstance(failed, list):
            failed = {name: 1 for name in failed}
        return {str(name): int(count) for name, count in failed.items()}

    def update_last_processed_pmc_id(self, pmc_id: Optional[str],
                                     failed_files: Optional[Dict[str, int]] = None) -> bool:
        """
        Update the last processed PMC ID in tracking file.
        
        Args:
            pmc_id: The ending PMC ID of the batch file that was processed, or
                None to keep the current one
            failed_files: Batch files to retry next run ({filename: failed
                runs}); None keeps the current list
            
        Returns:
            True if successful, False otherwise
        """
        try:
            current = self._read()
            data = {
                'last_processed_pmc_id': pmc_id or current.get('last_processed_pmc_id'),
                'updated_at': f"{__import__('datetime').datetime.now().isoformat()}"
            }
            failed = self.get_failed_files() if failed_files is None else failed_files
            if failed:
                data['failed_files'] = dict(sorted(failed.items()))
            
            # Ensure directory exists
            self.tracking_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.tracking_file, 'w') as f:
                json.dump(data, f, indent=2)
                
            logger.info(f"Updated tracking file with PMC ID: {data['last_processed_pmc_id']}"
                        + (f" and {len(failed)} files to retry" if failed else ""))
            return True
        except Exception as e:
            logger.error(f"Error updating tracking file: {e}")
            return False
            
    def extract_starting_pmc_id(self, filename: str) -> Optional[str]:
        """
        Extract the starting PMC ID from a filename.
        
        Args:
            filename: Filename like 'PMC11890001_PMC11900000.xml.gz'
            
        Returns:
            The starting PMC ID like 'PMC11890001'
        """
        import re
        match = re.search(r'(PMC\d+)_PMC\d+', filename)
        if match:
            return match.group(1)
        return None

    def extract_ending_pmc_id(self, filename: str) -> Optional[str]:
        """
        Extract the ending PMC ID from a filename.
        
        Args:
            filename: Filename like 'PMC11890001_PMC11900000.xml.gz'
            
        Returns:
            The ending PMC ID like 'PMC11900000'
        """
        import re
        match = re.search(r'PMC\d+_(PMC\d+)', filename)
        if match:
            return match.group(1)
        return None

    def get_resume_pmc_id(self) -> Optional[str]:
        """
        Get the first PMC ID not yet covered by a processed batch file.
        
        Batch files are processed from the first one whose starting PMC ID is
        >= this value, so the last processed file is not reprocessed.
        
        Returns:
            The PMC ID one past the last processed PMC ID, or None if not found
        """
        last_pmc_id = self.get_last_processed_pmc_id()
        if not last_pmc_id:
            return None
        import re
        match = re.fullmatch(r'PMC(\d+)', last_pmc_id)
        if not match:
            logger.warning(f"Unexpected PMC ID in tracking file: {last_pmc_id}")
            return None
        return f"PMC{int(match.group(1)) + 1}"
