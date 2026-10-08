"""Item feed queries and single-item deep enrichment (single mode)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import session_dep
from app.collectors import CHANNEL_ROUTES
from app.models import (
    Article,
    Digest,
    DigestItem,
    Item,
    ItemContent,
    ItemScore,
    Source,
)
from app.schemas.config import Page
from app.schemas.content import ItemDetailOut, ItemOut, ItemRefOut, ScoreOut
from app.services.app_settings import get_llm_config
from app.services.item_enrich import regenerate_card
from app.services.llm import LLMClient, LLMError

router = APIRouter(prefix="/items", tags=["items"])


class ItemStatusIn(BaseModel):
    status: str


async def _collect_relations(session: AsyncSession, items: list[Item]) -> dict[int, str]:
    source_names: dict[int, str] = {}
    if not items:
        return source_names
    source_ids = {item.source_id for item in items if item.source_id}
    if source_ids:
        rows = await session.execute(
            select(Source.id, Source.name).where(Source.id.in_(source_ids))
        )
        source_names = dict(rows.all())
    return source_names


def _item_out(item: Item, source_names: dict[int, str]) -> ItemOut:
    content = item.content
    score = item.score
    detail = (score.detail or {}) if score else {}

    def _words(value: Any) -> list[str]:
        return [str(word) for word in (value or []) if str(word).strip()]

    return ItemOut(
        id=item.id,
        channel=item.channel,
        content_type=item.content_type,
        title=item.title,
        url=item.url,
        author=item.author,
        published_at=item.published_at,
        lang=item.lang,
        tags=item.tags or [],
        status=item.status,
        first_seen_at=item.first_seen_at,
        source_id=item.source_id,
        source_name=source_names.get(item.source_id),
        translated_title=content.translated_title if content else None,
        summary=content.summary if content else None,
        collect_name=detail.get("collect_name"),
        collect_keywords=_words(detail.get("collect_keywords")),
        keyword_hits=_words(detail.get("keyword_hits")),
        origin=str(detail["origin"]) if detail.get("origin") else None,
        score=ScoreOut(
            heat=score.heat,
            relevance=score.relevance,
            freshness=score.freshness,
            total=score.total,
            detail=score.detail or {},
        )
        if score
        else None,
    )


def _item_detail(
    item: Item,
    source_names: dict[int, str],
    references: list[ItemRefOut] | None = None,
) -> ItemDetailOut:
    base = _item_out(item, source_names)
    content = item.content
    return ItemDetailOut(
        **base.model_dump(),
        raw_text=content.raw_text if content else None,
        translated_text=content.translated_text if content else None,
        card=content.card if content else None,
        references=references or [],
    )


async def _collect_references(session: AsyncSession, item_id: int) -> list[ItemRefOut]:
    """反查该素材被哪些产出物引用(日报经 digest_items,文章经 source_item_ids)。"""
    references: list[ItemRefOut] = []
    digest_rows = await session.execute(
        select(Digest.id, Digest.title, Digest.created_at)
        .join(DigestItem, DigestItem.digest_id == Digest.id)
        .where(DigestItem.item_id == item_id)
        .order_by(Digest.created_at.desc(), Digest.id.desc())
        .limit(20)
    )
    for digest_id, title, created_at in digest_rows.all():
        references.append(
            ItemRefOut(kind="digest", id=digest_id, title=title, created_at=created_at)
        )
    article_rows = await session.execute(
        select(Article.id, Article.title, Article.created_at)
        .where(Article.source_item_ids.contains([item_id]))
        .order_by(Article.created_at.desc(), Article.id.desc())
        .limit(20)
    )
    for article_id, title, created_at in article_rows.all():
        references.append(
            ItemRefOut(kind="article", id=article_id, title=title, created_at=created_at)
        )
    return references


def _engine_channels(engine: str) -> list[str]:
    """按引擎(rss/news/github)取采集渠道键;渠道注册表是唯一事实来源。"""
    return [
        key for key, route in CHANNEL_ROUTES.items() if route and route[0] == engine
    ]


@router.get("", response_model=Page[ItemOut])
async def list_items(
    page: int = 1,
    page_size: int = 20,
    content_type: str | None = None,
    channel: str | None = None,
    engine: str | None = None,
    source_id: int | None = None,
    min_score: float | None = None,
    since_hours: int | None = None,
    q: str | None = None,
    sort: str = "score",
    session: AsyncSession = Depends(session_dep),
) -> Page[ItemOut]:
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    stmt = select(Item).join(ItemScore, ItemScore.item_id == Item.id).where(Item.status == "active")
    if content_type:
        stmt = stmt.where(Item.content_type == content_type)
    if channel:
        stmt = stmt.where(Item.channel == channel)
    if engine:
        engine_channels = _engine_channels(engine)
        if not engine_channels:
            raise HTTPException(status_code=400, detail=f"未知采集引擎: {engine}")
        stmt = stmt.where(Item.channel.in_(engine_channels))
    if source_id is not None:
        stmt = stmt.where(Item.source_id == int(source_id))
    if min_score is not None:
        stmt = stmt.where(ItemScore.total >= min_score)
    if since_hours:
        stmt = stmt.where(
            Item.first_seen_at >= datetime.now(UTC) - timedelta(hours=int(since_hours))
        )
    if q:
        stmt = stmt.join(ItemContent, ItemContent.item_id == Item.id)
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Item.title.ilike(like),
                ItemContent.translated_title.ilike(like),
                ItemContent.summary.ilike(like),
            )
        )
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort == "published":
        stmt = stmt.order_by(Item.published_at.desc().nullslast(), Item.id.desc())
    elif sort == "recent":
        stmt = stmt.order_by(Item.first_seen_at.desc(), Item.id.desc())
    else:
        stmt = stmt.order_by(ItemScore.total.desc(), Item.id.desc())
    items = list(await session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)))
    source_names = await _collect_relations(session, items)
    return Page(
        items=[_item_out(item, source_names) for item in items],
        total=total,
    )


@router.get("/lookup", response_model=list[ItemOut])
async def lookup_items(
    ids: str = "", session: AsyncSession = Depends(session_dep)
) -> list[ItemOut]:
    """按 id 批量取素材(产出物详情里展示「素材来源」用),保持入参顺序。"""
    id_list = [int(part) for part in ids.split(",") if part.strip().isdigit()][:50]
    if not id_list:
        return []
    rows = list(await session.scalars(select(Item).where(Item.id.in_(id_list))))
    by_id = {item.id: item for item in rows}
    source_names = await _collect_relations(session, rows)
    return [_item_out(by_id[item_id], source_names) for item_id in id_list if item_id in by_id]


@router.get("/{item_id}", response_model=ItemDetailOut)
async def get_item(item_id: int, session: AsyncSession = Depends(session_dep)) -> ItemDetailOut:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="条目不存在")
    source_names = await _collect_relations(session, [item])
    references = await _collect_references(session, item_id)
    return _item_detail(item, source_names, references)


@router.patch("/{item_id}", response_model=ItemDetailOut)
async def update_item_status(
    item_id: int,
    payload: ItemStatusIn,
    session: AsyncSession = Depends(session_dep),
) -> ItemDetailOut:
    if payload.status not in ("active", "hidden"):
        raise HTTPException(status_code=400, detail="status 只支持 active/hidden")
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="条目不存在")
    item.status = payload.status
    await session.commit()
    source_names = await _collect_relations(session, [item])
    return _item_detail(item, source_names, await _collect_references(session, item_id))


@router.post("/{item_id}/enrich", response_model=ItemDetailOut)
async def enrich_single_item(
    item_id: int, session: AsyncSession = Depends(session_dep)
) -> ItemDetailOut:
    """Regenerate the deep-dive card for one item (single mode)."""
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="条目不存在")
    llm = LLMClient.from_config(await get_llm_config(session))
    if llm is None:
        raise HTTPException(status_code=400, detail="LLM 未配置,无法生成深挖卡片")
    try:
        await regenerate_card(session, item, llm)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM 调用失败: {exc}") from exc
    return await get_item(item_id, session)
