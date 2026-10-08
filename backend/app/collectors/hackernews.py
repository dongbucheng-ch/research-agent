"""Hacker News 采集器(engine=`news`,preset=`hackernews`,免鉴权 Firebase API)。

Adapted from Thysrael/Horizon (MIT) — src/scrapers/hackernews.py
保留其做法:topstories 取条目 id 后并发拉详情、按分数与时间过滤、单条失败不影响整批。
我们额外加了关键词过滤:给了研究方向关键词时,只保留标题/正文命中的条目。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

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

BASE_URL = "https://hacker-news.firebaseio.com/v0"
DEFAULT_TOP_STORIES = 30
DEFAULT_MIN_SCORE = 100
ITEM_URL = "https://news.ycombinator.com/item?id={id}"


def matches_keywords(story: dict[str, Any], keywords: list[str]) -> bool:
    if not keywords:
        return True
    haystack = f"{story.get('title') or ''}\n{story.get('text') or ''}".lower()
    return any(str(word).strip().lower() in haystack for word in keywords if str(word).strip())


def story_to_item(story: dict[str, Any]) -> RawItem | None:
    story_id = story.get("id")
    title = " ".join(str(story.get("title") or "").split())
    if not story_id or not title:
        return None
    created = story.get("time")
    published = (
        datetime.fromtimestamp(int(created), tz=UTC) if isinstance(created, (int, float)) else None
    )
    url = str(story.get("url") or "").strip() or ITEM_URL.format(id=story_id)
    text = str(story.get("text") or "").strip()
    return RawItem(
        url=url,
        title=truncate(title, 400),
        published_at=published,
        author=str(story.get("by") or "") or None,
        raw_text=truncate(text, 4000) or None,
        external_id=str(story_id),
        content_type_hint="community",
        metrics={
            "score": int(story.get("score") or 0),
            "comments": int(story.get("descendants") or 0),
        },
        extra={"hn_id": story_id, "hn_discussion": ITEM_URL.format(id=story_id)},
    )


class HackerNewsCollector(BaseCollector):
    channel = "hackernews"

    async def collect(self, source: Source, ctx: CollectContext) -> list[RawItem]:
        config = source.config if isinstance(source.config, dict) else {}
        top_n = max(1, min(int(config.get("fetch_top_stories") or DEFAULT_TOP_STORIES), 100))
        min_score = int(config.get("min_score") or DEFAULT_MIN_SCORE)
        since = datetime.now(UTC) - timedelta(hours=max(1, int(ctx.lookback_hours)))

        async with make_client(ctx.timeout) as client:
            response = await get_with_retries(client, f"{BASE_URL}/topstories.json")
            story_ids = [int(sid) for sid in (response.json() or [])[:top_n]]
            stories = await asyncio.gather(
                *[self._story(client, story_id) for story_id in story_ids],
                return_exceptions=True,
            )

        items: list[RawItem] = []
        for story in stories:
            if not isinstance(story, dict):
                continue
            if int(story.get("score") or 0) < min_score:
                continue
            if not matches_keywords(story, list(ctx.keywords)):
                continue
            item = story_to_item(story)
            if item is None or item.published_at is None:
                continue
            if item.published_at < since:
                continue
            items.append(item)
        return items

    @staticmethod
    async def _story(client: httpx.AsyncClient, story_id: int) -> dict[str, Any] | None:
        try:
            response = await client.get(f"{BASE_URL}/item/{story_id}.json")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None
