"""中文关键词 → 英文检索词。

采集与日报都会用到:中文词在 arXiv / GitHub / Hacker News 这些英文源上几乎命中不到,
所以先让 LLM 给 1-3 个英文检索词,再让「原词 + 译名」一起参与检索与打分(见
`pipeline.scoring.keyword_relevance` 的 `group` 归组,译名不会稀释相关度)。

设计要点:
- 只翻译含 CJK 的词;纯英文/数字词不进 LLM。
- LLM 未配置、调用失败或返回不合法时返回空映射,主流程照常跑(降级不阻断)。
- 进程内缓存(键 = 模型 + 词表),同一批词在采集/日报里不会重复调用 LLM。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from app.prompts import render_prompt
from app.services.llm import LLMClient, LLMError

logger = logging.getLogger(__name__)
LogFn = Callable[[str], None]

MAX_KEYWORDS = 12
MAX_VARIANTS = 3
_CACHE_LIMIT = 128

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_CACHE: dict[tuple[str, tuple[str, ...]], dict[str, list[str]]] = {}


def has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(str(text or "")))


def needs_translation(words: list[str]) -> bool:
    return any(has_cjk(str(word)) for word in words)


def clear_translation_cache() -> None:
    _CACHE.clear()


def parse_translations(data: Any, words: list[str]) -> dict[str, list[str]]:
    """校验 LLM 输出:只认输入词表里的 `word`,过滤中文/空/超长变体。"""
    rows: list[Any] = []
    if isinstance(data, dict):
        raw = data.get("translations")
        if isinstance(raw, list):
            rows = raw
        else:
            rows = [{"word": key, "english": value} for key, value in data.items()]
    elif isinstance(data, list):
        rows = data

    known = {str(word).strip().lower(): str(word).strip() for word in words}
    result: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("word") or row.get("keyword") or "").strip().lower()
        original = known.get(key)
        if not original:
            continue
        raw_variants = row.get("english") or row.get("en") or row.get("translations") or []
        if isinstance(raw_variants, str):
            raw_variants = [raw_variants]
        variants: list[str] = []
        for variant in raw_variants:
            text = " ".join(str(variant or "").split()).strip().strip('"').lower()
            if not text or has_cjk(text) or len(text.split()) > 4:
                continue
            if text in variants or text == key:
                continue
            variants.append(text)
        if variants:
            result[original] = variants[:MAX_VARIANTS]
    return result


def alias_keyword_entries(
    mapping: dict[str, list[str]], *, channel: str | None = None
) -> list[dict[str, Any]]:
    """翻译结果 → 采集用 keyword 条目(与中文原词同组,不额外降低相关度)。"""
    entries: list[dict[str, Any]] = []
    for word, variants in mapping.items():
        for variant in variants:
            entry: dict[str, Any] = {
                "word": variant,
                "kind": "include",
                "weight": 1.0,
                "group": word,
            }
            if channel:
                entry["channel"] = channel
            entries.append(entry)
    return entries


async def translate_keywords(
    llm: LLMClient | None,
    words: list[str],
    *,
    log: LogFn | None = None,
) -> dict[str, list[str]]:
    """返回 {原词: [英文检索词]};无需翻译或降级时返回空映射。"""
    log = log or (lambda _message: None)
    cleaned = [str(word).strip() for word in words if str(word).strip()][:MAX_KEYWORDS]
    if llm is None or not cleaned or not needs_translation(cleaned):
        return {}

    cache_key = (str(getattr(llm, "model", "")), tuple(cleaned))
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return {word: list(variants) for word, variants in cached.items()}

    try:
        data = await llm.chat_json(
            render_prompt(
                "keyword_translate", keywords_json=json.dumps(cleaned, ensure_ascii=False)
            )
        )
    except LLMError as exc:
        logger.warning("关键词翻译失败,使用原词采集: %s", exc)
        log(f"[配置] 关键词翻译失败,使用原词采集: {exc}")
        return {}

    mapping = parse_translations(data, cleaned)
    if mapping:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()
        _CACHE[cache_key] = {word: list(variants) for word, variants in mapping.items()}
        summary = "; ".join(f"{word} → {'/'.join(variants)}" for word, variants in mapping.items())
        log(f"[配置] 关键词翻译:{summary}")
    else:
        log("[配置] 关键词翻译无可用结果,使用原词采集")
    return mapping
