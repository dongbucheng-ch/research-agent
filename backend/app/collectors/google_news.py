"""Google News 检索采集器(免鉴权,engine=`news`,preset=`google_news`)。

Adapted from Thysrael/Horizon (MIT) — src/scrapers/google_news.py
保留其关键做法:时间窗用 Google News 查询算子 `when:Nh` / `after:YYYY-MM-DD` 表达,
本地化用 `hl` / `gl` / `ceid`,单个坏条目跳过而不是中断整批。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import feedparser

from app.collectors.base import (
    BaseCollector,
    CollectContext,
    RawItem,
    get_with_retries,
    make_client,
)
from app.collectors.feedutil import entry_text, parse_entry_date
from app.pipeline.text import truncate

if TYPE_CHECKING:
    from app.models import Source

MAX_QUERY_KEYWORDS = 12
RELATIVE_WINDOW_LIMIT_HOURS = 100


def keywords_to_query(keywords: list[str], limit: int = MAX_QUERY_KEYWORDS) -> str:
    """把关键词列表拼成 Google News 检索表达式(OR 连接,逐词加引号)。"""
    words = [str(word).strip().replace('"', " ") for word in keywords if str(word).strip()]
    return " OR ".join(f'"{word}"' for word in words[:limit])


def time_operator(lookback_hours: int, now: datetime | None = None) -> str:
    """相对窗口用 `when:Nh`;超过 100 小时改用 `after:YYYY-MM-DD`(窗口起点)更可靠。"""
    hours = max(1, int(lookback_hours))
    if hours <= RELATIVE_WINDOW_LIMIT_HOURS:
        return f"when:{hours}h"
    start = (now or datetime.now(UTC)).astimezone(UTC) - timedelta(hours=hours)
    return f"after:{start.strftime('%Y-%m-%d')}"


def _source_name(entry: Any) -> str | None:
    source = entry.get("source")
    if isinstance(source, dict) and source.get("title"):
        return str(source["title"]).strip()
    title = getattr(source, "title", None)
    return str(title).strip() if title else None


def entry_to_item(entry: Any) -> RawItem | None:
    """把一条 Google News 条目映射为 RawItem;缺标题/链接/时间则跳过。"""
    title = str(entry.get("title") or "").strip()
    link = str(entry.get("link") or "").strip()
    published = parse_entry_date(entry)
    if not title or not link or published is None:
        return None
    publisher = _source_name(entry)
    return RawItem(
        url=link,
        title=truncate(title, 500),
        published_at=published,
        author=publisher,
        raw_text=entry_text(entry),
        external_id=str(entry.get("id") or link).strip() or None,
        extra={"publisher": publisher, "gn_entry_id": str(entry.get("id") or "")},
    )


class GoogleNewsCollector(BaseCollector):
    channel = "google_news"
    base_url = "https://news.google.com/rss/search"

    async def collect(self, source: Source, ctx: CollectContext) -> list[RawItem]:
        config = source.config if isinstance(source.config, dict) else {}
        query = str(config.get("query") or "").strip() or keywords_to_query(ctx.keywords)
        if not query:
            return []
        params = {
            "q": f"{query} {time_operator(ctx.lookback_hours)}",
            "hl": str(config.get("hl") or "zh-CN"),
            "gl": str(config.get("gl") or "CN"),
            "ceid": str(config.get("ceid") or "CN:zh-Hans"),
        }
        async with make_client(ctx.timeout) as client:
            response = await get_with_retries(client, self.base_url, params=params)

        feed = feedparser.parse(response.content)
        if feed.bozo and not feed.entries:
            return []
        items: list[RawItem] = []
        for entry in feed.entries[: max(1, min(ctx.max_items, 50))]:
            item = entry_to_item(entry)
            if item is not None:
                items.append(item)
        return items
