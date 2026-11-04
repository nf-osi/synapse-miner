"""
Command-line interface for Synapse ID Mining.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from .core import SynapseMiner
from synapse_miner.utils import ProcessingTracker

# Import combine_results conditionally
try:
    from synapse_miner.utils import combine_results
    COMBINE_AVAILABLE = True
except ImportError:
    combine_results = None
    COMBINE_AVAILABLE = False

# Import SynapseUploader only if available
try:
    from synapse_miner.utils import SynapseUploader
    SYNAPSE_AVAILABLE = True
except ImportError:
    SynapseUploader = None
    SYNAPSE_AVAILABLE = False

def setup_logging(verbose: bool = False) -> None:
    """Set up logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

def main() -> None:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Mine Synapse IDs from scientific articles."
    )
    
    # Common arguments
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "-c", "--context-size",
        type=int,
        default=100,
        help="Number of characters to include around each Synapse ID (default: 100)"
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Process local file
    local_parser = subparsers.add_parser(
        "process",
        help="Process a local XML file"
    )
    local_parser.add_argument(
        "file",
        type=Path,
        help="Path to the XML file to process"
    )
    local_parser.add_argument(
        "-o", "--output",
        type=Path,
        default="results.csv",
        help="Path to save results (default: results.csv)"
    )
    
    # Process HTTP files
    http_parser = subparsers.add_parser(
        "http",
        help="Process XML files from HTTP server"
    )
    http_parser.add_argument(
        "-u", "--url",
        required=True,
        help="Base URL of the HTTP server"
    )
    http_parser.add_argument(
        "-o", "--output",
        required=True,
        help="Path to save results"
    )
    http_parser.add_argument(
        "-s", "--start-from",
        help="Filename to start processing from"
    )
    http_parser.add_argument(
        "-m", "--max-files",
        type=int,
        help="Maximum number of files to process"
    )
    
    # Combine command
    combine_parser = subparsers.add_parser(
        "combine",
        help="Combine multiple batch CSV files into one"
    )
    combine_parser.add_argument(
        "-o", "--output",
        required=True,
        help="Path to save combined results"
    )
    combine_parser.add_argument(
        "-d", "--directory",
        help="Directory containing batch files (default: current directory)"
    )
    combine_parser.add_argument(
        "-p", "--pattern",
        default="results.csv.*.csv",
        help="Glob pattern to match batch files (default: results.csv.*.csv)"
    )
    
    # Automated workflow command
    if SYNAPSE_AVAILABLE:
        workflow_parser = subparsers.add_parser(
            "workflow",
            help="Run automated weekly workflow with Synapse integration"
        )
        workflow_parser.add_argument(
            "-u", "--url",
            default="https://ftp.ebi.ac.uk/pub/databases/pmc/oa/",
            help="Base URL of the Europe PMC server (default: https://ftp.ebi.ac.uk/pub/databases/pmc/oa/)"
        )
        workflow_parser.add_argument(
            "-o", "--output",
            default="workflow_results.csv",
            help="Base name for output files (default: workflow_results.csv)"
        )
        workflow_parser.add_argument(
            "-t", "--tracking-file",
            default="last_processed_pmc.json",
            help="Path to tracking file (default: last_processed_pmc.json)"
        )
        workflow_parser.add_argument(
            "--folder-id",
            required=True,
            help="Synapse folder ID for uploading batch files (e.g., syn66046437)"
        )
        workflow_parser.add_argument(
            "--table-id", 
            required=True,
            help="Synapse table ID for uploading results (e.g., syn66047339)"
        )
        workflow_parser.add_argument(
            "-m", "--max-files",
            type=int,
            help="Maximum number of files to process (for testing)"
        )
        workflow_parser.add_argument(
            "--synapse-pat",
            help="Synapse Personal Access Token (can also use SERVICE_TOKEN or SYNAPSE_PAT env var)"
        )
    
    # EBI Search XML generation command
    if SYNAPSE_AVAILABLE:
        ebisearch_parser = subparsers.add_parser(
            "ebisearch",
            help="Generate EBI Search XML from Synapse table"
        )
        ebisearch_parser.add_argument(
            "--table-id",
            required=True,
            help="Synapse table ID to query for results (e.g., syn66047339)"
        )
        ebisearch_parser.add_argument(
            "--output-dir",
            default="ebisearch",
            help="Directory to write ebisearch.xml and entity_cache.json (default: ebisearch)"
        )
        ebisearch_parser.add_argument(
            "--cache-file",
            default=None,
            help="Path to entity metadata cache JSON (default: <output-dir>/entity_cache.json)"
        )
        ebisearch_parser.add_argument(
            "--refresh",
            action="store_true",
            help="Re-fetch all entity metadata from Synapse, ignoring and overwriting the cache"
        )
        ebisearch_parser.add_argument(
            "--db-name",
            default="Sage Bionetworks Synapse",
            help="Database name written to the EBI Search XML header"
        )
        ebisearch_parser.add_argument(
            "--db-description",
            default="Datasets available via Synapse, the Sage Bionetworks data sharing platform",
            help="Database description written to the EBI Search XML header"
        )
        ebisearch_parser.add_argument(
            "--synapse-pat",
            help="Synapse Personal Access Token (can also use SYNAPSE_PAT env var)"
        )

    # LabLinks XML generation command
    if SYNAPSE_AVAILABLE:
        labslinks_parser = subparsers.add_parser(
            "labslinks",
            help="Generate EuropePMC LabLinks XML from Synapse table"
        )
        labslinks_parser.add_argument(
            "--table-id",
            required=True,
            help="Synapse table ID to query for results (e.g., syn66047339)"
        )
        labslinks_parser.add_argument(
            "--provider-id",
            required=True,
            type=int,
            help="EuropePMC LabLinks provider ID"
        )
        labslinks_parser.add_argument(
            "--output-dir",
            default="labslinks",
            help="Directory to write links.xml and profile.xml (default: labslinks)"
        )
        labslinks_parser.add_argument(
            "--provider-name",
            default="Sage Bionetworks",
            help="Provider display name (default: Sage Bionetworks)"
        )
        labslinks_parser.add_argument(
            "--provider-description",
            default="Data available via Synapse, the Sage Bionetworks data sharing platform",
            help="Provider description shown alongside links"
        )
        labslinks_parser.add_argument(
            "--provider-email",
            default="act@sagebase.org",
            help="Provider contact email (default: act@sagebase.org)"
        )
        labslinks_parser.add_argument(
            "--synapse-pat",
            help="Synapse Personal Access Token (can also use SERVICE_TOKEN or SYNAPSE_PAT env var)"
        )

    # Publication classification command
    if SYNAPSE_AVAILABLE:
        classify_parser = subparsers.add_parser(
            "classify",
            help="Label mined papers as primary, secondary, review or mention for each NF Data Portal study"
        )
        classify_parser.add_argument(
            "--table-id",
            default="syn66047339",
            help="Synapse table of mined mentions (default: syn66047339)"
        )
        classify_parser.add_argument(
            "--studies-view",
            default="syn52677631",
            help="Portal studies view (default: syn52677631)"
        )
        classify_parser.add_argument(
            "--publications-table",
            default="syn16857542",
            help="Portal publications table, used to flag already-tracked papers (default: syn16857542)"
        )
        classify_parser.add_argument(
            "--funder",
            action="append",
            help="Only keep studies funded by this agency (e.g. NTAP); repeat for several"
        )
        classify_parser.add_argument(
            "-o", "--output",
            default="classified_publications.csv",
            help="Output CSV, one row per (paper, study) (default: classified_publications.csv)"
        )
        classify_parser.add_argument(
            "--cache-dir",
            default=".cache/classify",
            help="Directory caching Europe PMC responses and Synapse project lookups (default: .cache/classify)"
        )
        classify_parser.add_argument(
            "--cited-by-output",
            default="cited_by.csv",
            help="CSV of all Cited By rows (secondary, review, mention) in the publications table format "
                 "(default: cited_by.csv)"
        )
        classify_parser.add_argument(
            "--primary-output",
            default="primary_publications.csv",
            help="CSV of all primary rows (high/medium confidence) in the publications table format "
                 "(default: primary_publications.csv)"
        )
        classify_parser.add_argument(
            "--cited-by-table",
            help="Synapse Cited By table to append new (paper, study) pairs to (omit to only write CSVs)"
        )
        classify_parser.add_argument(
            "--add-primary-publications",
            action="store_true",
            help="Append new primary (paper, study) pairs to --publications-table"
        )
        classify_parser.add_argument(
            "--create-cited-by-table-in",
            metavar="PROJECT_ID",
            help="Create a new Cited By table in this Synapse project, then fill it"
        )
        classify_parser.add_argument(
            "--review-issue-output",
            help="When rows were added or updated, or new low-confidence pairs were left out, write a "
                 "review issue body here (and its title to <path>.title)"
        )
        classify_parser.add_argument(
            "--reported-file",
            default="reported_low_confidence.json",
            help="JSON of left-out low-confidence pairs already reported in an issue, so each is reported "
                 "once (default: reported_low_confidence.json)"
        )
        classify_parser.add_argument(
            "--synapse-pat",
            help="Synapse Personal Access Token (can also use SERVICE_TOKEN or SYNAPSE_PAT env var)"
        )

    # Add pairs a person reviewed (e.g. from a review issue)
    if SYNAPSE_AVAILABLE:
        reviewed_parser = subparsers.add_parser(
            "add-reviewed",
            help="Add reviewed paper-study pairs (e.g. answers to a review issue) to the portal tables"
        )
        reviewed_parser.add_argument(
            "decisions",
            help="File with one decision per line, e.g. 'PMID:40585258 (syn51115812): primary' "
                 "('-' reads stdin). Relationships: primary, secondary, review, mention"
        )
        reviewed_parser.add_argument(
            "--evidence", required=True,
            help="Where the review happened (e.g. the issue comment URL); stored in the evidence column"
        )
        reviewed_parser.add_argument(
            "--dry-run", action="store_true",
            help="Show the rows that would be written without writing"
        )
        reviewed_parser.add_argument("--table-id", default="syn66047339",
                                     help="Synapse table of mined mentions (default: syn66047339)")
        reviewed_parser.add_argument("--studies-view", default="syn52677631",
                                     help="Portal studies view (default: syn52677631)")
        reviewed_parser.add_argument("--publications-table", default="syn16857542",
                                     help="Portal publications table for primary pairs (default: syn16857542)")
        reviewed_parser.add_argument("--cited-by-table", default="syn78484103",
                                     help="Portal Cited By table for other pairs (default: syn78484103)")
        reviewed_parser.add_argument("--cache-dir", default=".cache",
                                     help="Cache directory for API responses (default: .cache)")
        reviewed_parser.add_argument(
            "--synapse-pat",
            help="Synapse Personal Access Token (can also use SERVICE_TOKEN or SYNAPSE_PAT env var)"
        )

    # Search beyond the Europe PMC open-access download
    if SYNAPSE_AVAILABLE:
        search_parser = subparsers.add_parser(
            "search",
            help="Find and mine articles mentioning Synapse in NCBI PMC and Europe PMC full text"
        )
        search_parser.add_argument(
            "--table-id",
            default="syn66047339",
            help="Synapse results table to add new mentions to (default: syn66047339)"
        )
        search_parser.add_argument(
            "--query",
            action="append",
            help="Full-text query; repeat for several (default: Synapse links/DOIs, 'Synapse ID' phrasing and Sage portal names)"
        )
        search_parser.add_argument(
            "--recheck-existing",
            action="store_true",
            help="Also re-mine articles already in the table, adding Synapse IDs earlier mining missed"
        )
        search_parser.add_argument(
            "--max-articles",
            type=int,
            help="Maximum number of articles to mine (for testing)"
        )
        search_parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mine and write the CSV without uploading to Synapse"
        )
        search_parser.add_argument(
            "-o", "--output",
            default="search_results.csv",
            help="CSV of mined mentions (default: search_results.csv)"
        )
        search_parser.add_argument(
            "--cache-dir",
            default=".cache/search",
            help="Directory caching NCBI full text (default: .cache/search)"
        )
        search_parser.add_argument(
            "--synapse-pat",
            help="Synapse Personal Access Token (can also use SERVICE_TOKEN or SYNAPSE_PAT env var)"
        )

    args = parser.parse_args()

    # Set up logging
    setup_logging(args.verbose)
    logger = logging.getLogger("synapse_miner.cli")
    
    # Create miner instance
    miner = SynapseMiner(context_size=args.context_size)
    
    try:
        if args.command == "process":
            # Process local file
            if not args.file.exists():
                logger.error(f"File does not exist: {args.file}")
                sys.exit(1)
                
            logger.info(f"Processing file: {args.file}")
            findings = miner.process_file(str(args.file))
            
            if findings:
                # Save results
                import pandas as pd
                df = pd.DataFrame(findings)
                df.to_csv(args.output, index=False)
                logger.info(f"Saved {len(findings)} findings to {args.output}")
            else:
                logger.warning("No findings to save")
                
        elif args.command == "http":
            # Process HTTP files
            logger.info(f"Processing files from {args.url}")
            miner.process_http_files(
                base_url=args.url,
                output_path=str(args.output),
                start_from=args.start_from,
                max_files=args.max_files
            )
            
        elif args.command == "combine":
            # Combine results
            if not COMBINE_AVAILABLE:
                logger.error("Combine functionality requires pandas. Please install: pip install pandas")
                sys.exit(1)
            combine_results(args.output, args.directory, args.pattern)
            
        elif args.command == "workflow" and SYNAPSE_AVAILABLE:
            # Run automated workflow
            run_automated_workflow(args, logger)

        elif args.command == "ebisearch" and SYNAPSE_AVAILABLE:
            run_ebisearch_workflow(args, logger)

        elif args.command == "labslinks" and SYNAPSE_AVAILABLE:
            # Generate LabLinks XML from Synapse table
            run_labslinks_workflow(args, logger)

        elif args.command == "classify" and SYNAPSE_AVAILABLE:
            run_classify_workflow(args, logger)

        elif args.command == "search" and SYNAPSE_AVAILABLE:
            run_search_workflow(args, logger)

        elif args.command == "add-reviewed" and SYNAPSE_AVAILABLE:
            run_add_reviewed(args, logger)

        else:
            parser.print_help()
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

