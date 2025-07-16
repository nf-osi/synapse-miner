"""
Utility functions for the Synapse ID Mining package.
"""

from .text_processing import extract_context
from .tracking import ProcessingTracker

# Import file_utils conditionally to avoid PyPDF2 import issues
try:
    from .file_utils import extract_text_from_pdf, read_text_file
    FILE_UTILS_AVAILABLE = True
except ImportError:
    extract_text_from_pdf = None
    read_text_file = None
    FILE_UTILS_AVAILABLE = False

# Import combine_results conditionally to avoid pandas import issues
try:
    from .data_utils import combine_results
    DATA_UTILS_AVAILABLE = True
except ImportError:
    combine_results = None
    DATA_UTILS_AVAILABLE = False

try:
    from .synapse_integration import SynapseUploader
    SYNAPSE_AVAILABLE = True
except ImportError:
    SynapseUploader = None
    SYNAPSE_AVAILABLE = False

__all__ = [
    'extract_context', 
    'ProcessingTracker'
]

if FILE_UTILS_AVAILABLE:
    __all__.extend(['extract_text_from_pdf', 'read_text_file'])

if DATA_UTILS_AVAILABLE:
    __all__.append('combine_results')

if SYNAPSE_AVAILABLE:
    __all__.append('SynapseUploader')