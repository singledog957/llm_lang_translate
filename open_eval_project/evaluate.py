#!/usr/bin/env python3
"""Combined pragmatic entrypoint for LLM evaluation and post-hoc analysis."""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from dotenv import load_dotenv
from tqdm import tqdm

from evaluate_analysis import METRIC_DISPLAY, SCORE_METRICS, compute_dim_scores, prepare_scores_dataframe
from src.api_client import APIClient, ChatMessage

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
ITEMS_PER_REQUEST = 4
CONCURRENT_REQUESTS = 3
EVAL_MODEL = "gpt-5.5"

BASE_URL = os.environ.get("BASE_URL", "")
API_KEY = os.environ.get("API_KEY", "")

_PROMPT_SECTIONS: dict[str, str] | None = None
_RESULT_TEXT_CACHE: dict[str, tuple[str, str]] = {}


def load_eval_prompt() -> dict[str, str]:
    """Load the evaluation prompt sections from the shared prompt file."""
    prompt_file = PROJECT_ROOT / "1_data" / "prompts" / "eval_prompt.md"
    with prompt_file.open("r", encoding="utf-8") as handle:
        content = handle.read()

    sections: dict[str, str] = {}
    current_section: str | None = None
    current_lines: list[str] = []

    for line in content.splitlines():
        if line.startswith("# Section: "):
            if current_section is not None:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = line[len("# Section: "):].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_section is not None:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


def _get_prompt_sections() -> dict[str, str]:
    global _PROMPT_SECTIONS
    if _PROMPT_SECTIONS is None:
        _PROMPT_SECTIONS = load_eval_prompt()
    return _PROMPT_SECTIONS


def extract_data_from_jsonl(file_path: str) -> list[dict[str, Any]]:
    """Extract items to evaluate from a result JSONL file."""
    data: list[dict[str, Any]] = []
    with open(file_path, "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            texts = item.get("texts", {})
            en_keys = [key for key in texts.keys() if key.startswith("EN")]
            en_indices = [int(key[2:]) for key in en_keys if key[2:].isdigit()]
            max_en_idx = max(en_indices) if en_indices else 0

            model_name = item.get("model", "")
            if not model_name and "metadata" in item:
                model_name = item["metadata"].get("model", "")

            data.append(
                {
                    "model": model_name,
                    "group": item.get("group", ""),
                    "source_id": item.get("source_id", ""),
                    "type": item.get("type", ""),
                    "chain": item.get("chain", []),
                    "en0": texts.get("EN0", ""),
                    "en_last": texts.get(f"EN{max_en_idx}", ""),
                }
            )
    return data


def process_batch(client: APIClient, batch: list[dict[str, Any]], max_retries: int = 3) -> list[dict[str, Any]]:
    sections = _get_prompt_sections()
    system_prompt = sections.get("SYSTEM_PROMPT", "You are a strict translation evaluator. Return only valid JSON.")
    user_preamble = sections.get("USER_PREAMBLE", "")

    text_parts = [user_preamble]
    for item in batch:
        text_parts.append(
            f"\n[Source ID: {item['source_id']}]\n"
            f"EN0 (source): {item['en0']}\n"
            f"EN_last (final translation): {item['en_last']}"
        )

    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content="\n".join(text_parts)),
    ]
    response_format = {"type": "json_object"}

    for attempt in range(max_retries):
        try:
            response = client.chat_completion(messages, response_format=response_format)
            if not response.content:
                raise ValueError("Empty content received from API")

            result_json = json.loads(response.content)
            evaluated_items: list[dict[str, Any]] = []

            for item in batch:
                sid = item["source_id"]
                if sid not in result_json:
                    logging.warning("Missing source_id %s in LLM response.", sid)
                    continue

                raw_dimensions = result_json[sid]
                dim_scores = compute_dim_scores(raw_dimensions)
                evaluated_items.append(
                    {
                        "model": item["model"],
                        "group": item["group"],
                        "source_id": sid,
                        "type": item["type"],
                        "chain": item["chain"],
                        "irony": dim_scores["irony"],
                        "speech_act": dim_scores["speech_act"],
                        "register": dim_scores["register"],
                        "uncertainty": dim_scores["uncertainty"],
                        "attitude": dim_scores["attitude"],
                        "raw_detail": raw_dimensions,
                    }
                )

            return evaluated_items
        except Exception as exc:
            if attempt < max_retries - 1:
                logging.warning("Batch processing error (%s). Retrying in 3s...", exc)
                time.sleep(3)
            else:
                logging.error("Batch failed after %s attempts: %s", max_retries, exc)
                return []


