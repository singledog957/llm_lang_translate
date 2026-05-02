"""
logger.py — 实验过程记录器

职责：
- 记录每次 API 调用的完整信息（prompt、response、token 用量等）
- 追踪实验进度，支持断点续做
- 输出 JSONL 格式日志
"""

import json
import os
import time
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class ExperimentLogger:
    """
    实验过程记录器。

    日志存储结构:
        {log_dir}/
        ├── api_calls.jsonl          # 所有 API 调用记录
        ├── progress.json            # 进度追踪（断点续做）
        └── summary.json             # 实验摘要
    """

    def __init__(self, log_dir: str, model_name: str = ""):
        self.log_dir = log_dir
        self.model_name = model_name
        os.makedirs(log_dir, exist_ok=True)

        self._api_log_path = os.path.join(log_dir, "api_calls.jsonl")
        self._progress_path = os.path.join(log_dir, "progress.json")
        self._summary_path = os.path.join(log_dir, "summary.json")

        # 统计
        self._total_calls = 0
        self._total_tokens = 0
        self._start_time = time.time()

    # ------------------------------------------------------------------
    # API 调用记录
    # ------------------------------------------------------------------

    def log_api_call(
        self,
        group_name: str,
        source_id: str,
        step_desc: str,
        prompt: str,
        response: str,
        usage: dict | None = None,
        latency_ms: float = 0.0,
        metadata: dict | None = None,
    ):
        """
        记录一次 API 调用。

        Args:
            group_name: 实验组名
            source_id: 源文本 ID
            step_desc: 步骤描述 (e.g. "EN→JA", "JA→EN backtranslation")
            prompt: 发送的完整 prompt
            response: 收到的回复
            usage: token 用量
            latency_ms: 响应延迟
            metadata: 额外元数据
        """
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": self.model_name,
            "group": group_name,
            "source_id": source_id,
            "step": step_desc,
            "prompt_length": len(prompt),
            "response_length": len(response),
            "usage": usage or {},
            "latency_ms": round(latency_ms, 1),
            "prompt": prompt,
            "response": response,
        }
        if metadata:
            record["metadata"] = metadata

        with open(self._api_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        self._total_calls += 1
        if usage:
            self._total_tokens += usage.get("total_tokens", 0)

    # ------------------------------------------------------------------
    # 进度追踪
    # ------------------------------------------------------------------

    def save_progress(self, progress: dict[str, Any]):
        """
        保存当前进度（用于断点续做）。

        Args:
            progress: 进度信息，格式自定义，例如:
                {
                    "completed": {"EN-1": ["group1", "group2"], "EN-2": ["group1"]},
                    "last_source_id": "EN-2",
                    "last_group": "group1",
                }
        """
        progress["updated_at"] = datetime.now(timezone.utc).isoformat()
        progress["model"] = self.model_name

        with open(self._progress_path, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)

    def load_progress(self) -> dict[str, Any]:
        """加载上次保存的进度。"""
        if not os.path.isfile(self._progress_path):
            return {}
        with open(self._progress_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def is_completed(self, source_id: str, group_name: str) -> bool:
        """检查某个 (source_id, group_name) 组合是否已完成。"""
        progress = self.load_progress()
        completed = progress.get("completed", {})
        return group_name in completed.get(source_id, [])

    def mark_completed(self, source_id: str, group_name: str):
        """标记某个 (source_id, group_name) 组合为已完成。"""
        progress = self.load_progress()
        completed = progress.setdefault("completed", {})
        groups = completed.setdefault(source_id, [])
        if group_name not in groups:
            groups.append(group_name)
        self.save_progress(progress)

    # ------------------------------------------------------------------
    # 实验摘要
    # ------------------------------------------------------------------

    def save_summary(self, extra: dict | None = None):
        """保存实验摘要统计。"""
        elapsed = time.time() - self._start_time
        summary = {
            "model": self.model_name,
            "total_api_calls": self._total_calls,
            "total_tokens": self._total_tokens,
            "elapsed_seconds": round(elapsed, 1),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            summary.update(extra)

        with open(self._summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        logger.info(
            "Experiment summary: %d API calls, %d tokens, %.1fs elapsed",
            self._total_calls, self._total_tokens, elapsed,
        )