# Runs a file may fail in before it is no longer retried
MAX_FILE_ATTEMPTS = 4


def pmc_number(pmc_id):
    """PMC13710763 -> 13710763 (0 if it isn't a PMC ID)."""
    digits = str(pmc_id).upper().removeprefix("PMC")
    return int(digits) if digits.isdigit() else 0


def retry_list(failed_before, failed_now, missing, logger):
    """
    Files to retry next run, as {filename: runs it has failed in}.

    A file that keeps failing is dropped after MAX_FILE_ATTEMPTS runs (logged
    as an error, so it can be mined by hand), as is one that is no longer in
    the directory listing.
    """
    retry = {}
    for name in failed_now:
        count = failed_before.get(name, 0) + 1
        if count >= MAX_FILE_ATTEMPTS:
            logger.error(f"{name} failed in {count} runs; no longer retrying it. "
                         f"Mine it by hand with: synapse-miner http -u <url> -o <csv> --start-from {name} --max-files 1")
        else:
            retry[name] = count
    for name in missing:
        logger.error(f"{name} failed in an earlier run and is no longer in the listing; not retrying it")
    return retry


def run_automated_workflow(args, logger):
    """Run the automated weekly workflow with Synapse integration."""
    import os
    import glob
    
    try:
        # Initialize tracker
        tracker = ProcessingTracker(args.tracking_file)
        
        # Get last processed PMC ID
        last_pmc_id = tracker.get_last_processed_pmc_id()
        if last_pmc_id:
            logger.info(f"Resuming from last processed PMC ID: {last_pmc_id}")
        else:
            logger.info("No previous processing state found, starting from beginning")
        failed_before = tracker.get_failed_files()
        if failed_before:
            logger.info(f"Will retry {len(failed_before)} files that failed in earlier runs: "
                        f"{', '.join(sorted(failed_before))}")
        
        # Initialize Synapse uploader
        try:
            # Prioritize SERVICE_TOKEN, then fall back to SYNAPSE_PAT for backward compatibility
            token = args.synapse_pat or os.getenv('SERVICE_TOKEN') or os.getenv('SYNAPSE_PAT')
            synapse_uploader = SynapseUploader(pat=token)
        except Exception as e:
            logger.error(f"Failed to initialize Synapse client: {e}")
            logger.error("Please check your SERVICE_TOKEN or SYNAPSE_PAT environment variable or --synapse-pat argument")
            sys.exit(1)
        
        # Create miner instance  
        miner = SynapseMiner(context_size=args.context_size)
        
        # Determine start file based on last processed PMC ID
        start_from = None
        if last_pmc_id:
            # Start just past the last processed PMC ID so the last processed
            # file isn't reprocessed; core.py finds the next available batch
            start_from = tracker.get_resume_pmc_id()
            if not start_from:
                logger.error(f"Could not determine resume point from tracking file value: {last_pmc_id}")
                sys.exit(1)
            logger.info(f"Will start from PMC ID >= {start_from}")
            
        # Clean up any existing batch files from previous runs
        batch_pattern = f"{args.output}.*.csv"
        existing_batch_files = glob.glob(batch_pattern)
        for batch_file in existing_batch_files:
            try:
                os.remove(batch_file)
                logger.info(f"Removed old batch file: {batch_file}")
            except Exception as e:
                logger.warning(f"Could not remove old batch file {batch_file}: {e}")
        
        # Process files from HTTP server
        logger.info(f"Starting processing from URL: {args.url}")
        try:
            last_processed_file = miner.process_http_files(
                base_url=args.url,
                output_path=args.output,
                start_from=start_from,
                max_files=args.max_files,
                retry_files=sorted(failed_before)
            )
        except Exception as e:
            logger.error(f"Failed to process files from HTTP server: {e}")
            sys.exit(1)
        failed_files = retry_list(failed_before, miner.failed_files, miner.missing_retry_files, logger)
        
        if not last_processed_file:
            logger.warning("No new files were processed")
        
        # Find generated batch files
        batch_files = glob.glob(batch_pattern)
        batch_files.sort()  # Process in order
        
        if batch_files:
            logger.info(f"Found {len(batch_files)} batch files to upload")
            
            # Upload batch files and results to Synapse
            try:
                success = synapse_uploader.batch_upload_workflow(
                    batch_files=batch_files,
                    folder_id=args.folder_id,
                    table_id=args.table_id
                )
            except Exception as e:
                logger.error(f"Failed during Synapse upload workflow: {e}")
                sys.exit(1)
            
            if not success:
                logger.error("Workflow failed during Synapse upload")
                sys.exit(1)
        else:
            logger.info("No Synapse IDs found in processed files; nothing to upload")
        
        # Update tracking file with the end of the last processed file, even if
        # it had no findings, so the next run starts with the following file;
        # files that failed are kept in the tracking file and retried next run
        last_processed_pmc = tracker.extract_ending_pmc_id(last_processed_file) if last_processed_file else None
        if last_processed_file and not last_processed_pmc:
            logger.warning(f"Could not extract PMC ID from filename: {last_processed_file}")
        if last_processed_pmc and last_pmc_id and pmc_number(last_processed_pmc) <= pmc_number(last_pmc_id):
            # Safety net: the resume point only moves forward
            logger.error(f"Not moving the resume point back from {last_pmc_id} to {last_processed_pmc}")
            last_processed_pmc = None
        if last_processed_pmc or failed_files != failed_before:
            tracker.update_last_processed_pmc_id(last_processed_pmc, failed_files=failed_files)
        else:
            logger.info("Tracking file unchanged")
        if failed_files:
            logger.warning(f"{len(failed_files)} files failed and will be retried next run: "
                           f"{', '.join(sorted(failed_files))}")
        
        logger.info("Workflow completed successfully")
            
    except Exception as e:
        logger.error(f"Error in automated workflow: {e}")
        sys.exit(1)

