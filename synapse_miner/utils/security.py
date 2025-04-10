"""
Security utilities for Synapse Miner.
"""

import os
import logging
from pathlib import Path
from typing import Optional, List
import magic

logger = logging.getLogger("synapse_miner.security")

class SecurityError(Exception):
    """Base class for security-related errors."""
    pass

class FileValidationError(SecurityError):
    """Raised when file validation fails."""
    pass

def sanitize_path(file_path: str) -> str:
    """
    Sanitize and normalize a file path.
    
    Args:
        file_path: Path to sanitize
        
    Returns:
        Normalized absolute path
        
    Raises:
        SecurityError: If path contains suspicious patterns
    """
    # Convert to absolute path and normalize
    abs_path = os.path.abspath(file_path)
    norm_path = os.path.normpath(abs_path)
    
    # Check for path traversal attempts
    if ".." in norm_path.split(os.sep):
        raise SecurityError("Path traversal attempt detected")
        
    return norm_path

def validate_file(file_path: str, max_size: Optional[int] = None, 
                 allowed_extensions: Optional[List[str]] = None) -> bool:
    """
    Validate a file for processing.
    
    Args:
        file_path: Path to validate
        max_size: Maximum allowed file size in bytes
        allowed_extensions: List of allowed file extensions
        
    Returns:
        True if file is valid
        
    Raises:
        FileValidationError: If validation fails
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            raise FileValidationError(f"File not found: {file_path}")
            
        # Check if file is readable
        if not os.access(file_path, os.R_OK):
            raise FileValidationError(f"File not readable: {file_path}")
            
        # Check file size
        if max_size is not None:
            file_size = os.path.getsize(file_path)
            if file_size > max_size:
                raise FileValidationError(f"File too large: {file_size} bytes")
                
        # Check file extension
        if allowed_extensions is not None:
            ext = os.path.splitext(file_path)[1].lower()
            if ext not in allowed_extensions:
                raise FileValidationError(f"File extension not allowed: {ext}")
                
        # Check file type using python-magic
        try:
            file_type = magic.from_file(file_path, mime=True)
            if not file_type.startswith(('text/', 'application/pdf', 'application/xml', 'text/html', 'application/gzip', 'application/x-gzip')):
                raise FileValidationError(f"Unsupported file type: {file_type}")
        except ImportError:
            logger.warning("python-magic not installed, skipping file type validation")
            
        return True
        
    except OSError as e:
        raise FileValidationError(f"Error validating file: {e}")

def validate_directory(directory_path: str) -> bool:
    """
    Validate a directory for processing.
    
    Args:
        directory_path: Path to validate
        
    Returns:
        True if directory is valid
        
    Raises:
        FileValidationError: If validation fails
    """
    try:
        # Check if directory exists
        if not os.path.exists(directory_path):
            raise FileValidationError(f"Directory not found: {directory_path}")
            
        # Check if directory is readable
        if not os.access(directory_path, os.R_OK):
            raise FileValidationError(f"Directory not readable: {directory_path}")
            
        # Check if path is actually a directory
        if not os.path.isdir(directory_path):
            raise FileValidationError(f"Path is not a directory: {directory_path}")
            
        return True
        
    except OSError as e:
        raise FileValidationError(f"Error validating directory: {e}") 