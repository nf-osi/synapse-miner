"""
Utility functions for the Synapse ID Mining package.
"""

from .file_utils import extract_text_from_pdf, read_text_file
from .text_processing import extract_context
from .data_utils import combine_results
from .tracking import ProcessingTracker

try:
    from .synapse_integration import SynapseUploader
    SYNAPSE_AVAILABLE = True
except ImportError:
    SynapseUploader = None
    SYNAPSE_AVAILABLE = False

__all__ = [
    'extract_text_from_pdf', 
    'read_text_file', 
    'extract_context', 
    'combine_results',
    'ProcessingTracker'
]

if SYNAPSE_AVAILABLE:
    __all__.append('SynapseUploader')