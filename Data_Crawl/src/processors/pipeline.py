"""
processors/pipeline.py - 文本处理管线（语言检测、过滤、去重）
"""
from __future__ import annotations

import hashlib
from collections import deque
from typing import Optional

from langdetect import detect, LangDetectException
from loguru import logger

from src.models import Article, ProcessingConfig
from src.processors.domain_picker import DomainPicker


class ProcessingPipeline:
    """
    依次对 Article 执行：
      1. 语言检测（可选，用于修正或过滤）
      2. 长度过滤
      3. 去重（基于内容哈希滑动窗口）
    """

    def __init__(self, cfg: ProcessingConfig, target_languages: list[str]):
        self.cfg = cfg
        self.target_languages = set(target_languages)
        # 滑动窗口去重
        self._seen: deque[str] = deque(maxlen=cfg.dedup_window)
        self._seen_set: set[str] = set()
        
        # 初始化领域分类器
        self.domain_picker = DomainPicker()

    def process(self, article: Article) -> Optional[Article]:
        """
        处理单篇文章。返回 None 表示丢弃。
        """
        # 1. 长度过滤
        if article.language in ("zh", "ja"):
            wc = len(article.content.replace(" ", "").replace("\n", ""))
        else:
            wc = len(article.content.split())

        if wc < self.cfg.min_word_count:
            logger.debug(f"丢弃（过短 {wc} 词）: {article.title[:40]}")
            return None
        if wc > self.cfg.max_word_count:
            article.content = article.content[:self.cfg.max_word_count * 5]  # 粗略截断
            logger.debug(f"截断至 {self.cfg.max_word_count} 词: {article.title[:40]}")

        # 2. 语言检测与过滤
        detected = self._detect_lang(article.content)
        if detected:
            article.metadata["detected_language"] = detected
            # 如果检测结果与声明语言不符，标记但不丢弃（可能是双语文章）
            if detected != article.language:
                logger.debug(
                    f"语言不符（声明={article.language}, 检测={detected}）: {article.title[:40]}"
                )
            # 若检测语言完全不在目标列表，且与声明语言也不符，则丢弃
            if (detected not in self.target_languages
                    and article.language not in self.target_languages):
                logger.debug(f"丢弃（语言不在目标列表）: {article.title[:40]}")
                return None

        # 3. 去重
        if self.cfg.dedup_enabled:
            content_hash = self._hash(article.title + article.content[:500])
            if content_hash in self._seen_set:
                logger.debug(f"丢弃（重复）: {article.title[:40]}")
                return None
            # 维护滑动窗口：弹出最旧的
            if len(self._seen) == self._seen.maxlen:
                oldest = self._seen[0]
                self._seen_set.discard(oldest)
            self._seen.append(content_hash)
            self._seen_set.add(content_hash)

        # 更新字数
        article.word_count = len(article.content.split())
        article.char_count = len(article.content)

        # 4. 基于关键词策略的领域二次判定
        picked_domain = self.domain_picker.pick_domain(
            title=article.title, 
            summary=article.summary, 
            content=article.content
        )
        # 仅当判定结果非 unknown 时覆盖原有的 domain_hint
        if picked_domain != "unknown":
            article.domain = picked_domain

        return article

    def _detect_lang(self, text: str) -> Optional[str]:
        try:
            return detect(text[:2000])
        except LangDetectException:
            return None

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()
