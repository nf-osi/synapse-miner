"""
Core functionality for the Synapse ID Mining package.
"""

import re
import os
import gzip
import xml.etree.ElementTree as ET
import pandas as pd
import logging
import urllib.request
import tempfile
import shutil
import time
from typing import List, Dict, Optional, Iterator, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import islice
from rich.progress import (
    Progress,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
    SpinnerColumn,
    MofNCompleteColumn
)

logger = logging.getLogger("synapse_miner.core")

def process_article(article_xml: str, context_size: int) -> Tuple[Optional[str], List[Dict]]:
    """Process a single article in a worker process."""
    findings = []
    pmc_id = None
    
    try:
        # Parse XML
        root = ET.fromstring(article_xml)
        
        # Extract PMC ID
        for article_id in root.findall(".//article-id"):
            if article_id.get("pub-id-type") in ["pmc", "pmcid"]:
                pmc_id = article_id.text
                break
                
        if not pmc_id:
            # Try regex as fallback
            pmc_id_match = re.search(r'(?:PMC|pmc)(\d+)', article_xml)
            if pmc_id_match:
                pmc_id = f"PMC{pmc_id_match.group(1)}"
            else:
                return None, []
                
        # Ensure PMC ID has the correct format
        if not pmc_id.startswith("PMC"):
            pmc_id = f"PMC{pmc_id}"
                
        # Extract text content from relevant sections
        text_parts = []
        
        def extract_text(element):
            """Recursively extract text from an element and its children."""
            if element is None:
                return ""
                
            # Get direct text
            text = element.text or ""
            
            # Get text from all children
            for child in element:
                child_text = extract_text(child)
                # Add a space before child text if needed
                if child_text and text and not text.endswith(' '):
                    text += ' '
                text += child_text
                # Add tail text (text after the element)
                if child.tail:
                    # Add a space before tail text if needed
                    if text and not text.endswith(' '):
                        text += ' '
                    text += child.tail
                    
            return text.strip()
            
        # Extract from title
        title = root.find(".//article-title")
        if title is not None:
            text_parts.append(extract_text(title))
            
        # Extract from abstract
        abstract = root.find(".//abstract")
        if abstract is not None:
            text_parts.append(extract_text(abstract))
                    
        # Extract from body
        body = root.find(".//body")
        if body is not None:
            text_parts.append(extract_text(body))
                    
        # Extract from back matter (references)
        back = root.find(".//back")
        if back is not None:
            text_parts.append(extract_text(back))
                    
        # Join all text parts with spaces and clean up whitespace
        text = ' '.join(text_parts)
        # Replace multiple spaces with single space
        text = re.sub(r'\s+', ' ', text)
        
        # Find Synapse IDs with improved pattern matching
        # Look for 'syn' followed by 7-12 digits, ensuring it's not part of a larger number
        synapse_pattern = re.compile(r'(?<!\d)syn\d{7,12}(?!\d)', re.IGNORECASE)
        for match in synapse_pattern.finditer(text):
            # Get 25 characters before and after the Synapse ID
            start = max(0, match.start() - 25)
            end = min(len(text), match.end() + 25)
            context = text[start:end].strip()
            
            # Extract the Synapse ID and ensure it's properly formatted
            syn_id = match.group(0).lower()  # Convert to lowercase for consistency
            
            # Additional validation to ensure it's a valid Synapse ID
            # Synapse IDs should be between 7-12 digits after 'syn'
            if not re.match(r'^syn\d{7,12}$', syn_id):
                continue
                
            # Skip if context is too short or doesn't contain the Synapse ID
            if len(context) < 10 or syn_id not in context:
                continue
            
            # Clean up the context for CSV output
            # Replace any double quotes with single quotes
            context = context.replace('"', "'")
            
            findings.append({
                "pmcid": pmc_id,
                "synid": syn_id,
                "context": context
            })
            
    except ET.ParseError as e:
        logger.error(f"Error parsing XML: {e}")
        return None, []
    except Exception as e:
        logger.error(f"Error processing article: {e}")
        return None, []
        
    return pmc_id, findings

