"""
experiment_runner.py — 实验调度器

职责：
- 管理四组实验的调度
- 实现"同轮次跨组批量 + 组内串行"的执行策略
- 支持多段源文本合并到一次请求（PARAGRAPHS_PER_REQUEST）
- 协调 translator、logger、data_io
- 支持断点续做

调度策略：
    将源文本按 PARAGRAPHS_PER_REQUEST 分批。对每个批次：
      Request 1 (batch): 4组 × N段 第1步翻译
      Request 2 (batch): 3组 × N段 第1步回译
      Request 3 (batch): 4组 × N段 第2步翻译
      ...
"""

import logging
from typing import Any

from src.api_client import APIClient
from src.data_io import DataIO, SourceText
from src.prompt_manager import PromptManager
from src.translator import Translator, TranslationTask, TranslationResult
from src.logger import ExperimentLogger

logger = logging.getLogger(__name__)


class ExperimentGroup:
    """实验组状态管理"""

    def __init__(self, name: str, chain: list[str], origin_lang: str,
                 group_type: str = "translate"):
        self.name = name
        self.chain = chain              # e.g. ["EN", "JA", "ZH", "FR"]
        self.origin_lang = origin_lang  # 回译目标语言
        self.group_type = group_type    # "translate" | "paraphrase"

    @property
    def num_steps(self) -> int:
        """翻译步数（链长度 - 1）"""
        return len(self.chain) - 1

    @property
    def is_paraphrase(self) -> bool:
        return self.group_type == "paraphrase"

    def needs_backtranslation(self, step_index: int) -> bool:
        """判断某步是否需要回译。"""
        if self.is_paraphrase:
            return False
        target = self.chain[step_index + 1]
        return target != self.origin_lang


