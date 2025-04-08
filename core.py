"""
Core functionality for the Synapse ID Mining package.
"""

import re
import os
import pandas as pd
from collections import defaultdict
import logging
import json
from typing import List, Dict, Tuple, Set, Optional, Union
import concurrent.futures
from tqdm import tqdm

from .utils.file_utils import extract_text_from_pdf, read_text_file
from .utils.text_processing import extract_context

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("synapse_miner.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("synapse_miner")

class SynapseMiner:
    """A tool for mining Synapse IDs from scientific articles."""
    
    def __init__(self, context_size: int = 100, deduplication: bool = True):
        """
        Initialize the SynapseMiner.
        
        Args:
            context_size: Number of characters to extract around the Synapse ID for context
            deduplication: Whether to deduplicate identical Synapse IDs within a document
        """
        self.context_size = context_size
        self.deduplication = deduplication
        # Regex pattern for Synapse IDs: 'syn' followed by 7-12 digits
        self.synapse_pattern = re.compile(r'syn\d{7,12}', re.IGNORECASE)
        self.results = defaultdict(list)
        
    def extract_synapse_ids_with_context(self, text: str, document_name: str) -> List[Dict]:
        """
        Extract Synapse IDs with surrounding context from text.
        
        Args:
            text: Text to search for Synapse IDs
            document_name: Name of the document being processed
            
        Returns:
            List of dictionaries containing Synapse IDs and their context
        """
        logger.info(f"Extracting Synapse IDs from document: {document_name}")
        findings = []
        seen_ids = set() if self.deduplication else None
        
        for match in self.synapse_pattern.finditer(text):
            synapse_id = match.group(0)
            
            # Skip if we've already seen this ID and deduplication is enabled
            if self.deduplication and synapse_id in seen_ids:
                continue
                
            # Get context around the match
            context = extract_context(text, match.start(), match.end(), self.context_size)
            
            # Create the finding record
            finding = {
                "synapse_id": synapse_id,
                "document": document_name,
                "position": match.start(),
                "context_before": context["before"],
                "context_after": context["after"],
                "full_context": context["full"]
            }
            
            findings.append(finding)
            
            # Add to seen set if deduplication is enabled
            if self.deduplication:
                seen_ids.add(synapse_id)
        
        return findings
    
    def process_file(self, file_path: str) -> List[Dict]:
        """
        Process a single file to extract Synapse IDs.
        
        Args:
            file_path: Path to the file to process
            
        Returns:
            List of findings from the file
        """
        file_name = os.path.basename(file_path)
        logger.info(f"Processing file: {file_name}")
        
        if file_path.lower().endswith('.pdf'):
            text = extract_text_from_pdf(file_path)
        else:
            text = read_text_file(file_path)
            
        if not text:
            logger.warning(f"No text content extracted from {file_name}")
            return []
            
        findings = self.extract_synapse_ids_with_context(text, file_name)
        logger.info(f"Found {len(findings)} Synapse ID mentions in {file_name}")
        
        return findings
    
    def process_directory(self, directory_path: str, extensions: List[str] = None, 
                         parallel: bool = True, max_workers: int = None) -> Dict[str, List[Dict]]:
        """
        Process all files in a directory to extract Synapse IDs.
        
        Args:
            directory_path: Path to the directory containing files to process
            extensions: List of file extensions to process (e.g., ['.pdf', '.txt'])
            parallel: Whether to process files in parallel
            max_workers: Maximum number of worker threads for parallel processing
            
        Returns:
            Dictionary mapping document names to lists of findings
        """
        import glob
        
        if not extensions:
            extensions = ['.pdf', '.txt', '.xml', '.html']
            
        # Find all files with the specified extensions
        all_files = []
        for ext in extensions:
            files = glob.glob(os.path.join(directory_path, f"*{ext}"))
            all_files.extend(files)
            
        logger.info(f"Found {len(all_files)} files to process in {directory_path}")
        
        if not all_files:
            logger.warning(f"No files found in {directory_path} with extensions {extensions}")
            return {}
            
        results = defaultdict(list)
        
        if parallel:
            # Process files in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_file = {executor.submit(self.process_file, file_path): file_path 
                                 for file_path in all_files}
                
                for future in tqdm(concurrent.futures.as_completed(future_to_file), 
                                  total=len(all_files), desc="Processing files"):
                    file_path = future_to_file[future]
                    file_name = os.path.basename(file_path)
                    try:
                        findings = future.result()
                        if findings:
                            results[file_name] = findings
                    except Exception as e:
                        logger.error(f"Error processing {file_name}: {str(e)}")
        else:
            # Process files sequentially
            for file_path in tqdm(all_files, desc="Processing files"):
                file_name = os.path.basename(file_path)
                try:
                    findings = self.process_file(file_path)
                    if findings:
                        results[file_name] = findings
                except Exception as e:
                    logger.error(f"Error processing {file_name}: {str(e)}")
                    
        return results
    
    def save_results_to_csv(self, output_path: str) -> None:
        """
        Save results to a CSV file.
        
        Args:
            output_path: Path to save the CSV file
        """
        all_findings = []
        for document, findings in self.results.items():
            all_findings.extend(findings)
            
        if not all_findings:
            logger.warning("No findings to save")
            return
            
        df = pd.DataFrame(all_findings)
        df.to_csv(output_path, index=False)
        logger.info(f"Results saved to {output_path}")
    
    def save_results_to_json(self, output_path: str) -> None:
        """
        Save results to a JSON file.
        
        Args:
            output_path: Path to save the JSON file
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(dict(self.results), f, indent=2)
        logger.info(f"Results saved to {output_path}")
    
    def generate_summary(self) -> Dict:
        """
        Generate a summary of the mining results.
        
        Returns:
            Dictionary containing summary statistics
        """
        total_documents = len(self.results)
        total_mentions = sum(len(findings) for findings in self.results.values())
        
        # Count unique Synapse IDs
        unique_ids = set()
        for findings in self.results.values():
            for finding in findings:
                unique_ids.add(finding["synapse_id"])
                
        # Document frequency of each Synapse ID
        id_document_freq = defaultdict(set)
        for doc, findings in self.results.items():
            for finding in findings:
                id_document_freq[finding["synapse_id"]].add(doc)
                
        # Convert to counts
        id_document_freq = {id_: len(docs) for id_, docs in id_document_freq.items()}
        
        # Find top mentioned IDs
        top_ids = sorted(id_document_freq.items(), key=lambda x: x[1], reverse=True)[:10]
        
        summary = {
            "total_documents_processed": total_documents,
            "total_synapse_id_mentions": total_mentions,
            "unique_synapse_ids": len(unique_ids),
            "top_mentioned_ids": dict(top_ids)
        }
        
        return summary

# Convenience functions
def mine_file(file_path: str, context_size: int = 100, deduplication: bool = True) -> Dict:
    """
    Mine a single file for Synapse IDs.
    
    Args:
        file_path: Path to the file to mine
        context_size: Number of characters to extract around the Synapse ID for context
        deduplication: Whether to deduplicate identical Synapse IDs within a document
        
    Returns:
        Dictionary with mining results
    """
    miner = SynapseMiner(context_size=context_size, deduplication=deduplication)
    findings = miner.process_file(file_path)
    
    return {
        'findings': findings,
        'summary': {
            'total_mentions': len(findings),
            'unique_ids': len(set(f['synapse_id'] for f in findings))
        }
    }

def mine_directory(directory_path: str, extensions: List[str] = None, 
                  context_size: int = 100, deduplication: bool = True,
                  parallel: bool = True, max_workers: int = None) -> Dict:
    """
    Mine a directory of files for Synapse IDs.
    
    Args:
        directory_path: Path to the directory to mine
        extensions: List of file extensions to process
        context_size: Number of characters to extract around the Synapse ID for context
        deduplication: Whether to deduplicate identical Synapse IDs within a document
        parallel: Whether to process files in parallel
        max_workers: Maximum number of worker threads for parallel processing
        
    Returns:
        Dictionary with mining results
    """
    miner = SynapseMiner(context_size=context_size, deduplication=deduplication)
    results = miner.process_directory(directory_path, extensions=extensions, 
                                    parallel=parallel, max_workers=max_workers)
    miner.results = results
    
    return {
        'results': results,
        'summary': miner.generate_summary()
    }