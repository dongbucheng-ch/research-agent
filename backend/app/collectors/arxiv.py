"""arXiv API collector driven by collection keywords."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import feedparser

from app.collectors.base import (
    BaseCollector,
    CollectContext,
    RawItem,
    get_with_retries,
    make_client,
)
from app.pipeline.text import truncate

if TYPE_CHECKING:
    from app.models import Source

logger = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"
MAX_QUERY_KEYWORDS = 12


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


class ArxivCollector(BaseCollector):
    channel = "arxiv"

    async def collect(self, source: Source, ctx: CollectContext) -> list[RawItem]:
        config = source.config or {}
        keywords = [str(k).strip() for k in ctx.keywords if str(k).strip()]
        keywords = keywords[:MAX_QUERY_KEYWORDS]
        if not keywords:
            logger.info("arXiv source %s skipped: no keywords", source.name)
            return []

        query_parts = [f'abs:"{kw.replace(chr(34), " ")}"' for kw in keywords]
        query = " OR ".join(query_parts)
        categories = [str(c).strip() for c in (config.get("categories") or []) if str(c).strip()]
        if categories:
            cat_query = " OR ".join(f"cat:{c}" for c in categories)
            query = f"({query}) AND ({cat_query})"

        params = {
            "search_query": query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": str(max(1, min(ctx.max_items, 50))),
        }
        async with make_client(ctx.timeout) as client:
            resp = await get_with_retries(client, ARXIV_API, params=params)

        parsed = feedparser.parse(resp.content)
        if parsed.bozo and not parsed.entries:
            logger.warning("arXiv query failed for %s", source.name)
            return []

        items: list[RawItem] = []
        for entry in parsed.entries:
            link = str(entry.get("link") or "").strip()
            title = " ".join(str(entry.get("title") or "").split())
            if not link or not title:
                continue
            authors = entry.get("authors") or []
            author = ", ".join(str(a.get("name")) for a in authors[:3] if a.get("name"))
            summary = " ".join(str(entry.get("summary") or "").split())
            items.append(
                RawItem(
                    url=link,
                    title=truncate(title, 500),
                    published_at=_parse_datetime(entry.get("published")),
                    author=author or None,
                    raw_text=truncate(summary, 8000) or None,
                    external_id=str(entry.get("id") or "").strip() or None,
                    content_type_hint="paper",
                    extra={
                        "categories": [
                            t.get("term") for t in (entry.get("tags") or []) if t.get("term")
                        ]
                    },
                )
            )
        return items
