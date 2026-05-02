"""
translator.py — 翻译执行器

职责：
- 执行单条翻译（独立 session）
- 执行批量翻译（多任务合并到一次 API 请求）
- 解析批量响应（支持 JSON 数组和正则回退）

所有翻译步骤使用独立 session（无上下文累积）。
"""

import re
import json
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
        """执行单条翻译（独立 session）。"""
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
        """批量翻译：将多个任务合并到一次 API 请求。"""
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
        
        # 启用 JSON Mode (Structured Output)
        response = self.api_client.chat_completion(
            messages, 
            response_format={"type": "json_object"}
        )

        # 解析批量响应
        try:
            outputs = self._parse_batch_response(response.content, len(tasks))
        except ValueError as e:
            logger.error("Parsing failed. Usage: %s, Finish Reason: %s", response.usage, response.finish_reason)
            raise e
        
        task_desc = ", ".join(
            f"{t.source_lang}→{t.target_lang}" for t in tasks[:3]
        )
        if len(tasks) > 3:
            task_desc += f", ... (+{len(tasks)-3})"
            
        logger.info(
            "Batch translation (%d tasks) [JSON Mode]: [%s] (tokens=%s, finish=%s)",
            len(tasks), task_desc, response.usage.get("total_tokens", "?"), response.finish_reason,
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
        优先尝试 JSON 解析 (期望格式: {"results": ["...", "..."]})
        """
        # 1. 尝试解析 JSON
        clean_content = content.strip()
        
        # 处理可能存在的 markdown 代码块
        if clean_content.startswith("```"):
            code_match = re.search(r"```(?:json)?\n(.*?)\n```", clean_content, re.DOTALL)
            if code_match:
                clean_content = code_match.group(1).strip()
            else:
                clean_content = re.sub(r"^```(?:json)?\n?|```$", "", clean_content).strip()

        try:
            data = json.loads(clean_content)
            # 期待格式: {"results": {"1": "...", "2": "..."}}
            results_dict = {}
            if isinstance(data, dict) and "results" in data:
                results_dict = data["results"]
            
            # 兼容如果模型依然返回了数组
            if isinstance(results_dict, list):
                if len(results_dict) == expected_count:
                    return [str(item).strip() for item in results_dict]
                else:
                    logger.warning("JSON parsed but array length mismatch: got %d, expected %d", len(results_dict), expected_count)
            elif isinstance(results_dict, dict):
                # 从 dict 中按 1..N 提取
                extracted = []
                for i in range(1, expected_count + 1):
                    key = str(i)
                    if key in results_dict:
                        extracted.append(str(results_dict[key]).strip())
                
                if len(extracted) == expected_count:
                    return extracted
                else:
                    logger.warning("JSON parsed but dict missing keys: found %d/%d", len(extracted), expected_count)

        except json.JSONDecodeError as e:
            logger.warning("JSONDecodeError: %s. Attempting heuristic extraction...", str(e))
            
            # 启发式提取：针对 Dict 结构 {"1": "...", "2": "..."}
            results_match = re.search(r'"results"\s*:\s*\{(.*)', clean_content, re.DOTALL)
            if results_match:
                dict_content = results_match.group(1)
                # 提取形如 "数字": "内容"
                pattern = r'"(\d+)"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"'
                matches = re.findall(pattern, dict_content)
                
                extracted_dict = {m[0]: m[1] for m in matches}
                extracted = []
                for i in range(1, expected_count + 1):
                    key = str(i)
                    if key in extracted_dict:
                        extracted.append(extracted_dict[key].strip())
                        
                if len(extracted) == expected_count:
                    logger.info("Heuristic extraction succeeded: found %d results via regex.", len(extracted))
                    return extracted
                elif len(extracted) > 0:
                    logger.warning("Heuristic extraction found partial results: %d/%d", len(extracted), expected_count)

        # 2. 尝试正则表达式解析 (回退策略)
        logger.warning("JSON parse failed or length mismatch, trying regex fallback...")
        
        # 模式 A: === Result N ===
        pattern_a = r"===\s*Result\s+(\d+)\s*===\s*\n?"
        parts = re.split(pattern_a, content)
        results_a: dict[int, str] = {}
        for i in range(1, len(parts) - 1, 2):
            idx = int(parts[i])
            results_a[idx] = parts[i + 1].strip()
        
        if len(results_a) == expected_count:
            return [results_a[i] for i in range(1, expected_count + 1)]

        # 模式 B: [N]
        pattern_b = r"\[(\d+)\]\s*\n?"
        parts_b = re.split(pattern_b, content)
        results_b: dict[int, str] = {}
        for i in range(1, len(parts_b) - 1, 2):
            idx = int(parts_b[i])
            results_b[idx] = parts_b[i + 1].strip()
        
        if len(results_b) == expected_count:
            return [results_b[i] for i in range(1, expected_count + 1)]

        # 3. 最终失败处理
        debug_file = "failed_response_debug.json"
        with open(debug_file, "w", encoding="utf-8") as f:
            f.write(content)
            
        logger.error(
            "All batch parse strategies failed! Expected %d results but found none. "
            "Raw response has been saved to %s for debugging. (first 500 chars): %s...",
            expected_count, debug_file, content[:500]
        )
        raise ValueError(
            f"Batch response parsing failed: expected {expected_count} results. "
            f"Check {debug_file} for the raw response."
        )
