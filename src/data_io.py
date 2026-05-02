"""
data_io.py — 数据读取与结果写入

职责：
- 从 source_XX.md 解析段落（按 ID 前缀筛选）
- 将翻译链结果写为 JSON 和 Markdown
"""

import json
import os
import re
import logging
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SourceText:
    """一段源文本"""
    id: str             # e.g. "EN-1"
    language: str       # e.g. "EN"
    content: str        # 段落正文


class DataIO:
    """数据读取与结果写入"""

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    @staticmethod
    def load_source_texts(
        path: str,
        lang_prefix: str = "EN",
        count: int = 0,
    ) -> list[SourceText]:
        """
        从 source_XX.md 读取指定语言前缀的所有段落。

        文件格式约定：
            ID 行格式为 `^[A-Z]+-\\d+$`（如 EN-1, ZH-12）
            紧跟 ID 行的下一非空行为正文。

        Args:
            path: 源文件路径
            lang_prefix: 语言前缀，如 "EN"、"ZH"
            count: 读取前 N 条，0 表示全部

        Returns:
            SourceText 列表
        """
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Source file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        id_pattern = re.compile(r"^([A-Z]+)-(\d+)\s*$")
        texts: list[SourceText] = []
        i = 0

        while i < len(lines):
            match = id_pattern.match(lines[i].strip())
            if match:
                lang = match.group(1)
                text_id = f"{lang}-{match.group(2)}"

                # 收集 ID 行之后的所有非空行作为正文（直到下一个 ID 行或文件末尾）
                i += 1
                content_lines: list[str] = []
                while i < len(lines):
                    if id_pattern.match(lines[i].strip()):
                        break
                    content_lines.append(lines[i].rstrip())
                    i += 1

                content = "\n".join(content_lines).strip()

                if lang == lang_prefix and content:
                    texts.append(SourceText(id=text_id, language=lang, content=content))
            else:
                i += 1

        if count > 0:
            texts = texts[:count]

        logger.info(
            "Loaded %d source texts from %s (prefix=%s)",
            len(texts), path, lang_prefix,
        )
        return texts

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    @staticmethod
    def save_chain_result(result: dict[str, Any], output_dir: str, filename: str):
        """将单条翻译链结果保存为 JSON。"""
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.debug("Saved chain result to %s", path)

    @staticmethod
    def save_experiment_summary(
        results: list[dict[str, Any]],
        output_dir: str,
        group_name: str,
    ):
        """
        将一组实验结果汇总保存为：
        - JSONL（机器可读）
        - Markdown（人类可读）
        """
        os.makedirs(output_dir, exist_ok=True)

        # JSONL
        jsonl_path = os.path.join(output_dir, f"{group_name}.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        # Markdown
        md_path = os.path.join(output_dir, f"{group_name}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# {group_name}\n\n")
            for r in results:
                source_id = r.get("source_id", "?")
                chain = r.get("chain", [])
                texts = r.get("texts", {})
                f.write(f"## {source_id} — Chain: {'→'.join(chain)}\n\n")
                for key, text in texts.items():
                    f.write(f"### {key}\n\n{text}\n\n")
                f.write("---\n\n")

        logger.info(
            "Saved experiment summary for %s: %s, %s",
            group_name, jsonl_path, md_path,
        )
