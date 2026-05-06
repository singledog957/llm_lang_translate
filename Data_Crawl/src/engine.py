"""
engine.py - 采集引擎（协调采集、处理、写入、配额）
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Optional

from loguru import logger

from src.collectors import make_collector
from src.models import AppConfig, Article, SourceConfig
from src.processors.pipeline import ProcessingPipeline
from src.storage.writer import DatasetWriter


class QuotaManager:
    """跟踪并限制各维度的采集数量"""

    def __init__(self, cfg):
        limits = cfg.limits
        self.total_limit = limits.total
        self.per_source_limit = limits.per_source
        self.per_language_limit = limits.per_language
        self.per_domain_limit = limits.per_domain

        self._total = 0
        self._per_source: dict[str, int] = defaultdict(int)
        self._per_language: dict[str, int] = defaultdict(int)
        self._per_domain: dict[str, int] = defaultdict(int)

    def accept(self, article: Article) -> bool:
        src = article.source.name
        lang = article.language
        dom = article.domain

        if self.total_limit and self._total >= self.total_limit:
            return False
        if self.per_source_limit and self._per_source[src] >= self.per_source_limit:
            return False
        if self.per_language_limit and self._per_language[lang] >= self.per_language_limit:
            return False
        if self.per_domain_limit and self._per_domain[dom] >= self.per_domain_limit:
            return False
        return True

    def record(self, article: Article) -> None:
        self._total += 1
        self._per_source[article.source.name] += 1
        self._per_language[article.language] += 1
        self._per_domain[article.domain] += 1

    @property
    def total(self) -> int:
        return self._total

    def source_exhausted(self, source_name: str) -> bool:
        return bool(
            self.per_source_limit
            and self._per_source[source_name] >= self.per_source_limit
        )

    def all_exhausted(self) -> bool:
        return bool(self.total_limit and self._total >= self.total_limit)

    def summary(self) -> dict:
        return {
            "total": self._total,
            "by_language": dict(self._per_language),
            "by_domain": dict(self._per_domain),
            "by_source": dict(self._per_source),
        }


async def run_source(
    source: SourceConfig,
    cfg: AppConfig,
    pipeline: ProcessingPipeline,
    quota: QuotaManager,
    writer: DatasetWriter,
) -> int:
    """运行单个数据源，返回采集数量"""
    collected = 0
    try:
        collector = make_collector(source, cfg.collection)
    except ValueError as e:
        logger.error(f"[{source.name}] 初始化失败: {e}")
        return 0

    async with collector:
        try:
            async for raw_article in collector.collect():
                if quota.all_exhausted() or quota.source_exhausted(source.name):
                    break

                # 过滤不在目标语言列表的文章
                if (cfg.collection.languages
                        and raw_article.language not in cfg.collection.languages):
                    continue

                # 过滤不在目标领域列表的文章
                if (cfg.collection.domains
                        and raw_article.domain not in cfg.collection.domains):
                    continue

                article = pipeline.process(raw_article)
                if article is None:
                    continue

                if not quota.accept(article):
                    continue

                writer.write(article)
                quota.record(article)
                collected += 1
                logger.info(
                    f"[{source.name}] [{article.language}:{article.domain}] "
                    f"{article.title[:50]} ({article.word_count}词)"
                )
        except Exception as e:
            logger.error(f"[{source.name}] 采集出错: {e}", exc_info=True)

    logger.info(f"[{source.name}] 完成，本次采集 {collected} 条")
    return collected


async def run_collection(
    cfg: AppConfig,
    sources: list[SourceConfig],
    concurrency: int = 3,
) -> dict:
    """
    运行一次完整采集。
    concurrency: 同时并发的采集器数量（避免对同一域名并发过多）
    """
    enabled = [s for s in sources if s.enabled]
    if not enabled:
        logger.warning("没有启用的数据源")
        return {}

    logger.info(f"启动采集：{len(enabled)} 个来源，目标语言={cfg.collection.languages}，"
                f"目标领域={cfg.collection.domains}，总上限={cfg.collection.limits.total}")

    pipeline = ProcessingPipeline(cfg.processing, cfg.collection.languages)
    quota = QuotaManager(cfg.collection)
    writer = DatasetWriter(cfg.output)

    sem = asyncio.Semaphore(concurrency)

    async def bounded(source: SourceConfig) -> int:
        async with sem:
            return await run_source(source, cfg, pipeline, quota, writer)

    tasks = [bounded(s) for s in enabled]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for src, result in zip(enabled, results):
        if isinstance(result, Exception):
            logger.error(f"[{src.name}] 任务异常: {result}")

    writer.flush()
    summary = quota.summary()
    logger.info(f"采集完成 ✓  总计 {summary['total']} 条")
    logger.info(f"  按语言: {summary['by_language']}")
    logger.info(f"  按领域: {summary['by_domain']}")
    return summary
