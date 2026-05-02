"""
translator.py — 翻译执行器

职责：
- 执行单条翻译（独立 session）
- 执行批量翻译（多任务合并到一次 API 请求）
- 解析批量响应

所有翻译步骤使用独立 session（无上下文累积）。
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Any

from src.api_client import APIClient, ChatMessage, APIResponse
from src.prompt_manager import PromptManager

logger = logging.getLogger(__name__)


@dataclass
class TranslationTask:
    """一个翻译任务的描述"""
    task_id: int                    # 批量中的序号 (1-based)
    source_lang: str                # 源语言代码 e.g. "EN"
    target_lang: str                # 目标语言代码 e.g. "JA"
    source_lang_full: str           # 源语言全称 e.g. "English"
    target_lang_full: str           # 目标语言全称 e.g. "Japanese"
    text: str                       # 待翻译文本
    is_backtranslation: bool = False
    is_paraphrase: bool = False
    group_name: str = ""            # 所属实验组
    source_id: str = ""             # 所属源文本 ID


@dataclass
class TranslationResult:
    """一个翻译任务的结果"""
    task: TranslationTask
    output_text: str
    api_response: APIResponse | None = None


class Translator:
    """
    翻译执行器。

    支持两种模式：
    1. translate_single: 单条翻译，一次 API 调用完成一个任务
    2. translate_batch: 批量翻译，多个任务合并到一次 API 调用

    所有翻译使用独立 session，不维护上下文。
    """

    def __init__(self, api_client: APIClient, prompt_manager: PromptManager):
        self.api_client = api_client
        self.prompt_manager = prompt_manager

    # ------------------------------------------------------------------
    # 单条翻译
    # ------------------------------------------------------------------

    def translate_single(self, task: TranslationTask) -> TranslationResult:
        """
        执行单条翻译（独立 session）。

        Args:
            task: 翻译任务描述

        Returns:
            TranslationResult 包含翻译结果和 API 响应信息
        """
        template_name = self.prompt_manager.get_template_name(
            source_lang=task.source_lang,
            target_lang=task.target_lang,
            is_backtranslation=task.is_backtranslation,
            is_paraphrase=task.is_paraphrase,
        )

        prompt = self.prompt_manager.render(
            template_name,
            source_lang=task.source_lang_full,
            target_lang=task.target_lang_full,
            text=task.text,
        )

        messages = [ChatMessage(role="user", content=prompt)]
        response = self.api_client.chat_completion(messages)

        logger.info(
            "Single translation: %s [%s] %s→%s (tokens=%s)",
            task.source_id, task.group_name,
            task.source_lang, task.target_lang,
            response.usage.get("total_tokens", "?"),
        )

        return TranslationResult(
            task=task,
            output_text=response.content,
            api_response=response,
        )

    # ------------------------------------------------------------------
    # 批量翻译
    # ------------------------------------------------------------------

    def translate_batch(self, tasks: list[TranslationTask]) -> list[TranslationResult]:
        """
        批量翻译：将多个任务合并到一次 API 请求。

        如果只有一个任务，自动退化为单条翻译。

        Args:
            tasks: 翻译任务列表

        Returns:
            TranslationResult 列表（与输入顺序一致）
        """
        if len(tasks) == 0:
            return []

        if len(tasks) == 1:
            return [self.translate_single(tasks[0])]

        # 确保 task_id 连续
        for i, t in enumerate(tasks):
            t.task_id = i + 1

        # 构建批量 prompt
        batch_tasks = []
        for t in tasks:
            template_name = self.prompt_manager.get_template_name(
                source_lang=t.source_lang,
                target_lang=t.target_lang,
                is_backtranslation=t.is_backtranslation,
                is_paraphrase=t.is_paraphrase,
            )
            batch_tasks.append({
                "task_id": t.task_id,
                "template_name": template_name,
                "variables": {
                    "source_lang": t.source_lang_full,
                    "target_lang": t.target_lang_full,
                    "text": t.text,
                },
            })

        batch_prompt = self.prompt_manager.render_batch(batch_tasks)
        messages = [ChatMessage(role="user", content=batch_prompt)]
        response = self.api_client.chat_completion(messages)

        # 解析批量响应
        outputs = self._parse_batch_response(response.content, len(tasks))

        task_desc = ", ".join(
            f"{t.source_lang}→{t.target_lang}" for t in tasks
        )
        logger.info(
            "Batch translation (%d tasks): [%s] (tokens=%s)",
            len(tasks), task_desc, response.usage.get("total_tokens", "?"),
        )

        results = []
        for t, output in zip(tasks, outputs):
            results.append(TranslationResult(
                task=t,
                output_text=output,
                api_response=response,
            ))

        return results

    # ------------------------------------------------------------------
    # 响应解析
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_batch_response(content: str, expected_count: int) -> list[str]:
        """
        解析批量翻译的响应文本。

        期望格式:
            === Result 1 ===
            <翻译内容>

            === Result 2 ===
            <翻译内容>
            ...

        如果格式不匹配，尝试回退解析策略。

        Args:
            content: API 返回的原始文本
            expected_count: 期望的结果数量

        Returns:
            各任务的翻译结果列表
        """
        # 主解析：按 === Result N === 标记分割
        pattern = r"===\s*Result\s+(\d+)\s*===\s*\n?"
        parts = re.split(pattern, content)

        # parts 格式: [前导文本, "1", 内容1, "2", 内容2, ...]
        results: dict[int, str] = {}
        for i in range(1, len(parts) - 1, 2):
            idx = int(parts[i])
            text = parts[i + 1].strip()
            results[idx] = text

        if len(results) == expected_count:
            return [results[i] for i in range(1, expected_count + 1)]

        # 回退策略1：按 === Task N === 或 [N] 等分割
        logger.warning(
            "Primary batch parse found %d/%d results, trying fallback...",
            len(results), expected_count,
        )
        pattern2 = r"\[(\d+)\]\s*\n?"
        parts2 = re.split(pattern2, content)
        results2: dict[int, str] = {}
        for i in range(1, len(parts2) - 1, 2):
            idx = int(parts2[i])
            text = parts2[i + 1].strip()
            results2[idx] = text

        if len(results2) == expected_count:
            return [results2[i] for i in range(1, expected_count + 1)]

        # 回退策略2：按连续空行分割
        logger.warning(
            "Fallback parse also failed (%d/%d), splitting by blank lines...",
            len(results2), expected_count,
        )
        chunks = re.split(r"\n\n+", content.strip())
        # 过滤掉明显是标记行的段落
        chunks = [
            c.strip() for c in chunks
            if c.strip() and not re.match(r"^===.*===$", c.strip())
        ]

        if len(chunks) == expected_count:
            return chunks

        # 最终回退：返回原始文本作为第一个结果，其余为空
        logger.error(
            "All batch parse strategies failed. Expected %d results, "
            "returning raw content for manual review.",
            expected_count,
        )
        fallback = [content] + ["[PARSE_ERROR: batch response parsing failed]"] * (expected_count - 1)
        return fallback
