"""
collectors/__init__.py - 采集器工厂
"""
from src.collectors.base import BaseCollector, RssCollector, WikiCollector
from src.collectors.api_collectors import GuardianCollector, ArxivCollector
from src.models import SourceConfig, CollectionConfig


def make_collector(source: SourceConfig, collection_cfg: CollectionConfig) -> BaseCollector:
    """根据 source.type 返回对应采集器实例"""
    mapping = {
        "rss": RssCollector,
        "custom_rss": RssCollector,
        "api_guardian": GuardianCollector,
        "api_arxiv": ArxivCollector,
        "wiki": WikiCollector,
    }
    cls = mapping.get(source.type)
    if cls is None:
        raise ValueError(f"未知的采集器类型: {source.type!r}，支持: {list(mapping)}")
    return cls(source, collection_cfg)
