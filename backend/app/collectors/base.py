"""Collector protocol and shared helpers."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from app.models import Source

USER_AGENT = "research-agent/0.1 (+internal research tool)"


@dataclass(slots=True)
class RawItem:
    url: str
    title: str
    published_at: datetime | None = None
    author: str | None = None
    raw_text: str | None = None
    external_id: str | None = None
    content_type_hint: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CollectContext:
    keywords: list[str] = field(default_factory=list)
    lookback_hours: int = 24
    timeout: float = 20.0
    max_items: int = 50


class BaseCollector(ABC):
    channel: str = ""

    @abstractmethod
    async def collect(self, source: Source, ctx: CollectContext) -> list[RawItem]:
        """Fetch new entries from the source. Implementations must not raise on
        individual feed failures when partial results are possible."""


def make_client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


DEFAULT_GET_ATTEMPTS = 3
DEFAULT_GET_BACKOFF_SECONDS = 1.0


def describe_error(exc: BaseException) -> str:
    """异常文案:httpx 的 ConnectError 常带空 message,补上类型名以免日志只剩 unknown error。"""
    text = str(exc).strip()
    if text:
        return f"{type(exc).__name__}: {text}"
    return type(exc).__name__


async def get_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    attempts: int = DEFAULT_GET_ATTEMPTS,
    backoff_seconds: float = DEFAULT_GET_BACKOFF_SECONDS,
) -> httpx.Response:
    """GET 并 raise_for_status;网络类错误按指数退避重试。

    采集节点常见「一次握手失败」的网络抖动(代理/出口 TLS EOF),单次失败不代表源不可用,
    因此这里对 TransportError 重试;4xx/5xx 属于源本身的问题,直接抛出。
    """
    total = max(1, int(attempts))
    last: httpx.TransportError | None = None
    for attempt in range(total):
        try:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response
        except httpx.TransportError as exc:
            last = exc
            if attempt + 1 >= total:
                break
            await asyncio.sleep(backoff_seconds * (2**attempt))
    assert last is not None
    raise last