class ExperimentRunner:
    """
    实验调度器。

    执行流程：
    1. 将源文本按 paragraphs_per_request 分批
    2. 对每个批次，按轮次执行翻译和回译
    3. 同轮次的多组 × 多段任务打包为一次批量 API 调用
    4. 保存结果，记录日志
    """

    def __init__(
        self,
        api_client: APIClient,
        prompt_manager: PromptManager,
        exp_logger: ExperimentLogger,
        languages: dict[str, str],
        output_dir: str,
        paragraphs_per_request: int = 1,
    ):
        self.translator = Translator(api_client, prompt_manager)
        self.exp_logger = exp_logger
        self.languages = languages
        self.output_dir = output_dir
        self.paragraphs_per_request = max(1, paragraphs_per_request)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def run_all(
        self,
        groups: list[ExperimentGroup],
        source_texts: list[SourceText],
    ) -> dict[str, list[dict[str, Any]]]:
        """
        执行所有实验。

        Args:
            groups: 实验组列表
            source_texts: 源文本列表

        Returns:
            {group_name: [chain_result_dict, ...]}
        """
        all_results: dict[str, list[dict]] = {g.name: [] for g in groups}

        # 按 paragraphs_per_request 分批
        batches = []
        for i in range(0, len(source_texts), self.paragraphs_per_request):
            batches.append(source_texts[i:i + self.paragraphs_per_request])

        logger.info(
            "Processing %d source texts in %d batches (paragraphs_per_request=%d)",
            len(source_texts), len(batches), self.paragraphs_per_request,
        )

        for batch_idx, batch in enumerate(batches):
            batch_ids = [s.id for s in batch]
            logger.info(
                "=== Batch %d/%d: %s ===",
                batch_idx + 1, len(batches), ", ".join(batch_ids),
            )

            # 过滤掉所有组都已完成的源文本
            active_sources = [
                s for s in batch
                if not all(
                    self.exp_logger.is_completed(s.id, g.name)
                    for g in groups
                )
            ]
            if not active_sources:
                logger.info("Skipping batch (all completed)")
                continue

            batch_results = self._process_batch(groups, active_sources)

            for source in active_sources:
                for group_name, result in batch_results.get(source.id, {}).items():
                    all_results[group_name].append(result)
                    DataIO.save_chain_result(
                        result,
                        output_dir=f"{self.output_dir}/{group_name}",
                        filename=f"{source.id}.json",
                    )
                    self.exp_logger.mark_completed(source.id, group_name)

        # 保存各组汇总
        for group_name, results in all_results.items():
            if results:
                DataIO.save_experiment_summary(
                    results, self.output_dir, group_name
                )

        self.exp_logger.save_summary({"source_count": len(source_texts)})
        return all_results

    # ------------------------------------------------------------------
    # 批次处理（多段源文本）
    # ------------------------------------------------------------------

    def _process_batch(
        self,
        groups: list[ExperimentGroup],
        sources: list[SourceText],
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """
        处理一批源文本的所有实验组。

        Args:
            groups: 实验组列表
            sources: 本批次的源文本列表

        Returns:
            {source_id: {group_name: chain_result_dict}}
        """
        max_steps = max(g.num_steps for g in groups)

        # 初始化状态：current_texts[source_id][group_name] = 当前文本
        current_texts: dict[str, dict[str, str]] = {}
        chain_results: dict[str, dict[str, dict]] = {}

        for source in sources:
            current_texts[source.id] = {}
            chain_results[source.id] = {}
            for g in groups:
                current_texts[source.id][g.name] = source.content
                chain_results[source.id][g.name] = {
                    "source_id": source.id,
                    "group": g.name,
                    "chain": g.chain,
                    "type": g.group_type,
                    "texts": {f"{source.language}0": source.content},
                    "steps": [],
                    "metadata": {"model": self.translator.api_client.model},
                }

        # 按轮次执行
        for step in range(max_steps):
            # --- 主翻译（批量：多组 × 多段）---
            translate_tasks: list[TranslationTask] = []
            # 记录每个 task 对应的 (source, group)
            task_mapping: list[tuple[SourceText, ExperimentGroup]] = []

            for g in groups:
                if step >= g.num_steps:
                    continue
                for source in sources:
                    if self.exp_logger.is_completed(source.id, g.name):
                        continue

                    src_lang = g.chain[step]
                    tgt_lang = g.chain[step + 1]

                    task = TranslationTask(
                        task_id=len(translate_tasks) + 1,
                        source_lang=src_lang,
                        target_lang=tgt_lang,
                        source_lang_full=self.languages.get(src_lang, src_lang),
                        target_lang_full=self.languages.get(tgt_lang, tgt_lang),
                        text=current_texts[source.id][g.name],
                        is_backtranslation=False,
                        is_paraphrase=g.is_paraphrase,
                        group_name=g.name,
                        source_id=source.id,
                    )
                    translate_tasks.append(task)
                    task_mapping.append((source, g))

            if not translate_tasks:
                continue

            translate_results = self.translator.translate_batch(translate_tasks)

            # 更新状态和结果
            for (source, g), task, result in zip(task_mapping, translate_tasks, translate_results):
                tgt_lang = g.chain[step + 1]
                current_texts[source.id][g.name] = result.output_text

                text_key = tgt_lang if not g.is_paraphrase else f"{tgt_lang}{step + 1}"
                chain_results[source.id][g.name]["texts"][text_key] = result.output_text
                chain_results[source.id][g.name]["steps"].append({
                    "step": step + 1,
                    "direction": f"{task.source_lang}→{task.target_lang}",
                    "type": "paraphrase" if g.is_paraphrase else "translate",
                    "tokens": result.api_response.usage if result.api_response else {},
                })

                if result.api_response:
                    self.exp_logger.log_api_call(
                        group_name=g.name,
                        source_id=source.id,
                        step_desc=f"Step {step+1}: {task.source_lang}→{task.target_lang}",
                        prompt=f"[batch task {task.task_id}]",
                        response=result.output_text[:500],
                        usage=result.api_response.usage,
                        latency_ms=result.api_response.latency_ms,
                    )

            # --- 回译（批量：多组 × 多段）---
            bt_tasks: list[TranslationTask] = []
            bt_mapping: list[tuple[SourceText, ExperimentGroup]] = []

            for (source, g), result in zip(task_mapping, translate_results):
                if step >= g.num_steps:
                    continue
                if not g.needs_backtranslation(step):
                    continue

                tgt_lang = g.chain[step + 1]
                bt_task = TranslationTask(
                    task_id=len(bt_tasks) + 1,
                    source_lang=tgt_lang,
                    target_lang=g.origin_lang,
                    source_lang_full=self.languages.get(tgt_lang, tgt_lang),
                    target_lang_full=self.languages.get(g.origin_lang, g.origin_lang),
                    text=result.output_text,
                    is_backtranslation=True,
                    is_paraphrase=False,
                    group_name=g.name,
                    source_id=source.id,
                )
                bt_tasks.append(bt_task)
                bt_mapping.append((source, g))

            if bt_tasks:
                bt_results = self.translator.translate_batch(bt_tasks)

                for (source, g), bt_task, bt_result in zip(bt_mapping, bt_tasks, bt_results):
                    en_key = f"{g.origin_lang}{step + 1}"
                    chain_results[source.id][g.name]["texts"][en_key] = bt_result.output_text
                    chain_results[source.id][g.name]["steps"].append({
                        "step": step + 1,
                        "direction": f"{bt_task.source_lang}→{bt_task.target_lang}",
                        "type": "backtranslation",
                        "tokens": bt_result.api_response.usage if bt_result.api_response else {},
                    })

                    if bt_result.api_response:
                        self.exp_logger.log_api_call(
                            group_name=g.name,
                            source_id=source.id,
                            step_desc=f"Step {step+1} BT: {bt_task.source_lang}→{bt_task.target_lang}",
                            prompt=f"[batch backtranslation task {bt_task.task_id}]",
                            response=bt_result.output_text[:500],
                            usage=bt_result.api_response.usage,
                            latency_ms=bt_result.api_response.latency_ms,
                        )

        return chain_results
