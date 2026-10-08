"""Feed entry 通用工具:news 系采集器(RSS/Atom/检索端点)共用的解析小函数。

自研。抽出来的原因:`google_news` / `bing_news` 两个检索采集器都要从 feedparser
entry 里取「发布时间」「正文摘要」,规则一致,避免两处实现漂移。
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from app.pipeline.text import strip_html, truncate


def parse_entry_date(entry: Any) -> datetime | None:
    """按 published → updated → created 顺序取时间,解析失败返回 None。"""
    for field in ("published", "updated", "created"):
        parsed = entry.get(f"{field}_parsed")
        if parsed:
            try:
                return datetime(*[int(part) for part in parsed[:6]], tzinfo=UTC)
            except (TypeError, ValueError, OverflowError):
                pass
        raw = entry.get(field)
        if raw:
            try:
                moment = parsedate_to_datetime(str(raw))
            except (TypeError, ValueError):
                continue
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            return moment.astimezone(UTC)
    return None


def entry_text(entry: Any, limit: int = 2000) -> str | None:
    """取条目正文/摘要:优先 summary,再 description,最后 content[0].value。"""
    for field in ("summary", "description"):
        value = entry.get(field)
        if value:
            text = truncate(strip_html(str(value)), limit)
            if text:
                return text
    content = entry.get("content")
    if content:
        try:
            return truncate(strip_html(str(content[0].get("value", ""))), limit) or None
        except (IndexError, AttributeError, TypeError):
            return None
    return None
