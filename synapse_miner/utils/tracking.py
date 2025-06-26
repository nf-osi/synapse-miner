"""
Tracking utilities for managing processing state.
"""

import json
import logging
from pathlib import Path
from typing import Optional

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
            The starting PMC ID of the last processed batch, or None if not found
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
    
    def update_last_processed_pmc_id(self, pmc_id: str) -> bool:
        """
        Update the last processed PMC ID in tracking file.
        
        Args:
            pmc_id: The starting PMC ID of the batch that was processed
            
        Returns:
            True if successful, False otherwise
        """
        try:
            data = {
                'last_processed_pmc_id': pmc_id,
                'updated_at': f"{__import__('datetime').datetime.now().isoformat()}"
            }
            
            # Ensure directory exists
            self.tracking_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.tracking_file, 'w') as f:
                json.dump(data, f, indent=2)
                
            logger.info(f"Updated tracking file with PMC ID: {pmc_id}")
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