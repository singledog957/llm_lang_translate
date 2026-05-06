"""
collectors/api_collectors.py - Guardian API、arXiv API 采集器
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

import httpx
from loguru import logger

from src.collectors.base import BaseCollector
from src.models import Article, ArticleSource, CollectionConfig, SourceConfig


class GuardianCollector(BaseCollector):
    """The Guardian Open Platform API（免费，无需付费）"""

    BASE_URL = "https://content.guardianapis.com/search"

    async def collect(self) -> AsyncIterator[Article]:
        if not self.source.api_key:
            logger.warning("[Guardian] 未配置 API Key，跳过。注册地址: https://open-platform.theguardian.com/")
            return

        domains = self.source.domains or ["politics"]
        page_size = self.source.extra.get("page_size", 50)

        for domain in domains:
            # Guardian section 映射
            section_map = {
                "politics": "politics",
                "technology": "technology",
                "science": "science",
                "culture": "culture",
                "health": "society",
                "finance": "business",
                "sport": "sport",
                "environment": "environment",
            }
            section = section_map.get(domain, domain)

            params: dict = {
                "api-key": self.source.api_key,
                "section": section,
                "show-fields": "bodyText,byline,wordcount",
                "page-size": page_size,
                "order-by": "newest",
            }

            # 时间范围
            start = self.collection_cfg.time_range.start_dt()
            end = self.collection_cfg.time_range.end_dt()
            if start:
                params["from-date"] = start.strftime("%Y-%m-%d")
            if end:
                params["to-date"] = end.strftime("%Y-%m-%d")

            logger.info(f"[Guardian] 采集 section={section}")
            try:
                resp = await self._client.get(self.BASE_URL, params=params)
                data = resp.json()
                results = data.get("response", {}).get("results", [])
            except Exception as e:
                logger.warning(f"[Guardian] 请求失败: {e}")
                continue

            for item in results:
                fields = item.get("fields", {})
                content = fields.get("bodyText", "")
                if not content or len(content.split()) < 80:
                    continue

                pub_str = item.get("webPublicationDate", "")

                yield Article(
                    source=ArticleSource(
                        name="The Guardian",
                        url=item.get("webUrl", ""),
                        type="api",
                        country="GB",
                    ),
                    language=self.source.language,
                    domain=domain,
                    title=item.get("webTitle", "").strip(),
                    content=content,
                    author=fields.get("byline", ""),
                    published_at=pub_str or None,
                    metadata={"guardian_id": item.get("id", "")},
                )


class ArxivCollector(BaseCollector):
    """arXiv API 采集器（学术论文摘要+正文）"""

    BASE_URL = "http://export.arxiv.org/api/query"

    async def collect(self) -> AsyncIterator[Article]:
        categories = self.source.extra.get("categories", ["cs.AI"])
        max_results = self.source.extra.get("max_results", 30)
        domain = self.source.domains[0] if self.source.domains else "science"

        for cat in categories:
            search_query = f"cat:{cat}"

            params = {
                "search_query": search_query,
                "max_results": max_results,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }

            start = self.collection_cfg.time_range.start_dt()
            end = self.collection_cfg.time_range.end_dt()

            logger.info(f"[arXiv] 采集 category={cat}")
            try:
                resp = await self._client.get(self.BASE_URL, params=params)
            except Exception as e:
                logger.warning(f"[arXiv] 请求失败: {e}")
                continue

            # arXiv 返回 Atom XML，用 feedparser 解析
            import feedparser
            parsed = feedparser.parse(resp.text)

            for entry in parsed.entries:
                pub_str = entry.get("published", "")
                pub_dt = None
                if pub_str:
                    try:
                        pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                    except Exception:
                        pass

                if not self._in_time_range(pub_dt):
                    continue

                title = entry.get("title", "").replace("\n", " ").strip()
                summary = entry.get("summary", "").replace("\n", " ").strip()

                if not summary or len(summary.split()) < 30:
                    continue

                # 拼接摘要作为正文（arXiv 正文需要 PDF 解析，这里用摘要）
                content = f"{title}\n\n{summary}"
                authors = ", ".join(
                    a.get("name", "") for a in entry.get("authors", [])
                )

                yield Article(
                    source=ArticleSource(
                        name="arXiv",
                        url=entry.get("link", ""),
                        type="api",
                        country="US",
                    ),
                    language=self.source.language,
                    domain=domain,
                    title=title,
                    content=content,
                    summary=summary,
                    author=authors,
                    published_at=pub_str or None,
                    metadata={
                        "arxiv_id": entry.get("id", ""),
                        "categories": [t.get("term", "") for t in entry.get("tags", [])],
                    },
                )
