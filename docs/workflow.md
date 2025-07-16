# Weekly PMC Mining Workflow

This document describes the automated weekly workflow for mining Synapse IDs from Europe PMC's Open Access subset.

## Overview

The workflow automatically:
1. Tracks the last processed PMC ID batch
2. Downloads and processes new XML files from Europe PMC 
3. Uploads individual batch results to Synapse folder
4. Adds new results to a Synapse table (with deduplication)
5. Updates the tracking file for the next run

## Setup

### Required Secrets

Add these secrets to your GitHub repository settings:

- `SYNAPSE_PAT`: Your Synapse Personal Access Token (get from https://www.synapse.org/#!PersonalAccessTokens:)

### Configuration

The workflow is configured to:
- **Schedule**: Run every Monday at 10:00 PM UTC (to avoid Synapse stack migration conflicts)
- **Synapse Folder**: syn66046437 (for individual batch CSV files)
- **Synapse Table**: syn66047339 (for aggregated results)
- **Tracking File**: `last_processed_pmc.json` (stored in the repository)

## Manual Execution

### Via GitHub Actions UI

1. Go to the "Actions" tab in your repository
2. Select "Weekly PMC Mining Workflow"
3. Click "Run workflow"
4. Optionally specify `max_files` for testing (e.g., "2" to process only 2 files)

### Via Command Line

```bash
# Install dependencies
pip install -r requirements.txt
pip install -e .

# Run workflow (requires Synapse credentials)
export SYNAPSE_PAT="your_personal_access_token"

synapse-miner workflow \
  --folder-id syn66046437 \
  --table-id syn66047339 \
  --tracking-file last_processed_pmc.json \
  --output workflow_results.csv \
  --verbose \
  --max-files 2  # Optional: limit for testing
```

## Workflow Details

### PMC ID Tracking

The workflow uses `last_processed_pmc.json` to track progress:

```json
{
  "last_processed_pmc_id": "PMC11890001",
  "updated_at": "2024-06-26T14:30:00.123456",
  "description": "This file tracks the last processed PMC ID for the weekly mining workflow."
}
```

- **Starting PMC ID**: Extracted from filename like `PMC11890001_PMC11900000.xml.gz`
- **Resumption Logic**: Next run starts from batches with PMC ID ≥ last processed ID
- **Overlap Handling**: Deduplication ensures no duplicate PMC IDs in the table

### File Processing

1. **Download**: XML files from `https://europepmc.org/ftp/oa/`
2. **Processing**: Extract Synapse IDs with context from each article
3. **Batch Files**: Individual CSV files for each XML file processed
4. **Main Results**: Aggregated CSV with all findings

### Synapse Integration

#### Individual Batch Upload
- Location: Synapse folder syn66046437
- Format: CSV files named `workflow_results.csv.{xml_filename}.csv`
- Content: PMC ID, Synapse ID, context for each finding

#### Table Upload
- Location: Synapse table syn66047339
- Deduplication: Checks existing PMC IDs to avoid duplicates
- Columns: `pmcid` (with bioregistry prefix, e.g., "pmc:PMC1234567"), `synid`, `context`

### Error Handling

- **Download Failures**: Automatic retries with exponential backoff
- **Processing Errors**: Logged but don't stop the workflow
- **Upload Failures**: Workflow fails if Synapse upload fails
- **Tracking Updates**: Only updated after successful processing

## Monitoring

### GitHub Actions Artifacts

Each run uploads artifacts containing:
- `workflow_results.csv`: Main results file
- `workflow_results.csv.*.csv`: Individual batch files
- `last_processed_pmc.json`: Updated tracking file
- Logs from the workflow execution

### Synapse Monitoring

- Check folder syn66046437 for new batch files
- Check table syn66047339 for new rows
- Monitor table growth and PMC ID coverage

## Troubleshooting

### Common Issues

1. **Synapse Authentication Failed**
   - Verify `SYNAPSE_PAT` secret is set correctly
   - Check if Personal Access Token has required permissions

2. **No New Files Processed**
   - Check if tracking file correctly reflects last processed batch
   - Verify Europe PMC server has new files available

3. **Duplicate PMC IDs**
   - Deduplication should prevent this automatically
   - Check table query logic if duplicates appear

4. **Workflow Timeout**
   - GitHub Actions have 6-hour limit
   - Consider using `max_files` parameter for large backlogs

### Manual Recovery

If the workflow fails partway through:

1. Check the artifacts for partial results
2. Manually update `last_processed_pmc.json` if needed
3. Re-run the workflow

### Testing

Test with limited files:

```bash
synapse-miner workflow \
  --folder-id syn66046437 \
  --table-id syn66047339 \
  --max-files 1 \
  --verbose
```

## File Structure

```
.
├── .github/
│   └── workflows/
│       └── weekly-mining.yml          # GitHub Actions workflow
├── synapse_miner/
│   ├── utils/
│   │   ├── tracking.py                # PMC ID tracking
│   │   └── synapse_integration.py     # Synapse upload utilities
│   └── cli.py                         # Extended CLI with workflow command
├── last_processed_pmc.json            # Tracking file (auto-updated)
└── requirements.txt                   # Updated with synapseclient
```