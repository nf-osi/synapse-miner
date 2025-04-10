# Synapse ID Miner Usage Guide

This guide provides detailed instructions for using the Synapse ID Miner to extract Synapse IDs from Europe PMC's Open Access subset.

## Basic Usage

The most basic command to process files from Europe PMC:

```bash
synapse-miner http -u https://europepmc.org/ftp/oa/ -o results.csv
```

This will:
1. Download and process all XML files from the Europe PMC Open Access subset
2. Save results to `results.csv`
3. Show progress during download and processing

## Advanced Options

### Starting from a Specific File

To start processing from a specific file:

```bash
synapse-miner http -u https://europepmc.org/ftp/oa/ -o results.csv -s PMC3000001_PMC3010000.xml.gz
```

This is useful for:
- Resuming after an interruption
- Processing a specific range of articles
- Testing with a known file

### Limiting the Number of Files

To process only a certain number of files:

```bash
synapse-miner http -u https://europepmc.org/ftp/oa/ -o results.csv -m 5
```

This will:
1. Process only the first 5 files
2. Save results to `results.csv`
3. Create individual CSV files for each processed file

### Combining Options

You can combine options to process a specific number of files starting from a particular point:

```bash
synapse-miner http -u https://europepmc.org/ftp/oa/ -o results.csv -s PMC3000001_PMC3010000.xml.gz -m 2
```

## Output Files

The miner generates two types of output files:

1. Main results file (`results.csv`):
   - Contains all findings across all processed files
   - Updated after each file is processed
   - Format: CSV with columns `pmcid`, `synid`, `context`

2. Batch files (`results.csv.{filename}.csv`):
   - Created for each processed XML file
   - Contains findings from that specific file
   - Useful for tracking progress and debugging

## Progress Tracking

The miner provides real-time progress information:

1. Download Progress:
   - Shows percentage complete
   - Displays current file being downloaded
   - Updates in real-time

2. Processing Progress:
   - Shows number of articles processed
   - Displays number of Synapse IDs found
   - Updates after each article

## Error Handling

The miner includes several error handling features:

1. Download Retries:
   - Automatically retries failed downloads
   - Maximum of 3 retries with 5-second delays
   - Logs retry attempts

2. File Cleanup:
   - Removes downloaded files after processing
   - Prevents disk space issues
   - Logs cleanup operations

3. Incremental Saving:
   - Saves results after each file
   - Prevents data loss on crashes
   - Maintains both batch and main results files

## Python API

You can also use the miner programmatically:

```python
from synapse_miner import SynapseMiner

# Initialize miner
miner = SynapseMiner()

# Process files with all options
miner.process_http_files(
    base_url="https://europepmc.org/ftp/oa/",
    output_path="results.csv",
    start_from="PMC3000001_PMC3010000.xml.gz",
    max_files=2
)
```

## Troubleshooting

Common issues and solutions:

1. **Download Failures**:
   - Check internet connection
   - Verify the base URL is correct
   - Wait for retries to complete

2. **Memory Issues**:
   - Process fewer files at once
   - Use the `-m` option to limit files
   - Ensure sufficient disk space

3. **File Not Found**:
   - Verify the start file exists
   - Check the filename format
   - Try without the start file option

4. **CSV Format Issues**:
   - Check for special characters in context
   - Verify CSV reader settings
   - Try opening with different tools 