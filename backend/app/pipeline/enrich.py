"""LLM enrichment: translation, summary, classification and score signals."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.pipeline.text import detect_lang, strip_html, truncate
from app.prompts import render_prompt
from app.services.llm import LLMClient, LLMError

CONTENT_TYPES = {"paper", "tech", "industry", "community", "repo", "skill", "model"}

# 资源类对象(项目/技能/模型)由采集器确定类型,LLM 不得改写
FORCED_CONTENT_TYPES = {"repo", "skill", "model"}

CHANNEL_DEFAULT_TYPE = {
    "arxiv": "paper",
    "github": "tech",
    "github_trending": "tech",
    "hn": "community",
    "hackernews": "community",
    "google_news": "tech",
    "bing_news": "tech",
    "repo": "repo",
    "skill": "skill",
    "model": "model",
    "rss": "tech",
}


@dataclass
class EnrichResult:
    content_type: str = "tech"
    lang: str = "unknown"
    translated_title: str | None = None
    translated_text: str | None = None
    summary: str | None = None
    card: dict[str, Any] | None = None
    tags: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    llm_relevance: float | None = None
    llm_heat: float | None = None
    model: str | None = None


@dataclass
class EnrichInput:
    """One raw item waiting for enrichment (batch friendly)."""

    title: str
    text: str | None
    url: str
    channel: str
    content_type_hint: str | None = None


@dataclass
class BatchEnrichOutcome:
    results: list[EnrichResult] = field(default_factory=list)
    fallback_items: int = 0
    batch_failures: int = 0


def fallback_enrich(
    *,
    title: str,
    text: str | None,
    channel: str,
    content_type_hint: str | None = None,
) -> EnrichResult:
    """Deterministic enrichment used when the LLM is unavailable."""
    content_type = content_type_hint if content_type_hint in CONTENT_TYPES else None
    content_type = content_type or CHANNEL_DEFAULT_TYPE.get(channel, "tech")
    plain = strip_html(text or "")
    return EnrichResult(
        content_type=content_type,
        lang=detect_lang(f"{title} {plain}"),
        summary=truncate(plain, 300) or None,
    )


def _clamp_score(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, number))


def _parse_result(payload: dict[str, Any], model: str) -> EnrichResult:
    content_type = str(payload.get("content_type") or "tech")
    if content_type not in CONTENT_TYPES:
        content_type = "tech"
    card = payload.get("card") if isinstance(payload.get("card"), dict) else None
    entities = payload.get("entities") if isinstance(payload.get("entities"), list) else []
    tags = [str(t) for t in payload.get("tags") or [] if str(t).strip()][:3]
    keywords = [str(k) for k in payload.get("keywords") or [] if str(k).strip()][:8]
    return EnrichResult(
        content_type=content_type,
        lang=str(payload.get("lang") or "unknown"),
        translated_title=(str(payload.get("translated_title") or "").strip() or None),
        summary=(str(payload.get("summary") or "").strip() or None),
        card=card,
        tags=tags,
        entities=[e for e in entities if isinstance(e, dict)][:8],
        keywords=keywords,
        llm_relevance=_clamp_score(payload.get("relevance")),
        llm_heat=_clamp_score(payload.get("heat")),
        model=model,
    )


def _keywords_text(keywords: list[dict[str, Any]]) -> str:
    return ", ".join(
        str(k.get("word")) for k in keywords if k.get("kind", "include") == "include"
    )


def _apply_hints(
    result: EnrichResult,
    *,
    title: str,
    text: str | None,
    content_type_hint: str | None,
) -> EnrichResult:
    lang_hint = detect_lang(f"{title} {strip_html(text or '')}")
    if result.lang == "unknown":
        result.lang = lang_hint
    if content_type_hint and content_type_hint in CONTENT_TYPES:
        if content_type_hint in FORCED_CONTENT_TYPES or result.content_type == "tech":
            result.content_type = content_type_hint
    return result


def _render_batch_item(index: int, item: EnrichInput, max_chars: int) -> str:
    plain = strip_html(item.text or "")
    lang_hint = detect_lang(f"{item.title} {plain}")
    return "\n".join(
        [
            f"### 条目 {index}",
            f"- 来源渠道: {item.channel}",
            f"- 原始标题: {item.title}",
            f"- 链接: {item.url}",
            f"- 原文语言判断: {lang_hint}",
            "- 正文(可能被截断):",
            truncate(plain, max_chars) or "(无正文,仅根据标题判断)",
        ]
    )


async def enrich_batch(
    client: LLMClient,
    items: list[EnrichInput],
    *,
    topic_name: str,
    keywords: list[dict[str, Any]],
    max_chars: int = 1800,
) -> dict[int, EnrichResult]:
    """One LLM call enriching several items; returns {1-based index: result}."""
    blocks = "\n\n".join(
        _render_batch_item(index + 1, item, max_chars) for index, item in enumerate(items)
    )
    prompt = render_prompt(
        "enrich_batch",
        topic_name=topic_name,
        keywords=_keywords_text(keywords),
        items=blocks,
    )
    payload = await client.chat_json(prompt)
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise LLMError("enrich batch response is not a JSON list")
    results: dict[int, EnrichResult] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            index = int(row.get("index"))
        except (TypeError, ValueError):
            continue
        if not 1 <= index <= len(items) or index in results:
            continue
        item = items[index - 1]
        results[index] = _apply_hints(
            _parse_result(row, client.model),
            title=item.title,
            text=item.text,
            content_type_hint=item.content_type_hint,
        )
    return results


async def enrich_many(
    client: LLMClient,
    items: list[EnrichInput],
    *,
    topic_name: str,
    keywords: list[dict[str, Any]],
    batch_size: int = 6,
    concurrency: int = 3,
    max_chars: int = 1800,
    semaphore: asyncio.Semaphore | None = None,
    on_progress: Callable[[int], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> BatchEnrichOutcome:
    """Batched enrichment with per-item fallbacks; keeps original ordering."""
    outcome = BatchEnrichOutcome()
    if not items:
        return outcome
    size = max(1, batch_size)
    sem = semaphore or asyncio.Semaphore(max(1, concurrency))
    results: list[EnrichResult | None] = [None] * len(items)
    done = 0

    def _fallback(item: EnrichInput) -> EnrichResult:
        outcome.fallback_items += 1
        return fallback_enrich(
            title=item.title,
            text=item.text,
            channel=item.channel,
            content_type_hint=item.content_type_hint,
        )

    async def run_chunk(offset: int, chunk: list[EnrichInput]) -> None:
        nonlocal done
        async with sem:
            mapping: dict[int, EnrichResult] = {}
            try:
                mapping = await enrich_batch(
                    client, chunk, topic_name=topic_name, keywords=keywords, max_chars=max_chars
                )
            except Exception as exc:  # noqa: BLE001 - degrade, never abort the run
                outcome.batch_failures += 1
                if on_error is not None:
                    on_error(exc)
            healthy = True
            for index, item in enumerate(chunk):
                result = mapping.get(index + 1)
                if result is None and healthy:
                    # 批量缺项/失败:探测一次单条调用;失败即整块降级,避免逐条打网络
                    try:
                        result = await enrich_item(
                            client,
                            title=item.title,
                            text=item.text,
                            url=item.url,
                            channel=item.channel,
                            topic_name=topic_name,
                            keywords=keywords,
                            content_type_hint=item.content_type_hint,
                        )
                    except Exception:  # noqa: BLE001
                        healthy = False
                results[offset + index] = result if result is not None else _fallback(item)
        done += len(chunk)
        if on_progress is not None:
            on_progress(done)

    await asyncio.gather(*(run_chunk(offset, chunk) for offset, chunk in _chunked(items, size)))
    outcome.results = [r for r in results if r is not None]
    return outcome


def _chunked(items: list[EnrichInput], size: int):
    for offset in range(0, len(items), size):
        yield offset, items[offset : offset + size]


async def enrich_item(
    client: LLMClient,
    *,
    title: str,
    text: str | None,
    url: str,
    channel: str,
    topic_name: str,
    keywords: list[dict[str, Any]],
    content_type_hint: str | None = None,
    max_chars: int = 6000,
) -> EnrichResult:
    """Run one LLM call producing translation, summary, type and score signals."""
    prompt = render_prompt(
        "enrich",
        topic_name=topic_name,
        keywords=_keywords_text(keywords),
        source=channel,
        title=title,
        url=url,
        lang_hint=detect_lang(f"{title} {strip_html(text or '')}"),
        content=truncate(strip_html(text or ""), max_chars) or "(无正文,仅根据标题判断)",
    )
    payload = await client.chat_json(prompt)
    if not isinstance(payload, dict):
        raise LLMError("enrich response is not a JSON object")
    return _apply_hints(
        _parse_result(payload, client.model),
        title=title,
        text=text,
        content_type_hint=content_type_hint,
    )
