# LLM Cross-Lingual Translation & Evaluation

This repository contains the experimental codebase for the study of **selective semantic-pragmatic degradation in LLM cross-lingual transmission**.

The project investigates how semantic and pragmatic information degrades through multi-round cross-lingual translation chains in Large Language Models, demonstrating that degradation is not random but follows a directional linguistic selection mechanism.

## Repository Structure

```
.
├── translation_system/        # Core experimental system
│   ├── src/                   # Python modules (API client, translator, runner, etc.)
│   ├── 1_data/                # Source texts & prompt templates
│   │   ├── source/            # Source texts (EN, ZH)
│   │   └── prompts/           # Prompt templates (translate, paraphrase, backtranslate)
│   ├── config.yaml            # Experiment configuration (groups, languages, chains)
│   ├── run_experiment.py      # Main entry point
│   ├── .env.example           # API configuration template
│   ├── requirements.txt       # Python dependencies
│   └── tldr.md                # Quick start guide
│
├── Data_Crawl/                # Multi-lingual data collection pipeline
│   ├── src/                   # Crawler & translator modules
│   ├── config/                # Crawler configuration
│   ├── cli.py                 # CLI entry point
│   ├── translate.py           # Translation pipeline
│   └── README.md              # Documentation
│
└── open_eval_project/         # Evaluation toolkit
    ├── evaluate_pure.py       # LLM-based evaluation (pragmatic dimensions)
    ├── evaluate_analysis.py   # Automated analysis & visualization
    └── outputs/               # Evaluation results
```

## Components

### 1. `translation_system/` — Cross-Lingual Translation Chain Experiment

The core system for running multi-round cross-lingual translation experiments. It calls OpenAI-compatible Chat Completion APIs to execute translation chains and records all intermediate results.

**Experiment Design:**

| Group | Chain | Type |
|-------|-------|------|
| Group 1 | EN→JA→ZH→FR | Cross-script chain |
| Group 2 | EN→FR→ZH→JA | Cross-script chain |
| Group 3 (Control) | EN→FR→DE→IT | European language chain |
| Group 4 (Control) | EN→EN→EN→EN | Monolingual paraphrase chain |

Each step also performs **back-translation** to the origin language (EN) for comparison.

**Quick Start:**
```bash
cd translation_system
pip install -r requirements.txt
cp .env.example .env   # Edit .env with your API credentials
python run_experiment.py --dry-run   # Verify configuration
python run_experiment.py             # Run experiments
```

### 2. `Data_Crawl/` — Multi-Lingual Data Crawler

A scalable data collection pipeline that gathers multi-lingual text datasets from RSS feeds in 10 languages (EN, ZH, JA, KO, FR, DE, ES, RU, PT, IT).

**Quick Start:**
```bash
cd Data_Crawl
pip install -r requirements.txt
python cli.py fetch        # Start crawling
python translate.py        # Translate datasets
```

### 3. `open_eval_project/` — Evaluation Toolkit

Evaluation scripts for assessing translation quality across pragmatic dimensions including irony, speech act, register, uncertainty, and attitudinal intensity.

**Quick Start:**
```bash
cd open_eval_project
pip install -r requirements.txt
```

## Requirements

- Python 3.10+
- An OpenAI-compatible API endpoint (for `translation_system`)

## License

This project is released for academic research purposes.