def run_labslinks_workflow(args, logger):
    """Generate EuropePMC LabLinks XML from the Synapse results table."""
    import os
    from synapse_miner.utils.xml_generator import generate_profile_xml, generate_links_xml

    # Initialize Synapse uploader
    try:
        token = args.synapse_pat or os.getenv('SERVICE_TOKEN') or os.getenv('SYNAPSE_PAT')
        synapse_uploader = SynapseUploader(pat=token)
    except Exception as e:
        logger.error(f"Failed to initialize Synapse client: {e}")
        sys.exit(1)

    # Pull all (pmcid, synid) pairs from the table
    try:
        df = synapse_uploader.get_all_results(args.table_id)
    except Exception as e:
        logger.error(f"Failed to query Synapse table {args.table_id}: {e}")
        sys.exit(1)

    if df.empty:
        logger.warning("No data found in Synapse table — nothing to generate")
        return

    logger.info(f"Retrieved {len(df)} rows; generating LabLinks XML in '{args.output_dir}'")

    os.makedirs(args.output_dir, exist_ok=True)

    profile_path = os.path.join(args.output_dir, "profile.xml")
    generate_profile_xml(
        provider_id=args.provider_id,
        provider_name=args.provider_name,
        provider_description=args.provider_description,
        provider_email=args.provider_email,
        output_path=profile_path,
    )
    logger.info(f"Wrote {profile_path}")

    links_path = os.path.join(args.output_dir, "links.xml")
    generate_links_xml(
        df=df,
        provider_id=args.provider_id,
        output_path=links_path,
    )
    logger.info(f"Wrote {links_path}")
    logger.info("Done — upload both files to the EuropePMC LabsLink FTP site")


