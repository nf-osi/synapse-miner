---
name: add-reviewed-publications
description: Add publication-study pairs a person has reviewed (answers on a synapse-miner publication-review issue) to the NF Data Portal tables syn16857542 (primary) and syn78484103 (Cited By). Use when someone has decided pairs from a review issue and wants them added, or asks how to add a paper the workflow left out.
---

# Add reviewed publications

The weekly workflow leaves low-confidence pairs out of the portal tables and lists them in a `publication-review` issue. A reviewer replies with one decision per line:

```
PMID:40585258 (liquid biopsy, syn51115812): primary
PMID:40744913 (FGFR glioma, syn5698493): secondary
```

Relationships: `primary` goes to the publications table (syn16857542); `secondary`, `review` and `mention` go to Cited By (syn78484103). A new Cited By paper is also listed in the publications table without study links (`studyId`/`studyName` empty, `fundingAgency` "Not Applicable (External Study)"); the write step does this itself (`synapse-miner copy-cited-by` does it on its own).

To **fix an existing row** rather than add one, end the line with `replaces PMID:<PMID>` naming the paper the study's row holds now, e.g. `PMID:36283200 (syn74287631): primary, replaces PMID:34711849`. Placeholder rows (no PMID, a dataset DOI, the study name as title, or author "Unknown") are named by their DOI: `replaces DOI:<doi>`. See what a study's rows hold with `SELECT * FROM syn16857542 WHERE studyId HAS ('<study>')`. The paper columns change and `fundingAgency` is reset to the study's funders. syn16857542's `fundingAgency` column defaults to `[NTAP, CTF, GFF]`, so a hand-entered row with exactly those funders is suspect. Exactly one row linked to the study must hold that paper, and rerunning the same line refreshes it.

## Steps

1. **Get the decisions.** Read the reply with `gh api repos/nf-osi/synapse-miner/issues/comments/<id> --jq .body` and save it to a scratch file. Confirm every line parsed. The command logs one `Decision:` line per pair, and a line it can't parse is silently skipped.
2. **Dry run**, then look at every row before writing:
   ```bash
   synapse-miner add-reviewed decisions.txt --evidence "Reviewed in <comment URL>" --dry-run
   ```
   Check:
   - **Preprints.** The journal is Research Square, bioRxiv or similar, or the DOI starts `10.21203` or `10.1101`. Search Europe PMC for a published version by title. If one exists, ask the reviewer whether to add that instead, using its PMID.
   - **Authors.** Preprint records often list only the corresponding author. Say so, since no source has the full list.
   - **Merges.** Expect "existing rows linked to more studies" when the paper is already in the table for another study. That is expected: one row per paper.
3. **Write.** Do this in either of two ways:
   - The **Add reviewed publications** workflow (`add-reviewed.yml`) with the comment link. It runs as the service account and replies on the issue.
   - The same command without `--dry-run`, which needs UPDATE on both tables.

   Every write is snapshotted before and after (`synapse_safety.py`). Rerunning is a no-op because existing paper-study pairs are skipped.
4. **Report on the issue.** List each row added (table, PMID, study, relationship) and the snapshot versions, and anything left for a person, such as a preprint with a single author. Close the issue if every pair is handled.

## Funders

To reset other rows' funders to their studies' funders, use `synapse-miner fix-funders <ROW_ID>... --dry-run`, then rerun without `--dry-run`. This fixes rows that hold the column default. Find candidates by comparing each row's `fundingAgency` with its studies' funders in syn52694652.

## Don't

- Don't write rows by hand with `syn.store`. Use the command so de-duplication, `studyName` IDs, DOI links and snapshots are applied.
- Don't delete rows. Automation never deletes; list anything to remove on the issue for a curator.