class SynapseMiner:
    """A tool for mining Synapse IDs from scientific articles."""
    
    def __init__(self, context_size: int = 100, max_workers: Optional[int] = None):
        """
        Initialize the SynapseMiner.
        
        Args:
            context_size: Number of characters to include around each Synapse ID
            max_workers: Maximum number of worker processes to use
        """
        self.context_size = context_size
        self.max_workers = max_workers or os.cpu_count()
        self.synapse_pattern = re.compile(r'syn\d{7,12}', re.IGNORECASE)
        
        # Set up a custom opener with User-Agent and timeout
        self.opener = urllib.request.build_opener()
        self.opener.addheaders = [
            ('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'),
            ('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'),
            ('Accept-Language', 'en-US,en;q=0.5'),
            ('Connection', 'keep-alive'),
        ]
        urllib.request.install_opener(self.opener)
        
    def _make_request(self, url: str, max_retries: int = 3, retry_delay: int = 5, timeout: int = 30) -> str:
        """Make an HTTP request with retries and proper headers."""
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(url, timeout=timeout) as response:
                    return response.read().decode('utf-8')
            except urllib.error.HTTPError as e:
                if e.code == 503 and attempt < max_retries - 1:
                    logger.warning(f"Server busy (503), retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                raise
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Error making request, retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                raise
                
        raise Exception(f"Failed to make request after {max_retries} attempts")
        
    def _download_file(self, url: str, local_path: str, progress: Optional[Progress] = None, task: Optional[int] = None) -> None:
        """Download a file with progress tracking and timeout."""
        try:
            def report_hook(count, block_size, total_size):
                if progress and task is not None and total_size > 0:
                    if progress.tasks[task].total is None:
                        progress.update(task, total=total_size)
                    progress.update(task, advance=block_size)
                
            urllib.request.urlretrieve(url, local_path, reporthook=report_hook)
                
        except Exception as e:
            logger.error(f"Error downloading {url}: {e}")
            raise
            
    def _iter_articles(self, file_path: str, is_gzipped: bool = False, chunk_size: int = 10 * 1024 * 1024) -> Iterator[str]:
        """Iterate over articles in the file using a memory-efficient approach."""
        opener = gzip.open if is_gzipped else open
        buffer = ""
        
        with opener(file_path, 'rt', encoding='utf-8') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk and not buffer:
                    break
                    
                buffer += chunk
                
                while '<article ' in buffer and '</article>' in buffer:
                    start = buffer.find('<article ')
                    end = buffer.find('</article>', start) + len('</article>')
                    
                    if start == -1 or end == -1:
                                    break
                        
                    yield buffer[start:end]
                    buffer = buffer[end:]
                    
                if not chunk:  # End of file
                    break
                    
    def _process_xml_file(self, file_path: str, is_gzipped: bool = False, progress: Optional[Progress] = None, task: Optional[int] = None) -> List[Dict]:
        """Process an XML file and extract Synapse IDs using parallel processing."""
        findings = []
        article_count = 0
        processed_count = 0
        synapse_count = 0
        
        try:
            # Count articles (memory efficient)
            logger.info("Counting articles in file...")
            with (gzip.open(file_path, 'rt', encoding='utf-8') if is_gzipped 
                  else open(file_path, 'rt', encoding='utf-8')) as f:
                article_count = sum(1 for line in f if '<article ' in line)
                        
            logger.info(f"Found {article_count} articles to process")
            
            # Only show progress bar if we have articles to process
            if article_count > 0 and progress and task is not None:
                progress.update(task, total=article_count, completed=0)
            
            # Process articles in parallel
            with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit articles in batches to avoid memory issues
                batch_size = 100
                article_iter = self._iter_articles(file_path, is_gzipped)
                
                while True:
                    # Get next batch of articles
                    batch = list(islice(article_iter, batch_size))
                    if not batch:
                        break
                        
                    # Submit batch for processing
                    futures = [
                        executor.submit(process_article, article, self.context_size)
                        for article in batch
                    ]
                    
                    # Process results as they complete
                    for future in as_completed(futures):
                        try:
                            pmc_id, article_findings = future.result()
                            findings.extend(article_findings)
                            synapse_count += len(article_findings)
                            processed_count += 1
                            if progress and task is not None:
                                # Update progress with percentage of articles processed
                                progress.update(task, 
                                             completed=processed_count,
                                             description=f"Processing articles ({processed_count}/{article_count}, found {synapse_count} Synapse IDs)")
                        except Exception as e:
                            logger.error(f"Error processing article: {e}")
                            processed_count += 1
                            if progress and task is not None:
                                progress.update(task, 
                                             completed=processed_count,
                                             description=f"Processing articles ({processed_count}/{article_count}, found {synapse_count} Synapse IDs)")
                            
            # Check if we processed all articles
            if processed_count < article_count:
                logger.warning(f"Only processed {processed_count} out of {article_count} articles")
            elif processed_count > article_count:
                logger.warning(f"Processed {processed_count} articles but only expected {article_count}")
                
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            
        return findings
        
    def process_file(self, file_path: str, output_path: Optional[str] = None) -> List[Dict]:
        """Process a local file and extract Synapse IDs."""
        if not os.path.exists(file_path):
            logger.error(f"File does not exist: {file_path}")
            return []

        is_gzipped = file_path.lower().endswith('.gz')
        findings = self._process_xml_file(file_path, is_gzipped)
        
        # Save results if output path is provided
        if output_path and findings:
            df = pd.DataFrame(findings)
            df.to_csv(output_path, index=False)
            logger.info(f"Saved {len(findings)} findings to {output_path}")
            
        return findings
        
    def process_http_files(self, base_url: str, output_path: str, 
                         start_from: Optional[str] = None, 
                         max_files: Optional[int] = None) -> None:
        """
        Process XML files from an HTTP server.
        
        Args:
            base_url: Base URL of the HTTP server
            output_path: Path to save results
            start_from: Filename to start processing from
            max_files: Maximum number of files to process
        """
        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        
        try:
            # Get directory listing
            logger.info("Fetching directory listing...")
            html = self._make_request(base_url)
                
            # Extract file URLs and parse PMC IDs
            file_entries = []
            for match in re.finditer(r'<a href="([^"]+\.xml\.gz)"', html):
                filename = match.group(1)
                # Extract PMC ID range
                pmc_match = re.search(r'PMC(\d+)_PMC(\d+)', filename)
                if pmc_match:
                    start_pmc = int(pmc_match.group(1))
                    end_pmc = int(pmc_match.group(2))
                    file_entries.append({
                        'url': base_url + filename,
                        'filename': filename,
                        'start_pmc': start_pmc,
                        'end_pmc': end_pmc
                    })
                
            # Sort files by starting PMC ID
            file_entries.sort(key=lambda x: x['start_pmc'])
            file_urls = [entry['url'] for entry in file_entries]
            
            # Find starting point
            if start_from:
                # Extract PMC ID range from start_from
                start_pmc_match = re.search(r'PMC(\d+)_PMC(\d+)', start_from)
                if start_pmc_match:
                    start_pmc = int(start_pmc_match.group(1))
                    # Find the first file with PMC ID >= start_pmc
                    for i, entry in enumerate(file_entries):
                        if entry['start_pmc'] >= start_pmc:
                            file_urls = [e['url'] for e in file_entries[i:]]
                            logger.info(f"Starting from file: {file_urls[0]}")
                            break
                    else:
                        logger.warning(f"Could not find file with PMC ID >= {start_pmc}")
                else:
                    # Try exact filename match as fallback
                    try:
                        start_idx = next(i for i, entry in enumerate(file_entries) 
                                       if entry['filename'] == start_from)
                        file_urls = [e['url'] for e in file_entries[start_idx:]]
                        logger.info(f"Starting from file: {file_urls[0]}")
                    except StopIteration:
                        logger.warning(f"Start file {start_from} not found, starting from beginning")
                    
            # Limit number of files
            if max_files:
                file_urls = file_urls[:max_files]
                
            # Process files
            all_findings = []
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
            ) as progress:
                # Create a single task for progress
                task = progress.add_task("Processing", total=None)
                
                for file_url in file_urls:
                    try:
                        # Download file with retries
                        local_path = os.path.join(temp_dir, os.path.basename(file_url))
                        
                        max_retries = 3
                        retry_delay = 5
                        for attempt in range(max_retries):
                            try:
                                # Create a custom opener with progress tracking
                                def report_hook(count, block_size, total_size):
                                    if total_size > 0:
                                        # Update download progress
                                        progress.update(task, 
                                                     description=f"Downloading {os.path.basename(file_url)}",
                                                     total=total_size,
                                                     completed=count * block_size)
                                
                                urllib.request.urlretrieve(file_url, local_path, reporthook=report_hook)
                                break
                            except urllib.error.HTTPError as e:
                                if attempt < max_retries - 1:
                                    logger.warning(f"HTTP Error {e.code} downloading {file_url}, retrying in {retry_delay} seconds...")
                                    time.sleep(retry_delay)
                                    continue
                                raise
                            except Exception as e:
                                if attempt < max_retries - 1:
                                    logger.warning(f"Error downloading {file_url}, retrying in {retry_delay} seconds...")
                                    time.sleep(retry_delay)
                                    continue
                                raise
                        
                        # Process file
                        progress.update(task, description=f"Processing {os.path.basename(file_url)}...")
                        findings = self._process_xml_file(local_path, is_gzipped=True, progress=progress, task=task)
                        all_findings.extend(findings)
                        
                        # Save results after each file
                        if findings:
                            # Create a new CSV file for this batch of results
                            batch_output_path = f"{output_path}.{os.path.basename(file_url)}.csv"
                            df = pd.DataFrame(findings)
                            df.to_csv(batch_output_path, index=False)
                            logger.info(f"Saved {len(findings)} findings from {os.path.basename(file_url)} to {batch_output_path}")
                            
                            # Also update the main results file
                            df = pd.DataFrame(all_findings)
                            df.to_csv(output_path, index=False)
                            logger.info(f"Updated main results file with {len(all_findings)} total findings")
                        
                        # Remove downloaded file
                        os.remove(local_path)
                        logger.info(f"Removed downloaded file: {local_path}")
                        
                        # Update progress with number of Synapse IDs found
                        progress.update(task, 
                                     description=f"Processing files (found {len(all_findings)} Synapse IDs)")
                    except Exception as e:
                        logger.error(f"Error processing {file_url}: {e}")
                        continue
                    
            # Final save of all results
            if all_findings:
                df = pd.DataFrame(all_findings)
                df.to_csv(output_path, index=False)
                logger.info(f"Final save: {len(all_findings)} total findings saved to {output_path}")
            else:
                logger.warning("No findings to save")
                
        finally:
            # Clean up
            shutil.rmtree(temp_dir)