def run_ebisearch_workflow(args, logger):
    """Generate an EBI Search XML file from the Synapse results table."""
    import os
    from synapse_miner.utils.ebisearch_generator import generate_ebisearch_xml

    token = args.synapse_pat or os.getenv('SYNAPSE_PAT')
    try:
        synapse_uploader = SynapseUploader(pat=token)
    except Exception as e:
        logger.error(f"Failed to initialize Synapse client: {e}")
        import sys
        sys.exit(1)

    try:
        df = synapse_uploader.get_all_results(args.table_id)
    except Exception as e:
        logger.error(f"Failed to query Synapse table {args.table_id}: {e}")
        import sys
        sys.exit(1)

    if df.empty:
        logger.warning("No data found in Synapse table — nothing to generate")
        return

    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    cache_file = args.cache_file or os.path.join(output_dir, "entity_cache.json")
    output_path = os.path.join(output_dir, "ebisearch.xml")

    if args.refresh:
        logger.info("--refresh set: ignoring existing cache and re-fetching all metadata")

    generate_ebisearch_xml(
        syn=synapse_uploader.syn,
        df=df,
        output_path=output_path,
        cache_path=cache_file,
        refresh=args.refresh,
        db_name=args.db_name,
        db_description=args.db_description,
    )
    logger.info(f"Done — EBI Search XML written to {output_path}")


