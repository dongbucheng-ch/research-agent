"""Push payload composition: overrides, channel defaults and material-derived tags."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

TAG_LIMIT = 9
TAG_MAX_LEN = 64
MATERIAL_TAG_LIMIT = 6


def normalize_tags(
    values: Iterable[Any] | None, *, limit: int = TAG_LIMIT, max_len: int = TAG_MAX_LEN
) -> list[str]:
    """去空、去重并截断标签(社区侧:自定义标签 ≤9 个、单标签 ≤64 字)。"""
    result: list[str] = []
    for raw in values or ():
        name = str(raw or "").strip()[:max_len]
        if name and name not in result:
            result.append(name)
        if len(result) >= limit:
            break
    return result


def rank_tags(tag_lists: Iterable[Iterable[Any]], *, limit: int = MATERIAL_TAG_LIMIT) -> list[str]:
    """按出现次数汇总素材标签;次数相同按首次出现顺序。"""
    counter: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    for tags in tag_lists:
        for raw in tags or ():
            name = str(raw or "").strip()
            if not name:
                continue
            if name not in first_seen:
                first_seen[name] = len(first_seen)
            counter[name] += 1
    ranked = sorted(counter, key=lambda name: (-counter[name], first_seen[name]))
    return ranked[:limit]


def compose_payload(
    *,
    target_id: int,
    title: str,
    lead: str | None,
    content_md: str | None,
    highlights: Sequence[Any] | None,
    material_tags: Sequence[str] | None = None,
    overrides: Mapping[str, Any] | None = None,
    channel_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """推送 payload:override > 渠道配置 > 产出物默认;标签默认取素材汇总。"""
    override = overrides or {}
    config = channel_config or {}

    def _text(key: str, fallback: str = "") -> str:
        value = str(override.get(key) or "").strip()
        if value:
            return value
        return str(config.get(key) or "").strip() or fallback

    tags_override = [str(tag) for tag in (override.get("tags") or [])]
    return {
        "id": target_id,
        "title": _text("title", title),
        "lead": lead or "",
        "content_md": content_md or "",
        "highlights": list(highlights or []),
        "tags": normalize_tags(tags_override or material_tags or []),
        "source": _text("source"),
        "author": _text("author"),
    }
