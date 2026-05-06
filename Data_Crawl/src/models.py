"""
models.py - 核心数据模型与配置加载
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


# ── 数据模型 ─────────────────────────────────────────────────

class ArticleSource(BaseModel):
    name: str
    url: str = ""
    type: str = "unknown"
    country: str = ""

class Article(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: ArticleSource
    language: str
    domain: str
    title: str
    content: str
    summary: str = ""
    author: str = ""
    published_at: Optional[str] = None
    collected_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    word_count: int = 0
    char_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not self.word_count:
            self.word_count = len(self.content.split())
        if not self.char_count:
            self.char_count = len(self.content)


# ── 配置模型 ─────────────────────────────────────────────────

class TimeRange(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None

    def start_dt(self) -> Optional[datetime]:
        if not self.start: return None
        if len(self.start) == 10:
            return datetime.fromisoformat(self.start + "T00:00:00+00:00")
        return datetime.fromisoformat(self.start)

    def end_dt(self) -> Optional[datetime]:
        if not self.end: return None
        if len(self.end) == 10:
            return datetime.fromisoformat(self.end + "T23:59:59+00:00")
        return datetime.fromisoformat(self.end)

class Limits(BaseModel):
    total: int = 0
    per_source: int = 0
    per_language: int = 0
    per_domain: int = 0

class Schedule(BaseModel):
    mode: str = "once"
    interval_hours: int = 12

class CollectionConfig(BaseModel):
    time_range: TimeRange = Field(default_factory=TimeRange)
    languages: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)
    schedule: Schedule = Field(default_factory=Schedule)

class ProcessingConfig(BaseModel):
    min_word_count: int = 80
    max_word_count: int = 50000
    dedup_enabled: bool = True
    dedup_window: int = 10000
    lang_confidence: float = 0.80

class OutputConfig(BaseModel):
    format: str = "jsonl"
    path: str = "./datasets"
    split_by_language: bool = True
    split_by_domain: bool = False
    compress: bool = False

class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "./logs/collector.log"

class AppConfig(BaseModel):
    collection: CollectionConfig
    processing: ProcessingConfig
    output: OutputConfig
    logging: LoggingConfig


# ── 数据源配置模型 ────────────────────────────────────────────

class FeedEntry(BaseModel):
    url: str
    domain_hint: str = ""

class SourceConfig(BaseModel):
    name: str
    type: str
    enabled: bool = True
    language: str
    domains: list[str] = Field(default_factory=list)
    api_key: str = ""
    url: str = ""
    feeds: list[FeedEntry] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        # 展开环境变量
        if self.api_key.startswith("${") and self.api_key.endswith("}"):
            env_var = self.api_key[2:-1]
            self.api_key = os.getenv(env_var, "")


# ── 配置加载 ─────────────────────────────────────────────────

def load_config(path: str) -> AppConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return AppConfig(**raw)

def load_sources(path: str) -> list[SourceConfig]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return [SourceConfig(**s) for s in raw.get("sources", [])]