def run_add_reviewed(args, logger):
    """Add reviewed paper-study pairs to the portal tables."""
    import os
    from synapse_miner.reviewed import add_reviewed, describe, parse_decisions
    from synapse_miner.utils.crossref_client import CrossrefClient
    from synapse_miner.utils.europepmc_client import EuropePMCClient
    from synapse_miner.utils.study_resolver import load_studies

    text = sys.stdin.read() if args.decisions == "-" else open(args.decisions).read()
    decisions = parse_decisions(text)
    if not decisions:
        logger.error("No decisions found (expected lines like 'PMID:40585258 (syn51115812): primary')")
        sys.exit(1)
    for d in decisions:
        logger.info(f"Decision: PMID {d.pmid} {d.study_id} {d.relationship}")

    token = args.synapse_pat or os.getenv('SERVICE_TOKEN') or os.getenv('SYNAPSE_PAT')
    syn = SynapseUploader(pat=token).syn
    plan = add_reviewed(
        syn, decisions, args.evidence,
        epmc=EuropePMCClient(cache_dir=os.path.join(args.cache_dir, "europepmc")),
        studies=load_studies(syn, args.studies_view),
        publications_table=args.publications_table, cited_by_table=args.cited_by_table,
        mentions_table=args.table_id,
        crossref=CrossrefClient(cache_path=os.path.join(args.cache_dir, "crossref.json")),
        dry_run=args.dry_run,
    )
    print(describe(plan))
    logger.info("Dry run: nothing written" if args.dry_run else "Reviewed pairs written")


