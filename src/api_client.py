"""
api_client.py — OpenAI Chat Completion API 封装

职责：
- 封装 OpenAI SDK 的同步调用
- 提供重试与错误处理
- 不维护状态，每次调用独立

所有请求串行发送，不做并发。
"""

import time
import logging
from dataclasses import dataclass, field
from openai import OpenAI, APIError, RateLimitError, APIConnectionError

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """单条对话消息"""
    role: str       # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class APIResponse:
    """API 调用响应"""
    content: str
    usage: dict = field(default_factory=dict)   # token 用量
    model: str = ""
    latency_ms: float = 0.0


class APIClient:
    """
    OpenAI-compatible Chat Completion 客户端。

    使用方式：
        client = APIClient(base_url="...", api_key="...", model="gpt-4o")
        resp = client.chat_completion([ChatMessage("user", "Hello")])
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        retry_attempts: int = 3,
        retry_delay: float = 2.0,
        request_interval: float = 0.5,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.request_interval = request_interval

        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat_completion(
        self,
        messages: list[ChatMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> APIResponse:
        """
        发送一次 Chat Completion 请求并返回结果。

        Args:
            messages: 对话消息列表
            temperature: 覆盖默认 temperature（可选）
            max_tokens: 覆盖默认 max_tokens（可选）

        Returns:
            APIResponse 包含回复文本、token 用量等
        """
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens
        msg_dicts = [m.to_dict() for m in messages]

        self._wait_for_interval()

        for attempt in range(1, self.retry_attempts + 1):
            try:
                start = time.time()
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=msg_dicts,
                    temperature=temp,
                    max_tokens=tokens,
                )
                elapsed_ms = (time.time() - start) * 1000

                content = response.choices[0].message.content.strip()
                usage = {}
                if response.usage:
                    usage = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    }

                self._last_request_time = time.time()
                logger.debug(
                    "API call succeeded: model=%s, tokens=%s, latency=%.0fms",
                    self.model, usage.get("total_tokens", "?"), elapsed_ms,
                )
                return APIResponse(
                    content=content,
                    usage=usage,
                    model=response.model or self.model,
                    latency_ms=elapsed_ms,
                )

            except RateLimitError as e:
                wait = self.retry_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Rate limited (attempt %d/%d), waiting %.1fs: %s",
                    attempt, self.retry_attempts, wait, e,
                )
                time.sleep(wait)

            except (APIError, APIConnectionError) as e:
                wait = self.retry_delay * (2 ** (attempt - 1))
                logger.warning(
                    "API error (attempt %d/%d), waiting %.1fs: %s",
                    attempt, self.retry_attempts, wait, e,
                )
                time.sleep(wait)

        raise RuntimeError(
            f"API call failed after {self.retry_attempts} attempts"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _wait_for_interval(self):
        """确保两次请求之间的最小间隔。"""
        if self._last_request_time > 0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.request_interval:
                time.sleep(self.request_interval - elapsed)
