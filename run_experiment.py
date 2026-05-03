#!/usr/bin/env python3
"""
run_experiment.py — 跨语言翻译链实验主入口

用法：
    python run_experiment.py                    # 使用默认 config.yaml
    python run_experiment.py --config my.yaml   # 使用自定义配置
    python run_experiment.py --dry-run          # 仅加载数据，不调用 API
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime

import yaml
from dotenv import load_dotenv

from src.api_client import APIClient
from src.data_io import DataIO
from src.prompt_manager import PromptManager
from src.experiment_runner import ExperimentRunner, ExperimentGroup
from src.logger import ExperimentLogger

# ------------------------------------------------------------------
# 日志配置
# ------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: str = "INFO"):
    logging.basicConfig(level=getattr(logging, level.upper()), format=LOG_FORMAT)


# ------------------------------------------------------------------
# 模型配置加载
# ------------------------------------------------------------------

def load_models_from_env() -> list[dict[str, str]]:
    """
    从 .env 加载所有模型配置。

    格式：MODEL{N}_NAME, MODEL{N}_BASE_URL, MODEL{N}_API_KEY
    返回按序号排列的模型配置列表。
    """
    models = []
    pattern = re.compile(r"^MODEL(\d+)_NAME$")

    # 收集所有 MODEL{N}_NAME
    indices = set()
    for key in os.environ:
        m = pattern.match(key)
        if m:
            indices.add(int(m.group(1)))

    for idx in sorted(indices):
        name = os.environ.get(f"MODEL{idx}_NAME", "")
        base_url = os.environ.get(f"MODEL{idx}_BASE_URL", "")
        api_key = os.environ.get(f"MODEL{idx}_API_KEY", "")

        if not all([name, base_url, api_key]):
            logging.warning(
                "Incomplete config for MODEL%d (name=%s), skipping.", idx, name
            )
            continue

        models.append({
            "name": name,
            "base_url": base_url,
            "api_key": api_key,
        })

    return models


def sanitize_model_name(name: str) -> str:
    """将模型名称中的 / 等特殊字符替换为 _，用于文件路径。"""
    return re.sub(r'[/\\:*?"<>|]', '_', name)


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="跨语言翻译链实验系统"
    )
    parser.add_argument(
        "--config", default="config.yaml",
        help="配置文件路径 (default: config.yaml)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅加载数据和配置，不调用 API",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别 (default: INFO)",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)
    log = logging.getLogger("main")

    # 1. 加载 .env
    load_dotenv()
    temperature = float(os.environ.get("TEMPERATURE", "0.0"))
    max_tokens = int(os.environ.get("MAX_TOKENS", "4096"))
    timeout = float(os.environ.get("TIMEOUT", "60.0"))
    paragraphs_per_request = int(os.environ.get("PARAGRAPHS_PER_REQUEST", "1"))

    # 2. 加载 config.yaml
    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    exp_config = config["experiment"]
    languages = config["languages"]
    api_config = config.get("api", {})

    # 3. 加载模型列表
    models = load_models_from_env()
    if not models:
        log.error(
            "No models configured. Set MODEL1_NAME, MODEL1_BASE_URL, "
            "MODEL1_API_KEY in .env (see .env.example)."
        )
        sys.exit(1)

    log.info("Found %d model(s): %s", len(models), [m["name"] for m in models])

    # 4. 加载源文本
    source_texts = DataIO.load_source_texts(
        path=exp_config["source_file"],
        lang_prefix=exp_config["source_lang_prefix"],
        count=exp_config.get("source_count", 0),
    )
    log.info("Loaded %d source texts", len(source_texts))

    # 5. 加载 prompt 模板
    prompt_manager = PromptManager(
        prompts_dir=exp_config["prompts_dir"],
        lang=exp_config.get("prompt_lang", "EN"),
    )
    log.info("Prompt templates: %s", prompt_manager.available_templates)

    # 6. 构建实验组
    groups = []
    for g in config["groups"]:
        groups.append(ExperimentGroup(
            name=g["name"],
            chain=g["chain"],
            origin_lang=g["origin_lang"],
            group_type=g.get("type", "translate"),
        ))
    log.info("Experiment groups: %s", [g.name for g in groups])

    # 7. Dry-run 检查
    if args.dry_run:
        log.info("=== DRY RUN MODE ===")
        log.info("Source texts: %d", len(source_texts))
        log.info("Paragraphs per request: %d", paragraphs_per_request)
        for st in source_texts[:3]:
            log.info("  %s: %s...", st.id, st.content[:80])
        log.info("Groups:")
        for g in groups:
            log.info("  %s: %s (type=%s)", g.name, "→".join(g.chain), g.group_type)
        log.info("Models: %s", [m["name"] for m in models])

        # 估算 API 调用次数
        num_groups = len(groups)
        max_steps = max(g.num_steps for g in groups)
        calls_per_step = 0
        for step in range(max_steps):
            active = sum(1 for g in groups if step < g.num_steps)
            bt = sum(1 for g in groups if step < g.num_steps and g.needs_backtranslation(step))
            calls_per_step += (1 if active > 0 else 0) + (1 if bt > 0 else 0)

        import math
        num_batches = math.ceil(len(source_texts) / paragraphs_per_request)
        total_calls = calls_per_step * num_batches
        log.info(
            "Estimated API calls: %d rounds × %d text batches (%d texts / %d per req) = %d calls per model",
            calls_per_step, num_batches, len(source_texts), paragraphs_per_request, total_calls,
        )
        log.info("Total across %d model(s): %d calls", len(models), total_calls * len(models))
        return

    # 8. 对每个模型串行执行
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for model_conf in models:
        model_name = model_conf["name"]
        
        # --- Prepare Output Directory ---
        resume_dir = os.getenv("RESUME_DIR")
        if resume_dir and os.path.isdir(resume_dir):
            output_path = resume_dir
            log.info("Resuming experiment in existing directory: %s", output_path)

            # Check model mismatch in progress.json
            progress_path = os.path.join(output_path, "logs", "progress.json")
            if os.path.exists(progress_path):
                try:
                    with open(progress_path, "r", encoding="utf-8") as f:
                        old_progress = json.load(f)
                        old_model = old_progress.get("model")
                        if old_model and old_model != model_name:
                            print(f"\n[WARNING] Model Mismatch detected in {output_path}")
                            print(f"  Current model: {model_name}")
                            print(f"  Resumed model: {old_model}")
                            ans = input("  Continue anyway? (y/N): ").strip().lower()
                            if ans != 'y':
                                log.info("User aborted due to model mismatch.")
                                sys.exit(0)
                except Exception as e:
                    log.warning("Failed to check model name in progress.json: %s", e)
        else:
            safe_name = sanitize_model_name(model_name)
            run_dir = f"{safe_name}_{timestamp}"
            output_path = os.path.join(exp_config["output_dir"], run_dir)
            os.makedirs(output_path, exist_ok=True)
            log.info("Output directory: %s", output_path)

        log.info("========== Running with model: %s ==========", model_name)

        # 创建 API 客户端
        api_mode = os.environ.get("API_MODE", "completion").lower()
        api_client = APIClient(
            base_url=model_conf["base_url"],
            api_key=model_conf["api_key"],
            model=model_name,
            api_mode=api_mode,
            temperature=temperature,
            max_tokens=max_tokens,
            retry_attempts=api_config.get("retry_attempts", 3),
            retry_delay=api_config.get("retry_delay", 2.0),
            request_interval=api_config.get("request_interval", 0.5),
            timeout=timeout,
        )

        # 创建日志记录器
        log_dir = os.path.join(output_path, "logs")
        exp_logger = ExperimentLogger(log_dir=log_dir, model_name=model_name)

        # 创建调度器
        runner = ExperimentRunner(
            api_client=api_client,
            prompt_manager=prompt_manager,
            exp_logger=exp_logger,
            languages=languages,
            output_dir=output_path,
            paragraphs_per_request=paragraphs_per_request,
        )

        # 执行
        results = runner.run_all(groups, source_texts)

        # 打印摘要
        for gname, gresults in results.items():
            log.info("  %s: %d chain results", gname, len(gresults))

    log.info("========== All experiments completed ==========")


if __name__ == "__main__":
    main()