def run_classify_workflow(args, logger):
    """Classify mined papers by how they relate to NF Data Portal studies."""
    import os
    from synapse_miner.portal_tables import (
        CITED_BY_COLUMNS, PUBLICATION_COLUMNS, append_rows, apply_merges, build_cited_by, build_primary,
        create_cited_by_table, left_out_key, load_pair_keys, load_reported, load_table_rows,
        not_added, plan_writes, review_issue, save_reported, update_preprint_rows,
    )
    from synapse_miner.classify import classify_publications
    from synapse_miner.utils.europepmc_client import EuropePMCClient
    from synapse_miner.utils.crossref_client import CrossrefClient
    from synapse_miner.utils.ncbi_pmc_client import NCBIPMCClient
    from synapse_miner.utils.study_resolver import (
        StudyResolver, load_studies, load_tracked_publications,
    )

    token = args.synapse_pat or os.getenv('SERVICE_TOKEN') or os.getenv('SYNAPSE_PAT')
    try:
        syn = SynapseUploader(pat=token).syn
    except Exception as e:
        logger.error(f"Failed to initialize Synapse client: {e}")
        sys.exit(1)

    try:
        mentions = syn.tableQuery(f"SELECT pmcid, synid, context FROM {args.table_id}").asDataFrame()
        studies = load_studies(syn, args.studies_view)
        tracked = load_tracked_publications(syn, args.publications_table)
    except Exception as e:
        logger.error(f"Failed to load Synapse tables: {e}")
        sys.exit(1)

    resolver = StudyResolver(syn, studies, cache_path=os.path.join(args.cache_dir, "projects.json"))
    epmc = EuropePMCClient(cache_dir=os.path.join(args.cache_dir, "europepmc"))
    ncbi = NCBIPMCClient(cache_dir=os.path.join(args.cache_dir, "ncbi"))
    crossref = CrossrefClient(cache_path=os.path.join(args.cache_dir, "crossref.json"))
    results = classify_publications(mentions, studies, tracked, resolver, epmc,
                                    funders=args.funder, ncbi=ncbi, crossref=crossref)
    results.to_csv(args.output, index=False)
    logger.info(f"Wrote {len(results)} paper-study rows to {args.output}")

    primary = build_primary(results, studies)
    cited_by = build_cited_by(results, studies)
    primary.to_csv(args.primary_output, index=False)
    cited_by.to_csv(args.cited_by_output, index=False)
    logger.info(f"Wrote {len(primary)} primary rows to {args.primary_output} "
                f"and {len(cited_by)} Cited By rows to {args.cited_by_output}")

    cited_by_table = args.cited_by_table
    if not (cited_by_table or args.create_cited_by_table_in or args.add_primary_publications):
        return
    additions, merged, replaced, to_remove, failed = {}, {}, [], [], False
    existing = set()
    try:
        if args.create_cited_by_table_in:
            cited_by_table = create_cited_by_table(syn, args.create_cited_by_table_in)
        # Point existing preprint rows at their published versions first, so a
        # published version is not appended next to its own preprint
        for table_id, is_cited_by in ((args.publications_table, False), (cited_by_table, True)):
            if table_id and (is_cited_by or args.add_primary_publications):
                done, manual = update_preprint_rows(syn, table_id, epmc, cited_by=is_cited_by,
                                                    crossref=crossref)
                replaced += done
                to_remove += manual
        # A pair already in either table is never added again, to either table
        existing = load_pair_keys(syn, args.publications_table)
        if cited_by_table:
            existing |= load_pair_keys(syn, cited_by_table)
        # One row per paper: new studies for a paper already in a table are
        # added to its existing row rather than to a new row
        targets = []
        if args.add_primary_publications:
            targets.append((args.publications_table, primary, PUBLICATION_COLUMNS, False, "primary publication"))
        if cited_by_table:
            targets.append((cited_by_table, cited_by, CITED_BY_COLUMNS, True, "Cited By"))
        for table_id, rows, columns, match_relationship, label in targets:
            new_rows, merges = plan_writes(rows, load_table_rows(syn, table_id), existing, match_relationship)
            apply_merges(syn, table_id, merges, f"classify links {len(merges)} existing {label} rows to more studies")
            merged[table_id] = merges
            append_rows(syn, table_id, new_rows, columns, f"classify adds {len(new_rows)} {label} rows")
            additions[table_id] = new_rows
    except Exception as e:
        logger.error(f"Failed to update the portal publication tables: {e}")
        failed = True

    # Changes made before a failure still get a review issue. Left-out pairs
    # are listed once, when first left out, not on every run.
    left_out = not_added(results, existing)
    left_out_keys = {left_out_key(row) for row in left_out.itertuples(index=False)}
    reported = load_reported(args.reported_file)
    new_left_out = left_out[[left_out_key(row) not in reported for row in left_out.itertuples(index=False)]]
    issue = review_issue(additions, replaced, to_remove, new_left_out, left_out_total=len(left_out), merged=merged)
    if issue and args.review_issue_output:
        title, body = issue
        with open(args.review_issue_output, "w") as f:
            f.write(body)
        with open(f"{args.review_issue_output}.title", "w") as f:
            f.write(title)
        save_reported(args.reported_file, reported | left_out_keys)
        logger.info(f"Wrote review issue to {args.review_issue_output}")
    elif not issue:
        logger.info("Nothing added, replaced or newly left out; no review issue needed")
    if failed:
        sys.exit(1)