def run_pure_evaluation() -> Path:
    print(f"Starting evaluation with model: {EVAL_MODEL}")
    print(f"Concurrency: {CONCURRENT_REQUESTS}, Batch Size: {ITEMS_PER_REQUEST}")

    client = APIClient(base_url=BASE_URL, api_key=API_KEY, model=EVAL_MODEL, api_mode="response")

    results_dir = PROJECT_ROOT / "3_exps" / "results"
    eval_dir = PROJECT_ROOT / "3_exps" / "evaluate"
    eval_dir.mkdir(parents=True, exist_ok=True)

    jsonl_files = glob.glob(str(results_dir / "*" / "*.jsonl"))
    print(f"Found {len(jsonl_files)} JSONL files to evaluate.")

    all_data: list[dict[str, Any]] = []
    for file_path in jsonl_files:
        all_data.extend(extract_data_from_jsonl(file_path))
    print(f"Extracted {len(all_data)} items to evaluate.")

    batches = [all_data[index:index + ITEMS_PER_REQUEST] for index in range(0, len(all_data), ITEMS_PER_REQUEST)]
    output_file = eval_dir / f"evaluation_results_{int(time.time())}.jsonl"
    print(f"Results will be saved to: {output_file}")

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as executor:
        futures = {executor.submit(process_batch, client, batch): batch for batch in batches}
        for future in tqdm(as_completed(futures), total=len(batches), desc="Processing Batches"):
            batch_result = future.result()
            if batch_result:
                results.extend(batch_result)
                with output_file.open("a", encoding="utf-8") as handle:
                    for result in batch_result:
                        handle.write(json.dumps(result, ensure_ascii=False) + "\n")

    print(f"\nEvaluation complete! {len(results)}/{len(all_data)} items evaluated.")
    print(f"Results saved to {output_file}")
    return output_file


def load_evaluation_data(eval_dir: Path) -> pd.DataFrame:
    """Load all JSONL evaluation results from the analysis directory."""
    data: list[dict[str, Any]] = []
    for file_path in sorted(eval_dir.glob("*.jsonl")):
        with file_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    data.append(json.loads(line))
    return pd.DataFrame(data)


