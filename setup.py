"""
Setup script for the Synapse ID Mining package.
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="synapse-miner",
    version="0.1.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="A package for mining Synapse IDs from scientific articles",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/synapse-miner",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
        "Topic :: Text Processing :: General",
    ],
    python_requires=">=3.7",
    install_requires=[
        "PyPDF2>=2.0.0",
        "pandas>=1.0.0",
        "tqdm>=4.40.0",
    ],
    entry_points={
        "console_scripts": [
            "synapse-miner=synapse_miner.cli:main",
        ],
    },
)