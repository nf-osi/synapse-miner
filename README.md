# Synapse ID Miner

A Python package that mines Synapse IDs from scientific articles (Europe PMC's Open Access corpus plus NCBI PMC full text, including NIH author manuscripts), uploads findings to a Synapse table, labels how each paper relates to the NF Data Portal studies it cites, and generates [EuropePMC LabsLink](https://europepmc.org/LabsLink) XML so that dataset links appear directly on article pages.

## How it works

1. **Mine** — Downloads bulk XML from the Europe PMC Open Access FTP, scans each article for Synapse IDs (`syn` followed by 7–12 digits), and captures surrounding context.
2. **Upload** — Deduplicates against the existing Synapse table and appends new findings.
3. **Search** — Finds articles outside the Open Access download (e.g. NIH author manuscripts) by searching NCBI PMC and Europe PMC full text for Synapse links, DOIs and portal names, mines their NCBI full text, and appends new (article, Synapse ID) pairs.
4. **Classify** — Labels each paper as primary (generated the data) or secondary (reused it) for every NF Data Portal study it cites.
5. **Link** — Generates a LabsLink `links.xml` + `profile.xml` from the full table, ready to submit to EuropePMC so links back to Synapse appear on article pages.

Steps 1–4 run automatically every Monday; step 5 runs every Tuesday (after new data has been uploaded).

## Installation

```bash
pip install git+https://github.com/nf-osi/synapse-miner.git
```

## CLI reference

### `synapse-miner http` — mine from Europe PMC

Download and process XML files from the Europe PMC Open Access subset.

```bash
synapse-miner http \
  -u https://ftp.ebi.ac.uk/pub/databases/pmc/oa/ \
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

### `synapse-miner search` — find articles beyond the Open Access download

The weekly download only covers Europe PMC's Open Access subset. `search` queries NCBI PMC and Europe PMC full text, fetches each match's full text from NCBI PMC (which also serves NIH author manuscripts), mines it with the same parser, and appends rows whose (article, Synapse ID) pair is not already in the table.

```bash
export SYNAPSE_PAT="your_token"

synapse-miner search \
  --table-id syn66047339 \
  [--recheck-existing]   # also re-mine articles already in the table
  [--dry-run]            # write search_results.csv without uploading
```

Default queries (override with repeated `--query`):
- `"synapse.org" OR "10.7303"` — Synapse links and DOIs
- `"Synapse ID" OR "SynID" OR ...` — IDs cited without a link
- `"NF Data Portal" OR "AD Knowledge Portal" OR "Sage Bionetworks"` — portal names

Search complements the weekly download rather than replacing it: articles that give a bare `syn` ID with none of these phrases are only found by the download. Matches without a PMCID (mostly preprints) are logged but not mined. Set `NCBI_API_KEY` to raise NCBI's rate limit.

### `synapse-miner classify` — label papers as primary or secondary use

Maps each mined Synapse ID to its NF Data Portal study ([syn52677631](https://www.synapse.org/Synapse/syn52677631)), reads each paper's full text from Europe PMC, and labels every (paper, study) pair from the wording around the ID:

| Relationship | Meaning | Typical wording |
|--------------|---------|-----------------|
| `primary` | The paper generated or deposited the study's data | "have been deposited in", "generated in this study", data descriptor or data-availability statement by a study lead |
| `secondary` | The paper reused data already on the portal | "downloaded from", "imported from", "accessed on <date>", "provided by" |
| `review` | Review article citing the study | Europe PMC publication type |
| `mention` | Cites the study without depositing or reusing data | Bare ID or wiki link, no study lead among authors |
| `unclear` | Not enough to tell; needs a human look | e.g. no full text, or only a bare ID with a study lead as author |

A study lead among the authors only decides weak cases. Funders count a paper as secondary when it reanalyses data already on the portal, even when a study lead is a co-author.

```bash
export SYNAPSE_PAT="your_token"

synapse-miner classify \
  -o classified_publications.csv \
  [--funder NTAP]        # repeat for several funders
```

Each output row is one (paper, study) pair with the label, a confidence (`high`/`medium`/`low`), the reason, the supporting sentences (`evidence`), study leads found among the authors, and whether the paper is already in the portal publications table ([syn16857542](https://www.synapse.org/Synapse/syn16857542)) and linked to that study. Europe PMC responses and Synapse lookups are cached in `--cache-dir` (default `.cache/classify`), so reruns only fetch new papers.

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
- Runs `search` for articles outside the Open Access download, adding new rows to the results table
- Runs `classify` and attaches `classified_publications.csv` to the run's artifacts

Can be triggered manually from the Actions tab with an optional `max_files` parameter for testing, and `recheck_existing` to re-mine articles already in the table (a one-off backfill of IDs older parser versions missed).

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
