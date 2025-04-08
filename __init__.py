"""
Synapse ID Mining Package
=========================

A package for mining Synapse IDs from scientific articles.

This package provides functionality to scan scientific articles 
and extract Synapse IDs matching the pattern "syn" followed by 7-12 digits.
"""

__version__ = '0.1.0'
__author__ = 'Your Name'

from .core import SynapseMiner

# Convenience functions
from .core import mine_file, mine_directory

__all__ = ['SynapseMiner', 'mine_file', 'mine_directory']