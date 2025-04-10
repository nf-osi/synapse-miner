# Synapse Miner

A Python package for mining Synapse IDs from scientific articles.

## Features

- Extract Synapse IDs matching the pattern "syn" followed by 7-12 digits
- Process PDF, TXT, XML, and HTML files
- Capture surrounding context for each Synapse ID
- Process files in parallel for increased efficiency
- Generate summary statistics and analytics
- Save results in CSV or JSON format

## Installation

```bash
# Install from PyPI
pip install synapse-miner

# Or install from source
git clone https://github.com/yourusername/synapse-miner.git
cd synapse-miner
pip install -e .
```

## Usage

### Command Line Interface

```bash
# Process a single file
synapse-miner path/to/article.pdf -o results.csv

# Process a directory of articles
synapse-miner path/to/articles/ -o results.csv

# Customize context size (characters around each Synapse ID)
synapse-miner path/to/articles/ -o results.csv -c 200

# Save results as JSON
synapse-miner path/to/articles/ -o results.json -f json

# Process specific file types only
synapse-miner path/to/articles/ -e .pdf .txt

# Process files sequentially (not in parallel)
synapse-miner path/to/articles/ --sequential

# Show more verbose output
synapse-miner path/to/articles/ -v
```

### Python API

You can use the Synapse Miner directly in your Python code:

```python
from synapse_miner import SynapseMiner

# Create a miner instance
miner = SynapseMiner()

# Process a single file
results = miner.process_file("path/to/article.pdf")

# Process a directory
results = miner.process_directory("path/to/articles/")

# Configure the miner
from synapse_miner import SynapseMinerConfig
config = SynapseMinerConfig()
config.set("allowed_extensions", [".pdf", ".txt"])
config.set("context_size", 150)  # Increase context size

miner = SynapseMiner(config)
results = miner.process_directory("path/to/articles/")
```

## Output Format

The tool generates results in either CSV or JSON format:

### CSV Output

The CSV output contains the following columns:

- `synapse_id`: The extracted Synapse ID
- `document`: Name of the source document
- `position`: Character position of the Synapse ID in the document
- `context_before`: Text context before the Synapse ID
- `context_after`: Text context after the Synapse ID
- `full_context`: Complete context including the Synapse ID

### Summary Output

The tool also prints a summary of results:

```
Synapse ID Mining Summary:
Documents processed: 25
Total Synapse ID mentions: 142
Unique Synapse IDs: 37

Top mentioned Synapse IDs:
  syn7778527: found in 12 documents
  syn7222438: found in 9 documents
  syn8474605: found in 7 documents
```

## Development

### Requirements

- Python 3.7+
- PyPDF2
- pandas
- tqdm

### Testing

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=synapse_miner
```

### Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.