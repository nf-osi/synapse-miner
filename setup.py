"""
Setup script for Synapse Miner.
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="synapse-miner",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "pandas>=1.3.0",
        "pypdf>=3.0.0,<4.0.0",
        "tqdm>=4.65.0,<5.0.0",
        "python-magic>=0.4.27,<0.5.0",
        "synapseclient>=4.0.0,<5.0.0",
    ],
    entry_points={
        "console_scripts": [
            "synapse-miner=synapse_miner.cli:main",
        ],
    },
    author="Your Name",
    author_email="your.email@example.com",
    description="A tool for mining Synapse IDs from scientific articles",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/synapse-miner",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
)