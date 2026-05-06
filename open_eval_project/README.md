# Open Eval Project

This folder now contains two separate evaluation paths:

- Pragmatic evaluation and analysis driven by `evaluate.py`
- The legacy syntax/semantic CSV evaluator in `open_eval_project/evaluator.py`

## Pragmatic Evaluation

Run the LLM-based evaluation over the experiment JSONL files:

```bash
python evaluate.py
```

The same workflow is also available through the compatibility wrapper:

```bash
python evaluate_pure.py
```

Run the post-hoc analysis over the generated evaluation JSONL files:

```bash
python evaluate.py analysis
```

You can override the default directories if needed:

```bash
python evaluate.py analysis --base-dir . --eval-dir 3_exps/evaluate --output-dir 3_exps/evaluate/analysis_results
```

### Input Layout

The pure evaluation workflow reads result JSONL files under:

- `3_exps/results/*/*.jsonl`

It loads the prompt definition from:

- `1_data/prompts/eval_prompt.md`

### Outputs

The pure evaluation workflow writes a timestamped JSONL file to:

- `3_exps/evaluate/evaluation_results_<timestamp>.jsonl`

The analysis workflow writes the following files under:

- `3_exps/evaluate/analysis_results/average_scores_by_model_group.csv`
- `3_exps/evaluate/analysis_results/average_scores_bar.png`
- `3_exps/evaluate/analysis_results/average_scores_by_model_metric.csv`
- `3_exps/evaluate/analysis_results/metrics_heatmap.png`
- `3_exps/evaluate/analysis_results/analysis_report.md`

### Scoring Helpers

`evaluate_analysis.py` now only keeps the score-computation and score-frame normalization helpers used by the pragmatic workflow.

## Legacy Evaluator

The original syntax/semantic retention evaluator is still available through the package entry point:

```bash
open-eval --input examples/sample_results.csv --output-dir outputs/sample_run
```

It evaluates the CSV format documented by `open_eval_project/evaluator.py` and writes:

- `scores.csv`
- `scores_detailed.csv`
- `summary_by_model.csv`
- `summary_by_model_chain.csv`

## Installation

```bash
cd open_eval_project
python -m pip install -r requirements.txt
```

To use the spaCy semantic extractor in the legacy evaluator, also install the English model:

```bash
python -m spacy download en_core_web_sm
```

If the model is not available, the legacy evaluator falls back to a regex-based semantic baseline.

## Example Data

A sample CSV for the legacy evaluator is included at:

- `examples/sample_results.csv`

## Repository Layout

```text
open_eval_project/
  evaluate.py
  evaluate_pure.py
  evaluate_analysis.py
  requirements.txt
  README.md
  examples/
    sample_results.csv
  open_eval_project/
    __init__.py
    evaluator.py
  outputs/
```