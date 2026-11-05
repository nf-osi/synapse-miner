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

#### Adding papers to the portal tables

`classify` turns labelled pairs into rows in the portal publications table's format, one row per (paper, study):

| Relationship | Table | Rows added |
|--------------|-------|------------|
| `primary` | Publications ([syn16857542](https://www.synapse.org/Synapse/syn16857542)) | `high` and `medium` confidence |
| `secondary`, `review`, `mention` | Cited By ([syn78484103](https://www.synapse.org/Synapse/syn78484103)) | all; `publicationType` holds the relationship |
| `unclear` | neither | left for a human look (in `classified_publications.csv`) |

A paper that is primary for one study and secondary for another gets a row in each table, each under its own study. Both tables share the publications table's columns, so study pages show them with the same publication cards filtered on `studyId`; Cited By adds `pmcid`, `isPreprint`, `confidence`, `citedSynapseIds` and `evidence` at the end.

Rows are only ever **appended**: a (paper, study) pair already in either table (matched by PMID or DOI) is skipped, so curated rows and hand edits are never changed and nothing is deleted.

```bash
# One-time: create the Cited By table in a project
synapse-miner classify --create-cited-by-table-in <PROJECT_ID>

# Append new pairs to both tables and write a review issue body if anything was added
synapse-miner classify \
  --cited-by-table syn78484103 \
  --add-primary-publications \
  --review-issue-output review_issue.md
```

**Preprints and published versions:** PubMed links a preprint to its published version ("Update in"). When a classified preprint has one, the row uses the published paper's PMID, DOI, title, journal, year and authors, keeping the label read from the preprint; if the published version is already classified for the same study, the preprint row is dropped. Rows already in either table whose PMID is a preprint with a published version are updated in place to the published version (study columns untouched, snapshotted before and after). If the table already has the published version for the same study, the preprint row is listed in the review issue for removal by hand, since automation never deletes rows.

**Review issue:** with `--review-issue-output`, `classify` writes an issue when a run adds or updates rows, or leaves out low-confidence pairs (`unclear`, and `primary` at `low` confidence) that have not been reported before. It lists the additions (lowest confidence first), the preprints it replaced, preprint rows to remove by hand, and, in a collapsible list, the newly left-out pairs with the total still left out. Each left-out pair is reported once: reported pairs are kept in `reported_low_confidence.json` (`--reported-file`), which the weekly workflow commits after opening the issue. A run with nothing to report writes no issue.

Without `--cited-by-table` or `--add-primary-publications`, `classify` only writes CSVs (`classified_publications.csv`, `primary_publications.csv`, `cited_by.csv`).

#### Adding reviewed pairs (`synapse-miner add-reviewed`)

The review issue lists low-confidence pairs the workflow left out. To add the ones that belong, reply on the issue with one line per pair:

```
PMID:40585258 (liquid biopsy, syn51115812): primary
PMID:40744913 (FGFR glioma, syn5698493): secondary
```

The relationship is `primary`, `secondary`, `review` or `mention`; anything else on the line is ignored. To fix an existing row instead of adding one (e.g. a placeholder holding a dataset DOI), end the line with `replaces PMID:<PMID>`, naming the paper the study's row holds now: `PMID:36283200 (syn74287631): primary, replaces PMID:34711849`. For a placeholder row with no PMID, use its DOI instead: `replaces DOI:10.7937/TCIA.9YTJ-5Q73`. The row's paper columns (DOI, journal, title, year, PMID, authors, type) are overwritten, `fundingAgency` is set to its studies' funders (the column defaults to NTAP, CTF, GFF, so hand-entered rows often hold that by mistake), and its study, disease and manifestation columns are kept. Exactly one row linked to that study must hold the named paper. Rerunning the same line on the same row refreshes it. Then run the **Add reviewed publications** workflow (Actions tab, `add-reviewed.yml`) with the reply's link. Tick `dry_run` first to see the rows without writing. The workflow replies on the issue with what it added.

Or run it locally (needs write access to both tables):

```bash
synapse-miner add-reviewed decisions.txt \
  --evidence "Reviewed in https://github.com/nf-osi/synapse-miner/issues/21#issuecomment-6644387488" \
  --dry-run   # drop to write
```

Rows are built the same way as the workflow's:
- metadata comes from Europe PMC, journal names from Crossref, and study details from the studies view;
- `citedSynapseIds` comes from the mined-mentions table;
- primary pairs go to the publications table and the rest to Cited By, one row per paper;
- a study already linked to the paper in either table is skipped, so rerunning adds nothing;
- `confidence` is `reviewed` and `evidence` holds the review link;
- every write is snapshotted.

A preprint is added as the preprint; the weekly run swaps in its published version once PubMed links one.

#### Fixing funders (`synapse-miner fix-funders`)

syn16857542's `fundingAgency` column defaults to `[NTAP, CTF, GFF]`, so a row entered without funders gets those three. To set rows' funders to their studies' funders (from the studies view):

```bash
synapse-miner fix-funders 422 423 424 --dry-run   # drop --dry-run to write; --table syn78484103 for Cited By
```

Rows with no study, or whose studies have no funders, are left alone; the write is snapshotted.

#### Synapse safety

Every automated write to a Synapse table (the mentions table, the publications table and Cited By) is bracketed by snapshot versions, as in nf-research-tools-schema's Synapse safety rules. Snapshot comments carry the date, what was written and the workflow run link, e.g. `2026-11-10 before: classify adds 3 Cited By rows https://github.com/nf-osi/synapse-miner/actions/runs/123`. A write does not go ahead if its "before" snapshot fails. To undo a run, query the table at the "before" version (`SELECT * FROM syn78484103.<version>`). Nothing in this package deletes table rows.

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
| Cited By table | [syn78484103](https://www.synapse.org/Synapse/syn78484103) |

## Automated workflows

### Weekly mining (`weekly-mining.yml`)

Runs every **Monday at 22:00 UTC**.

- Resumes from `last_processed_pmc.json` so only new batches are processed
- Uploads batch CSVs to the Synapse folder and new rows to the results table
- Commits the updated tracking file back to the repository
- Runs `search` for articles outside the Open Access download, adding new rows to the results table
- Runs `classify`, appends new primary pairs to the publications table and new secondary/review/mention pairs to Cited By, and attaches the CSVs to the run's artifacts
- Opens a `publication-review` issue when rows were added or updated, or new low-confidence pairs were left out, and commits `reported_low_confidence.json`; no issue when there is nothing to report

### Add reviewed publications (`add-reviewed.yml`)

Run by hand with the link to a reply on a review issue. It adds the pairs the reply lists (see [Adding reviewed pairs](#adding-reviewed-pairs-synapse-miner-add-reviewed)) and replies on the issue with what it added.

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
