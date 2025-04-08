"""
Text processing utilities for the Synapse ID Mining package.
"""

from typing import Dict

def extract_context(text: str, start_pos: int, end_pos: int, context_size: int) -> Dict[str, str]:
    """
    Extract context around a specified position in text.
    
    Args:
        text: The text to extract context from
        start_pos: Start position of the target text
        end_pos: End position of the target text
        context_size: Number of characters to include as context before and after
        
    Returns:
        Dictionary with before, after, and full context
    """
    # Calculate context boundaries
    context_start = max(0, start_pos - context_size)
    context_end = min(len(text), end_pos + context_size)
    
    # Extract context
    before = text[context_start:start_pos].strip()
    after = text[end_pos:context_end].strip()
    target = text[start_pos:end_pos]
    full = (before + " " + target + " " + after).strip()
    
    return {
        "before": before,
        "after": after,
        "full": full
    }

def clean_text(text: str) -> str:
    """
    Clean and normalize text.
    
    Args:
        text: Text to clean
        
    Returns:
        Cleaned text
    """
    # Remove excess whitespace
    text = ' '.join(text.split())
    
    # Additional cleaning steps can be added as needed
    
    return text