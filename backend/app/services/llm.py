"""OpenAI-compatible LLM client used for enrichment and digest generation."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class LLMUsage:
    """Token 消耗累计(来自 OpenAI 兼容响应的 usage 字段)。"""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }

    def add(self, usage: dict[str, Any] | None) -> None:
        self.calls += 1
        if not isinstance(usage, dict):
            return
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)
        self.total_tokens += int(usage.get("total_tokens") or 0)


def usage_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    """两次数快照之差,用于把 token 消耗归因到采集阶段。"""
    keys = ("calls", "prompt_tokens", "completion_tokens", "total_tokens")
    return {key: int(after.get(key) or 0) - int(before.get(key) or 0) for key in keys}


class LLMNotConfiguredError(RuntimeError):
    """Raised when no usable LLM configuration is available."""


class LLMError(RuntimeError):
    """Raised when the upstream LLM request fails or returns malformed data."""


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

# 网关不认识 `thinking` 时的典型报错(OpenAI 官方会直接 400 说参数不认识)。
_THINKING_REJECT_RE = re.compile(
    r"thinking|unrecogni[sz]ed|unknown (?:argument|parameter|field|key)|unsupported",
    re.IGNORECASE,
)


def parse_json_content(text: str) -> Any:
    """Best-effort JSON extraction from an LLM response."""
    text = (text or "").strip()
    if not text:
        raise LLMError("empty LLM response")
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if starts:
        start = min(starts)
        end = max(text.rfind("}"), text.rfind("]"))
        if end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    raise LLMError(f"cannot parse JSON from LLM response: {text[:200]}")


def normalize_base_url(base_url: str) -> str:
    """Accept the common flavours of an OpenAI-compatible base URL.

    Trims whitespace and trailing slashes, drops a trailing
    ``/chat/completions`` copied from the docs, and appends ``/v1`` when the URL
    carries no path (``https://api.openai.com`` -> ``https://api.openai.com/v1``).
    """
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return ""
    suffix = "/chat/completions"
    if url.endswith(suffix):
        url = url[: -len(suffix)]
    if not httpx.URL(url).path.strip("/"):
        url = f"{url}/v1"
    return url


class LLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 180.0,
        disable_thinking: bool = True,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        # 推理模型(DeepSeek 系等)默认会把 token 全烧在思维链上:实测 6000 max_tokens
        # 全部计入 reasoning_tokens、content 为空,最终请求超时、整轮生成降级;
        # 关掉后同一 prompt 从 47.6s 降到 18.8s 且能拿到完整 JSON。
        self.disable_thinking = disable_thinking
        self._thinking_rejected = False
        self.usage = LLMUsage()

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> LLMClient | None:
        if not config or not config.get("enabled", True):
            return None
        base_url = str(config.get("base_url") or "").strip()
        api_key = str(config.get("api_key") or "").strip()
        model = str(config.get("model") or "").strip()
        if not (base_url and api_key and model):
            return None
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=float(config.get("timeout_seconds") or 180),
            disable_thinking=bool(config.get("disable_thinking", True)),
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        wants_thinking_off = self.disable_thinking and not self._thinking_rejected
        if wants_thinking_off:
            payload["thinking"] = {"type": "disabled"}
        resp = await self._post(payload)
        if wants_thinking_off and self._rejects_thinking(resp):
            logger.warning(
                "LLM 网关不接受 thinking 参数(HTTP %s),去掉后重试并记住该能力",
                resp.status_code,
            )
            self._thinking_rejected = True
            payload.pop("thinking", None)
            resp = await self._post(payload)
        if resp.status_code != 200:
            raise LLMError(f"LLM HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
        except ValueError as exc:
            body = " ".join((resp.text or "").split())[:200]
            raise LLMError(
                "LLM 返回非 JSON 响应(HTTP 200),请确认 base_url 指向 OpenAI 兼容地址"
                f"(通常以 /v1 结尾);响应片段: {body or '<empty>'}"
            ) from exc
        if isinstance(data, dict):
            self.usage.add(data.get("usage"))
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected LLM response shape: {str(data)[:300]}") from exc

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            # 超时类异常的 str() 常为空,补上类型与超时值,否则日志只剩「LLM request failed: 」。
            detail = str(exc).strip() or type(exc).__name__
            raise LLMError(f"LLM 请求失败({detail}; timeout={self.timeout:g}s)") from exc

    @staticmethod
    def _rejects_thinking(resp: httpx.Response) -> bool:
        if resp.status_code not in (400, 404, 422):
            return False
        return bool(_THINKING_REJECT_RE.search(resp.text or ""))

    async def chat_text(
        self,
        prompt: str,
        *,
        temperature: float = 0.3,
        system: str | None = None,
    ) -> str:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(messages, temperature=temperature)

    async def chat_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
    ) -> Any:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        content = await self.chat(messages, temperature=temperature)
        return parse_json_content(content)

    async def test(self) -> tuple[str, int]:
        start = time.perf_counter()
        reply = await self.chat(
            [{"role": "user", "content": "Reply with the single word: ok"}],
            temperature=0,
            max_tokens=64,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        return reply.strip(), latency_ms
