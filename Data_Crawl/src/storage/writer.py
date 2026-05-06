"""
storage/writer.py - 数据写入（JSONL / Parquet）
"""
from __future__ import annotations

import gzip
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import IO

from loguru import logger

from src.models import Article, OutputConfig


class DatasetWriter:
    """
    按配置将 Article 写入 JSONL 或 Parquet 文件。
    支持按语言/领域分文件。
    """

    def __init__(self, cfg: OutputConfig):
        self.cfg = cfg
        self.base_path = Path(cfg.path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._handles: dict[str, IO] = {}
        self._counts: dict[str, int] = defaultdict(int)
        self._total = 0

        # Parquet 暂存
        self._parquet_buffer: dict[str, list[dict]] = defaultdict(list)

    def write(self, article: Article) -> None:
        key = self._get_key(article)
        record = article.model_dump()

        if self.cfg.format == "jsonl":
            handle = self._get_handle(key)
            line = json.dumps(record, ensure_ascii=False) + "\n"
            if self.cfg.compress:
                handle.write(line.encode("utf-8"))
            else:
                handle.write(line)
        else:  # parquet，先缓存
            self._parquet_buffer[key].append(record)

        self._counts[key] += 1
        self._total += 1

    def flush(self) -> None:
        """关闭所有文件句柄，并写出 Parquet（如需）"""
        for handle in self._handles.values():
            handle.close()
        self._handles.clear()

        if self.cfg.format == "parquet":
            self._flush_parquet()

        logger.info(f"写入完成，总计 {self._total} 条")
        for key, count in sorted(self._counts.items()):
            logger.info(f"  {key}: {count} 条")

    def stats(self) -> dict[str, int]:
        return {"total": self._total, **dict(self._counts)}

    # ── 内部工具 ─────────────────────────────────────────────

    def _get_key(self, article: Article) -> str:
        parts = []
        if self.cfg.split_by_language:
            parts.append(article.language)
        if self.cfg.split_by_domain:
            parts.append(article.domain)
        return "_".join(parts) if parts else "all"

    def _get_path(self, key: str) -> Path:
        if self.cfg.split_by_language:
            lang = key.split("_")[0]
            directory = self.base_path / lang
        else:
            directory = self.base_path
        directory.mkdir(parents=True, exist_ok=True)

        ext = ".jsonl.gz" if (self.cfg.format == "jsonl" and self.cfg.compress) else f".{self.cfg.format}"
        return directory / f"{key}{ext}"

    def _get_handle(self, key: str) -> IO:
        if key not in self._handles:
            path = self._get_path(key)
            if self.cfg.compress:
                self._handles[key] = gzip.open(path, "ab")
            else:
                self._handles[key] = open(path, "a", encoding="utf-8")
            logger.debug(f"打开输出文件: {path}")
        return self._handles[key]

    def _flush_parquet(self) -> None:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            logger.error("pyarrow 未安装，无法写出 Parquet，改为 JSONL")
            for key, records in self._parquet_buffer.items():
                path = self._get_path(key).with_suffix(".jsonl")
                with open(path, "w", encoding="utf-8") as f:
                    for r in records:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
            return

        for key, records in self._parquet_buffer.items():
            if not records:
                continue
            path = self._get_path(key)
            # 展平 nested dict
            flat_records = []
            for r in records:
                flat = {
                    "id": r["id"],
                    "source_name": r["source"]["name"],
                    "source_url": r["source"]["url"],
                    "source_type": r["source"]["type"],
                    "language": r["language"],
                    "domain": r["domain"],
                    "title": r["title"],
                    "content": r["content"],
                    "summary": r["summary"],
                    "author": r["author"],
                    "published_at": r["published_at"] or "",
                    "collected_at": r["collected_at"],
                    "word_count": r["word_count"],
                    "char_count": r["char_count"],
                }
                flat_records.append(flat)
            table = pa.Table.from_pylist(flat_records)
            pq.write_table(table, path, compression="snappy")
            logger.info(f"Parquet 写出: {path} ({len(flat_records)} 条)")
