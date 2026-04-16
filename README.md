# Synapse ID Miner

A Python package that mines Synapse IDs from Europe PMC's Open Access article corpus, uploads findings to a Synapse table, and generates [EuropePMC LabsLink](https://europepmc.org/LabsLink) XML so that dataset links appear directly on article pages.

## How it works

1. **Mine** — Downloads bulk XML from the Europe PMC Open Access FTP, scans each article for Synapse IDs (`syn` followed by 7–12 digits), and captures surrounding context.
2. **Upload** — Deduplicates against the existing Synapse table and appends new findings.
3. **Link** — Generates a LabsLink `links.xml` + `profile.xml` from the full table, ready to submit to EuropePMC so links back to Synapse appear on article pages.

Steps 1–2 run automatically every Monday; step 3 runs every Tuesday (after new data has been uploaded).

## Installation

```bash
pip install git+https://github.com/nf-osi/synapse-miner.git
```

## CLI reference

### `synapse-miner http` — mine from Europe PMC

Download and process XML files from the Europe PMC Open Access subset.

```bash
synapse-miner http \
  -u https://europepmc.org/ftp/oa/ \
  -o results.csv \
  [-s PMC3000001_PMC3010000.xml.gz]  # start from a specific batch
  [-m 2]                              # limit number of files (useful for testing)
```

### `synapse-miner process` — mine a local file

```bash
synapse-miner process path/to/articles.xml.gz -o results.csv
```

### `synapse-miner combine` — merge batch CSVs

After processing multiple files, combine the per-file batch CSVs into one.

```bash
synapse-miner combine -o combined_results.csv [-d ./results] [-p "results.csv.*.csv"]
```

### `synapse-miner workflow` — automated mining + upload

Runs the full weekly pipeline: mines new articles, uploads batch files and results to Synapse, and updates the tracking file.

```bash
export SYNAPSE_PAT="your_token"

synapse-miner workflow \
  --folder-id syn66046437 \
  --table-id syn66047339 \
  --tracking-file last_processed_pmc.json \
  --output workflow_results.csv \
  [--max-files 2]   # limit for testing
```

### `synapse-miner labslinks` — generate EuropePMC LabsLink XML

Queries the Synapse results table and writes `links.xml` and `profile.xml` for submission to the EuropePMC LabsLink FTP.

```bash
export SYNAPSE_PAT="your_token"

synapse-miner labslinks \
  --table-id syn66047339 \
  --provider-id <EUROPEPMC_PROVIDER_ID> \
  --output-dir labslinks/
```

Optional overrides (defaults shown):
- `--provider-name "Sage Bionetworks"`
- `--provider-description "Data available via Synapse, the Sage Bionetworks data sharing platform"`
- `--provider-email "act@sagebase.org"`

Upload both output files to the EuropePMC LabsLink FTP once generated.

## Output

| File | Description |
|------|-------------|
| `results.csv` | All findings from a run |
| `results.csv.{batch}.csv` | Per-file batch results |
| `last_processed_pmc.json` | Tracks the last processed PMC batch for resumption |
| `labslinks/links.xml` | EuropePMC LabsLink links file |
| `labslinks/profile.xml` | EuropePMC LabsLink provider profile |

Each row in the results CSVs contains:
- `pmcid` — PubMed Central ID with bioregistry prefix (e.g. `pmc:PMC1234567`)
- `synid` — Synapse ID found in the article (e.g. `syn23630203`)
- `context` — ~25 characters of surrounding text

Multiple rows per article are expected and intentional: a paper can reference the same Synapse dataset in several sentences, and each mention is recorded separately with its own context.

## Synapse resources

| Resource | ID |
|----------|----|
| Batch file folder | [syn66046437](https://www.synapse.org/Synapse/syn66046437) |
| Results table | [syn66047339](https://www.synapse.org/Synapse/syn66047339) |

## Automated workflows

### Weekly mining (`weekly-mining.yml`)

Runs every **Monday at 22:00 UTC**.

- Resumes from `last_processed_pmc.json` so only new batches are processed
- Uploads batch CSVs to the Synapse folder and new rows to the results table
- Commits the updated tracking file back to the repository

Can be triggered manually from the Actions tab with an optional `max_files` parameter for testing.

### LabsLink generation (`generate-labslinks.yml`)

Runs every **Tuesday at 10:00 UTC** (~12 hours after mining).

- Queries the full Synapse results table
- Writes deduplicated `labslinks/links.xml` and `labslinks/profile.xml`
- Commits the updated files to the repository and uploads them as a workflow artifact

Can be triggered manually from the Actions tab with a `provider_id` input.

## Repository secrets and variables

| Name | Type | Required by | Description |
|------|------|-------------|-------------|
| `SYNAPSE_PAT` | Secret | both workflows | Synapse Personal Access Token with read/write access to syn66046437 and syn66047339 |
| `LABSLINKS_PROVIDER_ID` | Variable | `generate-labslinks.yml` | EuropePMC LabsLink provider ID assigned during registration |
