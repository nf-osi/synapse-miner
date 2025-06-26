# Example: Testing the Workflow Locally

This example shows how to test the workflow functionality locally.

## Prerequisites

1. Install dependencies:
```bash
pip install -r requirements.txt
pip install -e .
```

2. Set up Synapse credentials (optional for testing):
```bash
export SYNAPSE_PAT="your_personal_access_token"
```

## Test Tracking Functionality

```python
from synapse_miner.utils import ProcessingTracker

# Create a tracker
tracker = ProcessingTracker("test_tracking.json")

# Test PMC ID extraction
filename = "PMC11890001_PMC11900000.xml.gz"
pmc_id = tracker.extract_starting_pmc_id(filename)
print(f"Extracted PMC ID: {pmc_id}")

# Update tracking
tracker.update_last_processed_pmc_id(pmc_id)

# Read back
last_id = tracker.get_last_processed_pmc_id()
print(f"Last processed: {last_id}")
```

## Test CLI (without Synapse)

```bash
# Test basic HTTP processing (downloads small amount)
synapse-miner http \
  -u https://europepmc.org/ftp/oa/ \
  -o test_results.csv \
  -m 1 \
  --verbose

# Check generated files
ls -la test_results.csv*
```

## Test Workflow Command (dry-run style)

Note: This requires valid Synapse credentials but you can test the CLI parsing:

```bash
# Test workflow command parsing
synapse-miner workflow --help

# Test with mock credentials (will fail at Synapse login but shows parsing works)
synapse-miner workflow \
  --folder-id syn66046437 \
  --table-id syn66047339 \
  --max-files 1 \
  --synapse-pat test \
  --verbose
```

## Test GitHub Actions Locally

If you have `act` installed, you can test the GitHub Actions workflow locally:

```bash
# Install act: https://github.com/nektos/act

# Create a .secrets file with:
# SYNAPSE_PAT=your_personal_access_token

# Run the workflow
act workflow_dispatch --secret-file .secrets
```

## Expected Behavior

1. **Tracking**: Creates/updates `last_processed_pmc.json`
2. **Processing**: Downloads XML files and creates batch CSV files
3. **Synapse Upload**: Uploads batch files to folder and aggregated data to table
4. **Deduplication**: Checks existing PMC IDs to avoid duplicates
5. **Progress Update**: Updates tracking file with last processed PMC ID

## Cleanup

```bash
# Remove test files
rm -f test_*.csv test_*.json
rm -f workflow_results.csv*
```