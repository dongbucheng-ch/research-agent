"""Generic RSS/Atom collector (works with RSSHub and regular feeds)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from time import struct_time
from typing import TYPE_CHECKING

import feedparser

from app.collectors.base import (
    BaseCollector,
    CollectContext,
    RawItem,
    describe_error,
    get_with_retries,
    make_client,
)
from app.collectors.extract import extract_main_text
from app.pipeline.text import truncate

if TYPE_CHECKING:
    from app.models import Source

logger = logging.getLogger(__name__)


def _struct_time_to_dt(value: struct_time | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime(*value[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _entry_published(entry: dict) -> datetime | None:
    return _struct_time_to_dt(entry.get("published_parsed")) or _struct_time_to_dt(
        entry.get("updated_parsed")
    )


def _entry_body(entry: dict) -> str:
    if entry.get("content"):
        joined = " ".join(str(getattr(part, "value", "") or "") for part in entry["content"])
        if joined.strip():
            return joined
    return str(entry.get("summary") or entry.get("description") or "")


class RSSCollector(BaseCollector):
    channel = "rss"

    async def collect(self, source: Source, ctx: CollectContext) -> list[RawItem]:
        config = source.config or {}
        raw_feeds = config.get("feeds")
        feed_urls = (
            [str(u) for u in raw_feeds if str(u).strip()]
            if isinstance(raw_feeds, list) and raw_feeds
            else [source.url]
        )
        fetch_full_text = bool(config.get("fetch_full_text", False))
        cutoff = datetime.now(UTC) - timedelta(hours=ctx.lookback_hours)
        items: list[RawItem] = []
        seen_links: set[str] = set()

        async with make_client(ctx.timeout) as client:
            for feed_url in feed_urls:
                try:
                    resp = await get_with_retries(client, feed_url)
                    parsed = feedparser.parse(resp.content)
                except Exception as exc:  # noqa: BLE001 - partial failures are expected
                    logger.warning("RSS fetch failed for %s: %s", feed_url, describe_error(exc))
                    continue
                for entry in parsed.entries[: ctx.max_items]:
                    link = str(entry.get("link") or "").strip()
                    title = str(entry.get("title") or "").strip()
                    if not link or not title or link in seen_links:
                        continue
                    published = _entry_published(entry)
                    if published is not None and published < cutoff:
                        continue
                    seen_links.add(link)
                    body = _entry_body(entry)
                    if fetch_full_text:
                        try:
                            page = await client.get(link)
                            if page.status_code == 200:
                                full = extract_main_text(page.text, url=link)
                                if len(full) > len(body):
                                    body = full
                        except Exception as exc:  # noqa: BLE001
                            logger.debug("full text fetch failed for %s: %s", link, exc)
                    author = str(entry.get("author") or "").strip() or None
                    items.append(
                        RawItem(
                            url=link,
                            title=truncate(title, 500),
                            published_at=published,
                            author=author,
                            raw_text=truncate(body, 12000) or None,
                            external_id=str(entry.get("id") or "") or None,
                        )
                    )
                    if len(items) >= ctx.max_items:
                        return items
        return items
