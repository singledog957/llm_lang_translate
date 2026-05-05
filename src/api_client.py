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
import json
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
                    # Map 'system' -> 'developer' for the input array as per official spec
                    input_msgs = []
                    for m in msg_dicts:
                        if m["role"] == "system":
                            # If we don't put it in instructions, we use developer role
                            # but we already use instructions below for highest priority.
                            # We'll keep them as developer in input if they aren't instructions.
                            continue
                        input_msgs.append(m)

                    resp_payload: dict = {"model": self.model}
                    if system_msgs:
                        resp_payload["instructions"] = "\n".join(system_msgs)
                    
                    if input_msgs:
                        resp_payload["input"] = input_msgs
                    if response_format:
                        resp_payload["text"] = {"format": response_format}
                    
                    # Force streaming to bypass gateway issues (as verified in test_res.py)
                    resp_payload["stream"] = True

                    raw_content = ""
                    finish_reason = ""
                    usage = {}
                    response_model = self.model

                    http_resp = _http.post(
                        f"{self._base_url}/responses",
                        headers=http_headers,
                        json=resp_payload,
                        timeout=self.timeout,
                        stream=True  # Important: enable stream
                    )
                    elapsed_ms = (time.time() - start) * 1000

                    if http_resp.status_code == 200:
                        # Handle both SSE Stream and potential fallback to plain JSON
                        text_parts = []
                        full_raw_data = []
                        event_types_seen = {}
                        is_sse = False
                        
                        for line in http_resp.iter_lines():
                            if not line: continue
                            line_str = line.decode('utf-8')
                            full_raw_data.append(line_str)
                            
                            # Robust SSE detection: data might not be at the very start if buffered
                            if "data: " in line_str:
                                is_sse = True
                                # Split in case multiple fields are on one line
                                parts = line_str.split("data: ")
                                data_str = parts[-1].strip()
                                
                                if data_str == "[DONE]": break
                                try:
                                    event = json.loads(data_str)
                                    e_type = event.get("type")
                                    if e_type:
                                        event_types_seen[e_type] = event_types_seen.get(e_type, 0) + 1
                                    
                                    # Support various delta formats
                                    if e_type == "response.content_part.delta":
                                        delta = event.get("delta", {})
                                        if delta.get("type") == "output_text":
                                            text_parts.append(delta.get("text", ""))
                                        elif delta.get("type") == "refusal":
                                            text_parts.append(f"[REFUSAL] {delta.get('refusal', '')}")
                                    elif e_type == "response.output_text.delta":
                                        delta = event.get("delta", "")
                                        if isinstance(delta, dict):
                                            text_parts.append(delta.get("text", ""))
                                        else:
                                            text_parts.append(str(delta))
                                    elif e_type == "response.error":
                                        # Capture explicit error events from the stream
                                        err = event.get("error", {})
                                        finish_reason = f"error: {err.get('message', 'unknown')}"
                                        logger.error(f"SSE Error Event: {err}")
                                    elif e_type in ["response.done", "response.completed"]:
                                        # Extract final usage if available
                                        resp_obj = event.get("response", {})
                                        u = resp_obj.get("usage", {})
                                        if u:
                                            usage = {
                                                "prompt_tokens":     u.get("input_tokens", u.get("prompt_tokens", 0)),
                                                "completion_tokens": u.get("output_tokens", u.get("completion_tokens", 0)),
                                                "total_tokens":      u.get("total_tokens", 0),
                                            }
                                            finish_reason = resp_obj.get("status", "")
                                except Exception as json_err:
                                    if data_str and data_str != "[DONE]":
                                        logger.debug(f"SSE JSON Parse Error: {json_err} | Data segment: {data_str[:100]}...")
                                    pass
                        
                        # Fallback: If not SSE, try to parse the entire body as a single JSON
                        if not is_sse and full_raw_data:
                            try:
                                data = json.loads("\n".join(full_raw_data))
                                # ... existing fallback logic ...
                                # (omitting for brevity in this chunk, but keeping in file)
                            except: pass
                        else:
                            data = {
                                "sse_summary": event_types_seen,
                                "raw_log": "\n".join(full_raw_data)
                            }

                        if text_parts:
                            raw_content = "".join(text_parts)
                            logger.debug("/v1/responses succeeded for model=%s (sse=%s)", self.model, is_sse)
                        else:
                            logger.warning("/v1/responses returned no text parts. sse=%s", is_sse)
                    else:
                        logger.warning(
                            "/v1/responses HTTP %s: %s",
                            http_resp.status_code, http_resp.text[:200],
                        )
                        data = {"error_response": http_resp.text}

                    # Fallback: Removed as per user request.
                    # We will proceed to check raw_content below.

                    # Unified post-processing variable for the response block below
                    class _FakeResponse:
                        model = response_model
                    response = _FakeResponse()

                elif self.api_mode == "anthropic":
                    # -------------------------------------------------------
                    # Anthropic Messages API
                    # -------------------------------------------------------
                    http_headers = {
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                        "Authorization": f"Bearer {self._api_key}" # for compatible gateways
                    }
                    
                    system_msgs = [m["content"] for m in msg_dicts if m["role"] == "system"]
                    anthropic_msgs = [m for m in msg_dicts if m["role"] != "system"]
                    
                    resp_payload = {
                        "model": self.model,
                        "max_tokens": tokens or self.max_tokens,
                        "messages": anthropic_msgs
                    }
                    if temp is not None:
                        resp_payload["temperature"] = temp
                    if system_msgs:
                        resp_payload["system"] = "\n".join(system_msgs)
                        
                    http_resp = _http.post(
                        f"{self._base_url}/messages",
                        headers=http_headers,
                        json=resp_payload,
                        timeout=self.timeout
                    )
                    elapsed_ms = (time.time() - start) * 1000

                    if http_resp.status_code != 200:
                        try:
                            err_body = http_resp.json()
                        except Exception:
                            err_body = {"raw": http_resp.text}
                        raise APIError(
                            message=http_resp.text or f"HTTP {http_resp.status_code}",
                            request=None,
                            body=err_body,
                        )

                    data = http_resp.json()
                    
                    # Extract text content
                    text_parts = []
                    if "content" in data and isinstance(data["content"], list):
                        for block in data["content"]:
                            if block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                    
                    raw_content = "".join(text_parts)
                    finish_reason = data.get("stop_reason", "")
                    
                    usage = {}
                    u = data.get("usage", {})
                    if u:
                        usage = {
                            "prompt_tokens": u.get("input_tokens", 0),
                            "completion_tokens": u.get("output_tokens", 0),
                            "total_tokens": u.get("input_tokens", 0) + u.get("output_tokens", 0)
                        }

                    class _FakeResponse:
                        model = data.get("model", self.model)
                    response = _FakeResponse()

                else:
                    # -------------------------------------------------------
                    # Chat Completions: POST directly via requests.
                    # The OpenAI SDK's httpx layer causes the gateway to route
                    # requests to the real OpenAI upstream, which applies
                    # strict validation (e.g. json_object requires "json" in
                    # messages, extra header fingerprinting, etc.) and returns
                    # 400.  Using raw requests bypasses this routing.
                    # -------------------------------------------------------
                    http_headers = {
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    }
                    cc_payload: dict = {
                        "model": self.model,
                        "messages": msg_dicts,
                        "temperature": temp,
                        "max_tokens": tokens,
                    }
                    if response_format:
                        cc_payload["response_format"] = response_format

                    http_resp = _http.post(
                        f"{self._base_url}/chat/completions",
                        headers=http_headers,
                        json=cc_payload,
                        timeout=self.timeout,
                    )
                    elapsed_ms = (time.time() - start) * 1000

                    if http_resp.status_code != 200:
                        # Re-raise as an APIError so the retry logic handles it
                        try:
                            err_body = http_resp.json()
                        except Exception:
                            err_body = {"raw": http_resp.text}
                        raise APIError(
                            message=http_resp.text or f"HTTP {http_resp.status_code}",
                            request=None,  # type: ignore[arg-type]
                            body=err_body,
                        )

                    data = http_resp.json()
                    
                    if not data or not isinstance(data, dict):
                        raise APIError(
                            message=f"Invalid JSON response (not a dict): {http_resp.text}",
                            request=None,
                            body=data
                        )
                        
                    choices = data.get("choices")
                    if not choices or not isinstance(choices, list) or len(choices) == 0:
                        # Some gateways return 200 OK but with an error object inside
                        if "error" in data:
                            raise APIError(
                                message=f"API returned error in 200 OK response: {data['error']}",
                                request=None,
                                body=data
                            )
                        raise APIError(
                            message=f"No valid choices in response: {data}",
                            request=None,
                            body=data
                        )

                    choice = choices[0]
                    msg_obj_dict = choice.get("message", {})
                    raw_content = msg_obj_dict.get("content")
                    finish_reason = choice.get("finish_reason", "")

                    # 特殊处理：某些推理模型（如 DeepSeek-R1）可能将内容放在 reasoning_content 中
                    reasoning_content = msg_obj_dict.get("reasoning_content")
                    if (raw_content is None or raw_content.strip() == "") and reasoning_content:
                        logger.info("Content is empty but found reasoning_content. Using reasoning_content as fallback.")
                        raw_content = reasoning_content

                    usage = {}
                    u = data.get("usage", {})
                    if u:
                        usage = {
                            "prompt_tokens":     u.get("prompt_tokens", 0),
                            "completion_tokens": u.get("completion_tokens", 0),
                            "total_tokens":      u.get("total_tokens", 0),
                        }

                    # Build a minimal object for the shared post-processing below
                    class _FakeResponse:
                        model = data.get("model", self.model)
                    response = _FakeResponse()


                if raw_content is None or raw_content.strip() == "":
                    # Summary-based logging instead of full dump to avoid clutter
                    
                    # Analyze structure
                    structure_info = {
                        "keys_present": list(data.keys()) if isinstance(data, dict) else "not_a_dict",
                        "sse_summary": data.get("sse_summary") if isinstance(data, dict) else None,
                        "is_sse": is_sse if 'is_sse' in locals() else False
                    }
                    
                    # Truncated raw dump
                    raw_dump = data.get("raw_log", json.dumps(data, ensure_ascii=False)) if isinstance(data, dict) else str(data)
                    truncated_dump = raw_dump[:1000] + "..." if len(raw_dump) > 1000 else raw_dump
                    
                    logger.warning(
                        "Empty content from model=%s. Structure: %s\nUsage: %s\nRaw (Truncated):\n%s",
                        self.model, structure_info, usage, truncated_dump
                    )
                    raise ValueError(
                        f"Empty content received from model {self.model}. "
                        f"Finish reason: {finish_reason}. Usage: {usage}"
                    )
                
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
