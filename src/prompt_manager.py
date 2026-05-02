"""
prompt_manager.py — Prompt 模板加载与渲染

职责：
- 从 prompts/ 目录加载模板文件
- 支持变量占位符替换（{source_lang}, {target_lang}, {text} 等）
- 支持单条和批量 prompt 组装

用户可自由编辑模板文件来定制 prompt。
"""

import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 模板名称常量
TEMPLATE_TRANSLATE = "translate"
TEMPLATE_PARAPHRASE = "paraphrase"
TEMPLATE_BACKTRANSLATE = "backtranslate"
TEMPLATE_BATCH_WRAPPER = "batch_wrapper"


class PromptManager:
    """
    Prompt 模板加载与渲染。

    模板文件命名约定: {template_name}_{lang}.txt
    例如: translate_EN.txt, paraphrase_EN.txt

    支持的变量占位符:
        {source_lang}   — 源语言全称 (e.g. "English")
        {target_lang}   — 目标语言全称 (e.g. "Japanese")
        {text}          — 待翻译/改写的文本
        {tasks}         — 批量模式下的任务列表（自动生成）
        {output_format} — 批量模式下的输出格式（自动生成）
    """

    def __init__(self, prompts_dir: str, lang: str = "EN"):
        """
        Args:
            prompts_dir: 模板文件所在目录
            lang: 模板语言后缀 (e.g. "EN")
        """
        self.prompts_dir = prompts_dir
        self.lang = lang
        self._templates: dict[str, str] = {}
        self._load_templates()

    def _load_templates(self):
        """加载目录下所有匹配语言后缀的模板文件。"""
        suffix = f"_{self.lang}.txt"
        if not os.path.isdir(self.prompts_dir):
            raise FileNotFoundError(f"Prompts directory not found: {self.prompts_dir}")

        for fname in os.listdir(self.prompts_dir):
            if fname.endswith(suffix):
                name = fname[: -len(suffix)]  # e.g. "translate"
                path = os.path.join(self.prompts_dir, fname)
                with open(path, "r", encoding="utf-8") as f:
                    self._templates[name] = f.read()
                logger.debug("Loaded prompt template: %s from %s", name, path)

        logger.info(
            "Loaded %d prompt templates from %s (lang=%s)",
            len(self._templates), self.prompts_dir, self.lang,
        )

    # ------------------------------------------------------------------
    # 单条渲染
    # ------------------------------------------------------------------

    def render(self, template_name: str, **variables: Any) -> str:
        """
        渲染单条 prompt 模板。

        Args:
            template_name: 模板名称 ("translate", "paraphrase", "backtranslate")
            **variables: 变量替换（source_lang, target_lang, text 等）

        Returns:
            渲染后的 prompt 字符串
        """
        if template_name not in self._templates:
            raise KeyError(
                f"Template '{template_name}' not found. "
                f"Available: {list(self._templates.keys())}"
            )
        template = self._templates[template_name]
        try:
            return template.format(**variables)
        except KeyError as e:
            raise KeyError(
                f"Missing variable {e} in template '{template_name}'. "
                f"Provided: {list(variables.keys())}"
            ) from e

    # ------------------------------------------------------------------
    # 批量渲染
    # ------------------------------------------------------------------

    def render_batch(self, tasks: list[dict[str, Any]]) -> str:
        """
        将多个翻译任务组装为一个批量 prompt。

        Args:
            tasks: 任务列表，每个任务为 dict，包含:
                - task_id: int (1-based)
                - template_name: str
                - variables: dict (source_lang, target_lang, text, ...)

        Returns:
            组装后的完整 batch prompt
        """
        if TEMPLATE_BATCH_WRAPPER not in self._templates:
            raise KeyError(
                f"Batch wrapper template '{TEMPLATE_BATCH_WRAPPER}' not found."
            )

        # 构建各任务描述
        task_blocks: list[str] = []
        output_blocks: list[str] = []

        for task in tasks:
            tid = task["task_id"]
            rendered = self.render(task["template_name"], **task["variables"])
            task_blocks.append(f"=== Task {tid} ===\n{rendered}")
            output_blocks.append(f"=== Result {tid} ===\n[your output here]")

        tasks_str = "\n\n".join(task_blocks)
        output_str = "\n\n".join(output_blocks)

        return self._templates[TEMPLATE_BATCH_WRAPPER].format(
            tasks=tasks_str,
            output_format=output_str,
        )

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def get_template_name(self, source_lang: str, target_lang: str, is_backtranslation: bool, is_paraphrase: bool) -> str:
        """根据翻译参数自动选择模板名称。"""
        if is_paraphrase:
            return TEMPLATE_PARAPHRASE
        if is_backtranslation:
            return TEMPLATE_BACKTRANSLATE
        return TEMPLATE_TRANSLATE

    @property
    def available_templates(self) -> list[str]:
        return list(self._templates.keys())