def run_search_workflow(args, logger):
    """Find and mine articles mentioning Synapse beyond the open-access download."""
    import os
    from synapse_miner.search import DEFAULT_QUERIES, search_and_mine
    from synapse_miner.utils.europepmc_client import EuropePMCClient
    from synapse_miner.utils.ncbi_pmc_client import NCBIPMCClient

    token = args.synapse_pat or os.getenv('SERVICE_TOKEN') or os.getenv('SYNAPSE_PAT')
    try:
        uploader = SynapseUploader(pat=token)
        existing = uploader.get_all_results(args.table_id)
    except Exception as e:
        logger.error(f"Failed to read Synapse table {args.table_id}: {e}")
        sys.exit(1)
    existing_pmcids = set(existing["pmcid"].astype(str).str.replace("pmc:", "", regex=False))

    ncbi = NCBIPMCClient(cache_dir=os.path.join(args.cache_dir, "ncbi"))
    epmc = EuropePMCClient()
    try:
        mentions, without_pmcid = search_and_mine(
            args.query or DEFAULT_QUERIES, existing_pmcids, ncbi, epmc,
            recheck_existing=args.recheck_existing, max_articles=args.max_articles)
    except Exception as e:
        logger.error(f"Search failed: {e}")
        sys.exit(1)

    mentions.to_csv(args.output, index=False)
    logger.info(f"Wrote {len(mentions)} mentions to {args.output}")
    if without_pmcid:
        logger.info(f"{len(without_pmcid)} matching records have no PMCID and were not mined, e.g. "
                    + ", ".join(f"{r['source']}:{r['id']}" for r in without_pmcid[:5]))

    if args.dry_run:
        logger.info("--dry-run set: not uploading to Synapse")
        return
    try:
        uploader.upload_new_pairs_to_table(mentions, args.table_id)
    except Exception as e:
        logger.error(f"Failed to upload to Synapse table {args.table_id}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()