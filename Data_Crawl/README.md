# Multi-Lingual Data Crawler & Translator

A scalable data collection and translation pipeline designed to gather multi-lingual text datasets for LLM evaluation and training.

## Features
- **Multi-Lingual Crawling**: Automatically fetches articles from RSS feeds in 10 languages (EN, ZH, JA, KO, FR, DE, ES, RU, PT, IT).
- **Text Extraction**: Uses Trafilatura to cleanly extract main article content.
- **Domain Classification**: Auto-tags articles into domains (Politics, Technology, Science, etc.) using multi-lingual keyword mapping.
- **Automated Translation**: Built-in translation pipeline leveraging Tencent Cloud Translate API to automatically produce multi-lingual parallel datasets.

## Documentation
For detailed architecture, setup instructions, and configuration guides, please see the docs:
- [Detailed Guide (Docs/README.md)](Docs/README.md)
- [Quick Start / TL;DR (Docs/tldr.md)](Docs/tldr.md)

## Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Start crawling
python cli.py fetch

# Translate datasets (requires Tencent Cloud credentials in .env and config/translate.yaml configuration)
python translate.py

# View statistics
python stats.py
```
