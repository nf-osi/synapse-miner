# Usage Guide

## Python API

### Basic Usage

You can use the Synapse Miner directly in your Python code:

```python
from synapse_miner import SynapseMiner

# Create a miner instance
miner = SynapseMiner()

# Process a single file
results = miner.process_file("path/to/article.pdf")
print(f"Found {len(results)} findings")

# Process a directory
results = miner.process_directory("path/to/articles/")
print(f"Found results for {len(results)} files")

# Save the results
all_findings = [finding for findings in results.values() for finding in findings]
miner.save_results(all_findings, "results.csv", "csv")
```

### Advanced Configuration

You can configure the Synapse Miner with various options:

```python
from synapse_miner import SynapseMiner, SynapseMinerConfig

# Create a configuration object
config = SynapseMinerConfig()

# Set configuration options
config.set("context_size", 150)  # Characters of context around each Synapse ID
config.set("deduplication", True)  # Deduplicate identical Synapse IDs within documents
config.set("batch_size", 50)  # Number of files to process before saving interim results
config.set("max_workers", 4)  # Number of parallel worker threads
config.set("allowed_extensions", [".pdf", ".txt", ".xml"])  # File types to process

# Create a miner with the configuration
miner = SynapseMiner(config)

# Process files with the configuration
results = miner.process_directory("path/to/articles/")

# Save results
all_findings = [finding for findings in results.values() for finding in findings]
miner.save_results(all_findings, "results.csv", "csv")
```

### Processing Large Datasets

For large datasets, you can use batch processing:

```python
from synapse_miner import SynapseMiner, SynapseMinerConfig

# Configure for batch processing
config = SynapseMinerConfig()
config.set("batch_size", 100)
config.set("max_workers", 8)

# Create a miner
miner = SynapseMiner(config)

# Process directory - results will be saved in batches
results = miner.process_directory("path/to/large_dataset/")

# Combine all batch files into a single output
miner.combine_batch_files("final_results.csv", "csv")
```

### Processing XML Files from Europe PMC

To process XML files from Europe PMC:

```python
from synapse_miner import process_ftp_files

# Process files from Europe PMC
results = process_ftp_files(
    max_files=10,  # Process only 10 files
    output_path="europe_pmc_results.csv",
    show_progress=True
)
```

## Command-line Interface

### Basic Usage

Process a single file:

```bash
synapse-miner local path/to/file.pdf -o results.csv
```

Process a directory:

```bash
synapse-miner local path/to/directory -o results.csv
```

### Advanced Options

```bash
# Process a directory with custom context size and specific file types
synapse-miner local path/to/directory -o results.csv -c 200 --extensions .pdf .txt

# Disable deduplication of Synapse IDs
synapse-miner local path/to/directory -o results.csv --no-deduplication

# Enable verbose logging
synapse-miner local path/to/directory -o results.csv -v

# Use multiple worker threads
synapse-miner local path/to/directory -o results.csv --max-workers 8
```

### Processing Files from Europe PMC

```bash
# Process 5 files from Europe PMC
synapse-miner ftp --max-files 5 -o europe_pmc_results.csv

# Process specific files matching a pattern
synapse-miner ftp --pattern "PMC123.*\.xml\.gz" -o results.csv

# Process files with more context
synapse-miner ftp --max-files 10 -o results.csv -c 200
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

```
