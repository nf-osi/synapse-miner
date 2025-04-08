"""
File utility functions for the Synapse ID Mining package.
"""

import os
import logging
import PyPDF2

logger = logging.getLogger("synapse_miner.utils.file_utils")

def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract text content from a PDF file.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Extracted text content
    """
    logger.info(f"Extracting text from PDF: {pdf_path}")
    text = ""
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                text += page.extract_text() + "\n\n"
        return text
    except Exception as e:
        logger.error(f"Error extracting text from PDF {pdf_path}: {str(e)}")
        return ""

def read_text_file(file_path: str) -> str:
    """
    Read text content from a text file.
    
    Args:
        file_path: Path to the text file
        
    Returns:
        Text content
    """
    logger.info(f"Reading text file: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    except UnicodeDecodeError:
        # Try with a different encoding if UTF-8 fails
        try:
            with open(file_path, 'r', encoding='latin-1') as file:
                return file.read()
        except Exception as e:
            logger.error(f"Error reading text file {file_path} with latin-1 encoding: {str(e)}")
            return ""
    except Exception as e:
        logger.error(f"Error reading text file {file_path}: {str(e)}")
        return ""

def get_file_list(directory_path: str, extensions: list = None) -> list:
    """
    Get a list of files with the specified extensions from a directory.
    
    Args:
        directory_path: Path to the directory
        extensions: List of file extensions to include (e.g., ['.pdf', '.txt'])
        
    Returns:
        List of file paths
    """
    import glob
    
    if not extensions:
        extensions = ['.pdf', '.txt', '.xml', '.html']
        
    all_files = []
    for ext in extensions:
        files = glob.glob(os.path.join(directory_path, f"*{ext}"))
        all_files.extend(files)
        
    return all_files