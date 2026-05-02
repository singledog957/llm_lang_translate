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
import requests as _http
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
    finish_reason: str = ""                     # "stop" | "length" | "content_filter" | etc.


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
        api_mode: str = "completion",
        temperature: float = 0.0,
        max_tokens: int = 4096,
        retry_attempts: int = 3,
        retry_delay: float = 2.0,
        request_interval: float = 0.5,
        timeout: float = 60.0,
    ):
        self.model = model
        self.api_mode = api_mode
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.request_interval = request_interval
        self.timeout = timeout

        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=self.timeout)
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat_completion(
        self,
        messages: list[ChatMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> APIResponse:
        """
        发送一次 Chat Completion 请求并返回结果。

        Args:
            messages: 对话消息列表
            temperature: 覆盖默认 temperature（可选）
            max_tokens: 覆盖默认 max_tokens（可选）
            response_format: 响应格式配置，例如 {"type": "json_object"}

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
                
                if self.api_mode == "response":
                    # -------------------------------------------------------
                    # Responses API: POST directly to /v1/responses via
                    # requests (avoids SDK routing issues on third-party
                    # gateways that expose /v1/responses as a Codex endpoint).
                    # Falls back to /v1/chat/completions if output[] is empty.
                    # Ref: Cherry Studio OpenAIResponseAPIClient pattern.
                    # -------------------------------------------------------
                    http_headers = {
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    }
                    system_msgs = [m["content"] for m in msg_dicts if m["role"] == "system"]
                    input_msgs  = [m for m in msg_dicts if m["role"] != "system"]

                    resp_payload: dict = {"model": self.model}
                    if system_msgs:
                        resp_payload["instructions"] = "\n".join(system_msgs)
                    if len(input_msgs) == 1 and input_msgs[0]["role"] == "user":
                        # Compact form: single user turn → plain string input
                        resp_payload["input"] = input_msgs[0]["content"]
                    elif input_msgs:
                        resp_payload["input"] = input_msgs
                    if response_format:
                        resp_payload["text"] = {"format": response_format}

                    raw_content = None
                    finish_reason = ""
                    usage = {}
                    response_model = self.model

                    http_resp = _http.post(
                        f"{self._base_url}/responses",
                        headers=http_headers,
                        json=resp_payload,
                        timeout=self.timeout,
                    )
                    elapsed_ms = (time.time() - start) * 1000

                    if http_resp.status_code == 200:
                        data = http_resp.json()
                        response_model = data.get("model", self.model)
                        finish_reason = data.get("status", "")
                        u = data.get("usage", {})
                        usage = {
                            "prompt_tokens":     u.get("input_tokens",  u.get("prompt_tokens", 0)),
                            "completion_tokens": u.get("output_tokens", u.get("completion_tokens", 0)),
                            "total_tokens":      u.get("total_tokens", 0),
                        }
                        # Parse canonical Responses API output structure
                        for item in data.get("output", []):
                            if item.get("role") == "assistant":
                                for part in item.get("content", []):
                                    if part.get("type") == "output_text":
                                        raw_content = part.get("text")
                                        break
                                if raw_content is None and isinstance(item.get("content"), str):
                                    raw_content = item["content"]
                                if raw_content:
                                    break

                        if raw_content:
                            logger.debug("/v1/responses succeeded for model=%s", self.model)
                        else:
                            logger.warning(
                                "/v1/responses returned empty output[] (output_tokens=%s). "
                                "Falling back to /v1/chat/completions.",
                                usage.get("completion_tokens", "?")
                            )
                    else:
                        logger.warning(
                            "/v1/responses HTTP %s: %s — falling back to /v1/chat/completions.",
                            http_resp.status_code, http_resp.text[:200],
                        )

                    # Fallback: chat completions when responses endpoint fails/empty
                    if not raw_content:
                        fb_kwargs = {
                            "model": self.model,
                            "messages": msg_dicts,
                            "temperature": temp,
                            "max_tokens": tokens,
                        }
                        if response_format:
                            fb_kwargs["response_format"] = response_format
                        fb_start = time.time()
                        fb_resp = self._client.chat.completions.create(**fb_kwargs)
                        elapsed_ms = (time.time() - fb_start) * 1000
                        response_model = getattr(fb_resp, "model", self.model) or self.model
                        msg_obj = fb_resp.choices[0].message
                        raw_content = getattr(msg_obj, "content", None)
                        finish_reason = fb_resp.choices[0].finish_reason
                        if fb_resp.usage:
                            usage = {
                                "prompt_tokens":     fb_resp.usage.prompt_tokens,
                                "completion_tokens": fb_resp.usage.completion_tokens,
                                "total_tokens":      fb_resp.usage.total_tokens,
                            }

                    # Unified post-processing variable for the response block below
                    class _FakeResponse:
                        model = response_model
                    response = _FakeResponse()

                else:
                    # 构建请求参数
                    kwargs = {
                        "model": self.model,
                        "messages": msg_dicts,
                        "temperature": temp,
                        "max_tokens": tokens,
                    }
                    if response_format:
                        kwargs["response_format"] = response_format

                    response = self._client.chat.completions.create(**kwargs)
                    elapsed_ms = (time.time() - start) * 1000

                    msg_obj = response.choices[0].message
                    raw_content = getattr(msg_obj, "content", None)
                    finish_reason = response.choices[0].finish_reason
                    
                    # 特殊处理：某些推理模型（如 DeepSeek-R1）可能将内容放在 reasoning_content 中
                    reasoning_content = getattr(msg_obj, "reasoning_content", None)
                    
                    if (raw_content is None or raw_content.strip() == "") and reasoning_content:
                        logger.info("Content is empty but found reasoning_content. Using reasoning_content as fallback.")
                        raw_content = reasoning_content

                    usage = {}
                    if response.usage:
                        usage = {
                            "prompt_tokens": response.usage.prompt_tokens,
                            "completion_tokens": response.usage.completion_tokens,
                            "total_tokens": response.usage.total_tokens,
                        }

                if raw_content is None or raw_content.strip() == "":
                    # 打印完整响应以供 Debug
                    import json
                    try:
                        # 尝试获取底层的 dict，以防 SDK 过滤了非标准字段
                        full_dict = response.model_dump()
                        full_resp_log = json.dumps(full_dict, indent=2, ensure_ascii=False)
                        
                        # 检查 choices[0].message 中是否有任何非 None 的字段
                        msg_dict = full_dict.get("choices", [{}])[0].get("message", {})
                        found_fields = [k for k, v in msg_dict.items() if v is not None and k != "role"]
                        if found_fields:
                            logger.warning(f"Message content is null, but found other fields: {found_fields}")
                    except:
                        full_resp_log = str(response)
                        
                    logger.warning(f"Received empty content from API. Full response: {full_resp_log}")
                    raise ValueError(f"Empty content received from model {self.model}. Finish reason: {finish_reason}. Usage: {usage}")
                
                content = raw_content.strip()
                
                self._last_request_time = time.time()
                logger.debug(
                    "API call succeeded: model=%s, tokens=%s, finish_reason=%s, latency=%.0fms",
                    self.model, usage.get("total_tokens", "?"), finish_reason, elapsed_ms,
                )
                return APIResponse(
                    content=content,
                    usage=usage,
                    model=getattr(response, "model", self.model) or self.model,
                    latency_ms=elapsed_ms,
                    finish_reason=finish_reason or "",
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
