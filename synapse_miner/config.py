"""
Configuration module for Synapse Miner.
"""

import os
import json
import logging
from typing import Dict, Optional
from pathlib import Path

class SynapseMinerConfig:
    """Configuration manager for Synapse Miner."""
    
    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize configuration.
        
        Args:
            config_file: Path to configuration file (optional)
        """
        self.config = self._load_config(config_file)
        self._setup_logging()
        
    def _load_config(self, config_file: Optional[str]) -> Dict:
        """Load configuration from file or use defaults."""
        default_config = {
            "context_size": 100,
            "deduplication": True,
            "batch_size": 100,
            "max_workers": None,
            "timeout": 300,
            "max_file_size": 500 * 1024 * 1024,  # 500MB
            "allowed_extensions": [".pdf", ".txt", ".xml", ".html", ".gz"],
            "log_level": "INFO",
            "log_file": "synapse_miner.log"
        }
        
        if config_file and os.path.exists(config_file):
            try:
                with open(config_file) as f:
                    user_config = json.load(f)
                    default_config.update(user_config)
            except (json.JSONDecodeError, IOError) as e:
                logging.warning(f"Error loading config file: {e}. Using defaults.")
                
        return default_config
    
    def _setup_logging(self):
        """Configure logging based on settings."""
        log_level = getattr(logging, self.config["log_level"].upper())
        log_file = self.config["log_file"]
        
        # Create log directory if it doesn't exist
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        
    def get(self, key: str, default=None):
        """Get configuration value."""
        return self.config.get(key, default)
    
    def set(self, key: str, value):
        """Set configuration value."""
        self.config[key] = value
        
    def save(self, config_file: str):
        """Save configuration to file."""
        try:
            with open(config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
        except IOError as e:
            logging.error(f"Error saving config file: {e}") 