def fetch_text_from_results(base_dir: Path, model: str, group: str, source_id: str) -> tuple[str, str]:
    """Fetch the source and final English texts from the original result JSONL files."""
    cache_key = f"{model}_{group}_{source_id}"
    if cache_key in _RESULT_TEXT_CACHE:
        return _RESULT_TEXT_CACHE[cache_key]

    results_dir = base_dir / "3_exps" / "results"
    matched_files = glob.glob(str(results_dir / "*" / f"{group}.jsonl"))

    for file_path in matched_files:
        with open(file_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                sid = item.get("source_id")
                model_name = item.get("model", "")
                if not model_name and "metadata" in item:
                    model_name = item["metadata"].get("model", "")

                texts = item.get("texts", {})
                en_keys = [key for key in texts.keys() if key.startswith("EN")]
                en_indices = [int(key[2:]) for key in en_keys if key[2:].isdigit()]
                max_en_idx = max(en_indices) if en_indices else 0
                en0 = texts.get("EN0", "")
                en_last = texts.get(f"EN{max_en_idx}", "")

                _RESULT_TEXT_CACHE[f"{model_name}_{group}_{sid}"] = (en0, en_last)

    return _RESULT_TEXT_CACHE.get(cache_key, ("(Text not found)", "(Text not found)"))


def run_analysis(base_dir: Path | None = None, eval_dir: Path | None = None, out_dir: Path | None = None) -> Path:
    print("Starting evaluation analysis...")
    base_dir = base_dir or PROJECT_ROOT
    eval_dir = eval_dir or (base_dir / "3_exps" / "evaluate")
    out_dir = out_dir or (eval_dir / "analysis_results")
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_evaluation_data(eval_dir)
    if df.empty:
        print("No evaluation data found in", eval_dir)
        return out_dir

    df = prepare_scores_dataframe(df)
    if df.empty:
        print("No scoreable data found - all dimension columns are NaN.")
        return out_dir

    print("Generating Model & Group analysis...")
    avg_by_model_group = df.groupby(["model", "group"], dropna=False)["average_score"].mean().reset_index()
    avg_by_model_group.to_csv(out_dir / "average_scores_by_model_group.csv", index=False)

    plt.rcParams["font.sans-serif"] = ["SimHei", "WenQuanYi Micro Hei", "Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False

    plt.figure(figsize=(12, 6))
    sns.barplot(data=avg_by_model_group, x="model", y="average_score", hue="group")
    plt.title("Average Translation Score by Model and Group")
    plt.xticks(rotation=45, ha="right")
    plt.ylabel("Average Score (0-100)")
    plt.legend(title="Group", bbox_to_anchor=(1.05, 1), loc="upper left")
    plt.tight_layout()
    plt.savefig(out_dir / "average_scores_bar.png")
    plt.close()

    print("Generating Metrics Heatmap...")
    avg_by_model_metric = df.groupby("model", dropna=False)[SCORE_METRICS].mean().reset_index()
    display_df = avg_by_model_metric.rename(columns=METRIC_DISPLAY).set_index("model")
    avg_by_model_metric.to_csv(out_dir / "average_scores_by_model_metric.csv", index=False)

    plt.figure(figsize=(10, 8))
    sns.heatmap(display_df.T, annot=True, cmap="YlGnBu", fmt=".1f", vmin=0, vmax=100)
    plt.title("Average Dimension Score by Model")
    plt.tight_layout()
    plt.savefig(out_dir / "metrics_heatmap.png")
    plt.close()

    print("Extracting highest and lowest performing texts for each model...")
    report_lines = ["# 翻译评估分析报告 (Evaluation Analysis Report)", ""]

    for model_name in df["model"].dropna().unique():
        model_df = df[df["model"] == model_name].dropna(subset=["average_score"])
        if model_df.empty:
            continue

        highest_row = model_df.loc[model_df["average_score"].idxmax()]
        lowest_row = model_df.loc[model_df["average_score"].idxmin()]
        en0_high, en_last_high = fetch_text_from_results(base_dir, model_name, highest_row["group"], highest_row["source_id"])
        en0_low, en_last_low = fetch_text_from_results(base_dir, model_name, lowest_row["group"], lowest_row["source_id"])

        report_lines.append(f"## 模型 (Model): {model_name}")
        report_lines.append(f"- **模型整体平均分 (Overall Average Score)**: {model_df['average_score'].mean():.2f}")
        report_lines.append("")
        report_lines.append(f"### 表现最好的文本 (Best Performing Text) - 得分: {highest_row['average_score']:.2f}")
        report_lines.append(f"- **Group**: {highest_row['group']}")
        report_lines.append(f"- **Source ID**: {highest_row['source_id']}")
        report_lines.append(f"- **英文原文 (EN0)**: {en0_high}")
        report_lines.append(f"- **最终翻译回英文 (EN_last)**: {en_last_high}")
        report_lines.append("")
        report_lines.append(f"### 表现最差的文本 (Worst Performing Text) - 得分: {lowest_row['average_score']:.2f}")
        report_lines.append(f"- **Group**: {lowest_row['group']}")
        report_lines.append(f"- **Source ID**: {lowest_row['source_id']}")
        report_lines.append(f"- **英文原文 (EN0)**: {en0_low}")
        report_lines.append(f"- **最终翻译回英文 (EN_last)**: {en_last_low}")
        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")

    with (out_dir / "analysis_report.md").open("w", encoding="utf-8") as handle:
        handle.write("\n".join(report_lines).rstrip() + "\n")

    print(f"Analysis complete! Results saved to: {out_dir}")
    print("- average_scores_bar.png (柱状图)")
    print("- metrics_heatmap.png (维度热力图)")
    print("- analysis_report.md (极值文本分析报告)")
    return out_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run evaluation or analysis for the open evaluation project.")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("pure", help="Run the LLM-based pragmatic evaluation workflow.")

    analysis_parser = subparsers.add_parser("analysis", help="Aggregate and visualize evaluation JSONL outputs.")
    analysis_parser.add_argument("--base-dir", default=str(PROJECT_ROOT), help="Project root directory.")
    analysis_parser.add_argument("--eval-dir", default=None, help="Directory containing evaluation JSONL files.")
    analysis_parser.add_argument("--output-dir", default=None, help="Directory for generated analysis artifacts.")

    return parser


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        run_pure_evaluation()
        return

    parser = build_parser()
    if argv[0] in {"-h", "--help"}:
        parser.print_help()
        return
    if argv[0] in {"pure", "analysis"}:
        args = parser.parse_args(argv)
        if args.command == "analysis":
            run_analysis(
                base_dir=Path(args.base_dir),
                eval_dir=Path(args.eval_dir) if args.eval_dir else None,
                out_dir=Path(args.output_dir) if args.output_dir else None,
            )
        else:
            run_pure_evaluation()
        return

    raise SystemExit(f"Unknown command: {argv[0]}. Use 'pure' or 'analysis'.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...")