"""Single-item card regeneration, shared by the API route and refresh scripts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Item, ItemContent, ItemScore, RawDocument
from app.pipeline.enrich import EnrichResult, enrich_item
from app.pipeline.scoring import combine_scores, freshness_score, metric_heat_score
from app.services.llm import LLMClient

CARD_KEYS = ("what", "why", "how")
LEGACY_CARD_KEYS = ("background", "method", "result", "insight")


def is_legacy_card(card: dict[str, Any] | None) -> bool:
    """True for cards written by the retired background/method/result/insight prompt."""
    if not card:
        return False
    if any(str(card.get(key) or "").strip() for key in CARD_KEYS):
        return False
    return any(str(card.get(key) or "").strip() for key in LEGACY_CARD_KEYS)


async def regenerate_card(session: AsyncSession, item: Item, llm: LLMClient) -> EnrichResult:
    """Re-run LLM enrichment for one item, updating content/card/score in place."""
    content = await session.get(ItemContent, item.id)
    score_row = await session.get(ItemScore, item.id)
    previous = (score_row.detail or {}) if score_row else {}
    # Keywords are typed per collection run and not persisted, so re-scoring
    # reuses the keyword signal recorded at ingest time.
    keyword_rel = float(previous.get("keyword_relevance") or 0.0)
    keyword_hits = [str(word) for word in (previous.get("keyword_hits") or [])]
    weights = previous.get("weights") if isinstance(previous.get("weights"), dict) else None

    result = await enrich_item(
        llm,
        title=item.title,
        text=content.raw_text if content else None,
        url=item.url,
        channel=item.channel,
        topic_name="综合",
        keywords=[],
        content_type_hint=item.content_type,
    )

    if content is None:
        content = ItemContent(item_id=item.id)
        session.add(content)
    content.translated_title = result.translated_title or content.translated_title
    content.summary = result.summary or content.summary
    content.card = result.card or content.card
    item.content_type = result.content_type
    item.tags = result.tags or item.tags
    item.entities = result.entities or item.entities
    if result.lang and result.lang != "unknown":
        item.lang = result.lang

    # Re-scoring must not lose the platform metrics (GitHub stars, HN points)
    # captured at ingest time, nor decay freshness from a missing published_at.
    payload = await session.scalar(
        select(RawDocument.payload)
        .where(RawDocument.item_id == item.id)
        .order_by(RawDocument.id.desc())
        .limit(1)
    )
    metrics = payload.get("metrics") if isinstance(payload, dict) else None
    score = combine_scores(
        keyword_rel=keyword_rel,
        llm_rel=result.llm_relevance,
        llm_heat=result.llm_heat,
        metric_heat=metric_heat_score(metrics),
        freshness=freshness_score(item.published_at or item.first_seen_at, result.content_type),
        weights=weights,
        keyword_hits=keyword_hits,
    )
    if score_row is None:
        score_row = ItemScore(item_id=item.id)
        session.add(score_row)
    score_row.heat = score.heat
    score_row.relevance = score.relevance
    score_row.freshness = score.freshness
    score_row.total = score.total
    score_row.detail = score.detail
    score_row.model = result.model
    await session.commit()
    return result
