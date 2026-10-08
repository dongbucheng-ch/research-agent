"""采集补量用的关键词辐射。

当一轮采集的新入库素材不足时,让 LLM 围绕研究方向生成 4-6 个相关检索词,
再做**一轮**补采(不递归,避免无限扩采与 token 消耗)。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from app.prompts import render_prompt
from app.services.llm import LLMClient, LLMError

logger = logging.getLogger(__name__)
LogFn = Callable[[str], None]

MIN_TERMS = 4
MAX_TERMS = 6
_MAX_WORD_LEN = 40
_CACHE_LIMIT = 64
_CACHE: dict[tuple[str, str, tuple[str, ...]], list[str]] = {}


def clear_expand_cache() -> None:
    _CACHE.clear()


def parse_expanded(data: Any, existing: list[str]) -> list[str]:
    """校验 LLM 输出:去重、去空、剔除与已有词重复的条目,最多 MAX_TERMS 个。"""
    rows: list[Any] = []
    if isinstance(data, dict):
        raw = data.get("keywords")
        if isinstance(raw, list):
            rows = raw
    elif isinstance(data, list):
        rows = data

    seen = {str(word).strip().lower() for word in existing if str(word).strip()}
    result: list[str] = []
    for row in rows:
        word = str(row or "").strip()
        if not word or len(word) > _MAX_WORD_LEN:
            continue
        lowered = word.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(word)
        if len(result) >= MAX_TERMS:
            break
    return result


async def expand_keywords(
    llm: LLMClient | None,
    *,
    topic: str,
    keywords: list[str],
    log: LogFn | None = None,
) -> list[str]:
    """生成辐射检索词;LLM 不可用或结果不足时返回空列表(调用方按“不补量”处理)。"""
    log = log or (lambda _message: None)
    cleaned = [str(word).strip() for word in keywords if str(word).strip()]
    if llm is None or not cleaned:
        return []

    cache_key = (str(getattr(llm, "model", "")), topic.strip(), tuple(cleaned))
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return list(cached)

    try:
        data = await llm.chat_json(
            render_prompt(
                "keyword_expand",
                topic=topic.strip() or "未指定",
                keywords_json=json.dumps(cleaned, ensure_ascii=False),
            )
        )
    except LLMError as exc:
        logger.warning("关键词辐射失败,跳过补量: %s", exc)
        log(f"[扩词] 关键词辐射失败,跳过补量: {exc}")
        return []

    words = parse_expanded(data, cleaned)
    if len(words) < MIN_TERMS:
        log(f"[扩词] 关键词辐射结果不足({len(words)} 个),跳过补量")
        return []
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.clear()
    _CACHE[cache_key] = list(words)
    return words


__all__ = ["MIN_TERMS", "MAX_TERMS", "clear_expand_cache", "expand_keywords", "parse_expanded"]
