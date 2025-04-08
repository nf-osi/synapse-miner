# Usage Guide

This guide explains how to use the Synapse ID Mining package to extract Synapse IDs from scientific articles.

## Basic Usage

### From the Command Line

The Synapse ID Mining package provides a command-line interface (CLI) for convenient usage:

```bash
# Process a single PDF file
synapse-miner path/to/article.pdf

# Process a directory containing multiple articles
synapse-miner path/to/articles/

# Save results to a specific file
synapse-miner path/to/articles/ -o results.csv

# Save results in JSON format
synapse-miner path/to/articles/ -o results.json -f json
```

### From Python

The package can also be used programmatically in Python:

```python
from synapse_miner import SynapseMiner

# Initialize the miner
miner = SynapseMiner(context_size=100, deduplication=True)

# Process a single file
findings = miner.process_file("path/to/article.pdf")

# Process a directory
results = miner.process_directory("path/to/articles/")

# Save results
miner.save_results_to_csv("results.csv")
# or
miner.save_results_to_json("results.json")

# Generate and print summary
summary = miner.generate_summary()
print(f"Found {summary['unique_synapse_ids']} unique Synapse IDs")
```

## Convenience Functions

For quick, one-off analysis, you can use the convenience functions:

```python
from synapse_miner import mine_file, mine_directory

# Mine a single file
result = mine_file("path/to/article.pdf")
print(f"Found {result['summary']['unique_ids']} unique Synapse IDs")

# Mine a directory
result = mine_directory("path/to/articles/")
summary = result['summary']
```

## Advanced Usage

### Customizing Context Size

You can control how much context to extract around each Synapse ID:

```bash
# From the command line (200 characters)
synapse-miner path/to/articles/ -c 200
```

```python
# In Python
miner = SynapseMiner(context_size=200)
```

### Handling Duplicate IDs

By default, the tool deduplicates identical Synapse IDs within a document. To include all occurrences:

```bash
# From the command line
synapse-miner path/to/articles/ --no-dedup
```

```python
# In Python
miner = SynapseMiner(deduplication=False)
```

### Parallel Processing

The tool processes files in parallel by default. For sequential processing:

```bash
# From the command line
synapse-miner path/to/articles/ --sequential
```

```python
# In Python
results = miner.process_directory("path/to/articles/", parallel=False)
```

### Filtering File Types

You can specify which file types to process:

```bash
# From the command line
synapse-miner path/to/articles/ -e .pdf .txt
```

```python
# In Python
results = miner.process_directory("path/to/articles/", extensions=[".pdf", ".txt"])
```

## Working with Raw Text

If you already have text content, you can extract Synapse IDs directly:

```python
from synapse_miner import SynapseMiner

text = """
This is an example text mentioning a Synapse ID syn1234567.
It also references another resource at syn9876543.
"""

miner = SynapseMiner()
findings = miner.extract_synapse_ids_with_context(text, "example_text")

for finding in findings:
    print(f"Found {finding['synapse_id']} with context: {finding['full_context']}")
```

## Integration Examples

### Integrating with pandas

```python
import pandas as pd
from synapse_miner import mine_directory

# Mine a directory
result = mine_directory("path/to/articles/")

# Convert all findings to a DataFrame
all_findings = []
for doc, findings in result['results'].items():
    all_findings.extend(findings)

df = pd.DataFrame(all_findings)

# Analyze the data
doc_counts = df['document'].value_counts()
id_counts = df['synapse_id'].value_counts()
```

### Integrating with Matplotlib

```python
import matplotlib.pyplot as plt
import pandas as pd
from synapse_miner import mine_directory

# Mine a directory
result = mine_directory("path/to/articles/")

# Convert to DataFrame
all_findings = []
for doc, findings in result['results'].items():
    all_findings.extend(findings)

df = pd.DataFrame(all_findings)

# Plot the top 10 most frequent Synapse IDs
id_counts = df['synapse_id'].value_counts().head(10)
id_counts.plot(kind='bar')
plt.title('Top 10 Synapse IDs by Frequency')
plt.xlabel('Synapse ID')
plt.ylabel('Frequency')
plt.tight_layout()
plt.savefig('top_synapse_ids.png')
