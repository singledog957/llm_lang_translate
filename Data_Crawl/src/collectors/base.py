"""
collectors/base.py - 采集器基类 + RSS采集器 + Wikipedia采集器
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import feedparser
import httpx
import trafilatura
from loguru import logger

from src.models import Article, ArticleSource, SourceConfig, CollectionConfig


class BaseCollector(ABC):
    """所有采集器的基类"""

    def __init__(self, source: SourceConfig, collection_cfg: CollectionConfig):
        self.source = source
        self.collection_cfg = collection_cfg
        self._client = httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (research bot; contact@example.com)"},
            follow_redirects=True,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    @abstractmethod
    async def collect(self) -> AsyncIterator[Article]:
        """产出 Article 对象"""
        ...

    def _in_time_range(self, pub_dt: Optional[datetime]) -> bool:
        """检查发布时间是否在配置的时间范围内"""
        if pub_dt is None:
            return True  # 无法确定时间，默认接受
        # 确保 pub_dt 有时区信息
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)

        start = self.collection_cfg.time_range.start_dt()
        end = self.collection_cfg.time_range.end_dt()

        if start and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        if start and pub_dt < start:
            return False
        if end and pub_dt > end:
            return False
        return True

    async def _fetch_full_text(self, url: str) -> str:
        """用 trafilatura 抓取并提取正文"""
        try:
            resp = await self._client.get(url)
            text = trafilatura.extract(
                resp.text,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )
            return text or ""
        except Exception as e:
            logger.debug(f"fetch_full_text failed for {url}: {e}")
            return ""


class RssCollector(BaseCollector):
    """RSS/Atom 订阅采集器"""

    async def collect(self) -> AsyncIterator[Article]:
        for feed_entry in self.source.feeds:
            async for article in self._collect_feed(feed_entry.url, feed_entry.domain_hint):
                yield article

    async def _collect_feed(self, feed_url: str, domain_hint: str) -> AsyncIterator[Article]:
        logger.info(f"[RSS] {self.source.name} → {feed_url}")
        try:
            resp = await self._client.get(feed_url)
            parsed = feedparser.parse(resp.text)
        except Exception as e:
            logger.warning(f"[RSS] 无法获取 {feed_url}: {e}")
            return

        for entry in parsed.entries:
            # 解析发布时间
            pub_dt = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except Exception:
                    pass

            if not self._in_time_range(pub_dt):
                continue

            url = entry.get("link", "")
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()

            # 尝试从 feed 正文字段获取内容，再 fallback 到全文抓取
            content = ""
            for field in ("content", "summary_detail", "description"):
                val = entry.get(field)
                if isinstance(val, list) and val:
                    content = trafilatura.extract(val[0].get("value", "")) or ""
                elif isinstance(val, str):
                    content = trafilatura.extract(val) or ""
                if content:
                    break

            # 若内容太短，尝试抓取原文
            if len(content) < 250 and url:
                content = await self._fetch_full_text(url)

            if not content or not title:
                continue

            domain = domain_hint or (self.source.domains[0] if self.source.domains else "unknown")
            pub_str = pub_dt.isoformat() + "Z" if pub_dt else None

            yield Article(
                source=ArticleSource(
                    name=self.source.name,
                    url=url,
                    type="rss",
                ),
                language=self.source.language,
                domain=domain,
                title=title,
                content=content,
                summary=summary,
                author=entry.get("author", ""),
                published_at=pub_str,
                metadata={"feed_url": feed_url},
            )


class WikiCollector(BaseCollector):
    """Wikipedia 随机文章采集器（通过 MediaWiki API）"""

    async def collect(self) -> AsyncIterator[Article]:
        wiki_lang = self.source.extra.get("wiki_lang", "en")
        count = self.source.extra.get("count", 20)
        api_url = f"https://{wiki_lang}.wikipedia.org/w/api.php"
        domain = self.source.domains[0] if self.source.domains else "culture"

        fetched = 0
        while fetched < count:
            try:
                # 获取随机页面列表
                resp = await self._client.get(api_url, params={
                    "action": "query",
                    "list": "random",
                    "rnnamespace": 0,
                    "rnlimit": min(10, count - fetched),
                    "format": "json",
                })
                data = resp.json()
                pages = data.get("query", {}).get("random", [])
            except Exception as e:
                logger.warning(f"[Wiki] API 请求失败: {e}")
                break

            for page in pages:
                page_id = page["id"]
                title = page["title"]
                try:
                    # 获取页面正文（纯文本）
                    content_resp = await self._client.get(api_url, params={
                        "action": "query",
                        "pageids": page_id,
                        "prop": "extracts",
                        "exintro": False,
                        "explaintext": True,
                        "format": "json",
                    })
                    cdata = content_resp.json()
                    extract = cdata["query"]["pages"][str(page_id)].get("extract", "")
                    if not extract or len(extract) < 150:
                        continue

                    page_url = f"https://{wiki_lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
                    yield Article(
                        source=ArticleSource(
                            name=f"Wikipedia ({wiki_lang.upper()})",
                            url=page_url,
                            type="wiki",
                        ),
                        language=self.source.language,
                        domain=domain,
                        title=title,
                        content=extract[:10000],
                        metadata={"page_id": page_id},
                    )
                    fetched += 1
                except Exception as e:
                    logger.debug(f"[Wiki] 获取页面 {title} 失败: {e}")

            await asyncio.sleep(0.5)
