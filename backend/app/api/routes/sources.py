"""Source pool management and the recommended-source catalog."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import session_dep
from app.collectors import CollectContext, collector_for, object_type_of, route_of
from app.collectors.base import describe_error
from app.models import Item, ItemScore, RawDocument, Source
from app.schemas.config import (
    DiscoverCandidateOut,
    DiscoverIn,
    DiscoverOut,
    ImportCandidatesIn,
    RecommendedSource,
    SourceIn,
    SourceOut,
    SourceStatOut,
    SourceTestOut,
    SourceUpdate,
)
from app.services.discovery import collect_candidates, normalize_url, probe_candidates

router = APIRouter(prefix="/sources", tags=["sources"])

RECOMMENDED_PATH = Path(__file__).resolve().parents[3] / "resources" / "recommended_sources.json"


class ImportRecommendedIn(BaseModel):
    keys: list[str]


def _source_out(source: Source) -> SourceOut:
    """带上引擎/预设/对象类型(按 channel + config 解析,不落库)。"""
    route = route_of(source) or ("", "")
    return SourceOut.model_validate(source).model_copy(
        update={"engine": route[0], "preset": route[1], "object_type": object_type_of(source)}
    )


def _load_recommended() -> list[RecommendedSource]:
    if not RECOMMENDED_PATH.exists():
        return []
    data = json.loads(RECOMMENDED_PATH.read_text(encoding="utf-8"))
    return [RecommendedSource(**item) for item in data.get("sources", [])]


@router.get("", response_model=list[SourceOut])
async def list_sources(
    channel: str | None = None,
    enabled: bool | None = None,
    session: AsyncSession = Depends(session_dep),
) -> list[SourceOut]:
    stmt = select(Source).order_by(Source.tier, Source.id)
    if channel:
        stmt = stmt.where(Source.channel == channel)
    if enabled is not None:
        stmt = stmt.where(Source.enabled.is_(enabled))
    sources = list(await session.scalars(stmt))
    return [_source_out(source) for source in sources]


@router.get("/stats", response_model=list[SourceStatOut])
async def source_stats(
    days: int = 30, session: AsyncSession = Depends(session_dep)
) -> list[SourceStatOut]:
    """近 N 天每个信源的候选量与产出质量,用于淘汰低产源。"""
    days = max(1, min(int(days), 365))
    since = datetime.now(UTC) - timedelta(days=days)
    fetched_rows = (
        await session.execute(
            select(RawDocument.source_id, func.count(RawDocument.id))
            .where(RawDocument.fetched_at >= since, RawDocument.source_id.isnot(None))
            .group_by(RawDocument.source_id)
        )
    ).all()
    ingest_rows = (
        await session.execute(
            select(
                Item.source_id,
                func.count(Item.id),
                func.avg(ItemScore.total),
                func.max(Item.first_seen_at),
            )
            .join(ItemScore, ItemScore.item_id == Item.id)
            .where(Item.first_seen_at >= since, Item.source_id.isnot(None))
            .group_by(Item.source_id)
        )
    ).all()
    stats: dict[int, SourceStatOut] = {}
    for source_id, count in fetched_rows:
        stats[int(source_id)] = SourceStatOut(source_id=int(source_id), candidates=int(count))
    for source_id, count, avg_score, last_item_at in ingest_rows:
        entry = stats.setdefault(int(source_id), SourceStatOut(source_id=int(source_id)))
        entry.ingested = int(count)
        entry.avg_score = round(float(avg_score), 1) if avg_score is not None else None
        entry.last_item_at = last_item_at
    return sorted(stats.values(), key=lambda row: row.source_id)


@router.get("/recommended", response_model=list[RecommendedSource])
async def list_recommended() -> list[RecommendedSource]:
    return _load_recommended()


@router.post("/import-recommended", response_model=list[SourceOut])
async def import_recommended(
    payload: ImportRecommendedIn, session: AsyncSession = Depends(session_dep)
) -> list[SourceOut]:
    catalog = {item.key: item for item in _load_recommended()}
    created: list[Source] = []
    for key in payload.keys:
        item = catalog.get(key)
        if item is None:
            continue
        exists = await session.scalar(select(Source.id).where(Source.name == item.name))
        if exists is not None:
            continue
        source = Source(
            name=item.name,
            channel=item.channel,
            collector_kind=item.collector_kind,
            url=item.url,
            config=item.config,
            tier=item.tier,
        )
        session.add(source)
        await session.flush()
        created.append(source)
    await session.commit()
    return [_source_out(source) for source in created]


async def _existing_feed_keys(session: AsyncSession) -> set[str]:
    """已存在信源(信源池 + 推荐库)的 URL 归一化键,用于发现结果去重标记。"""
    urls = {url for url in await session.scalars(select(Source.url)) if url}
    urls.update(item.url for item in _load_recommended())
    return {normalize_url(url) for url in urls}


@router.post("/discover", response_model=DiscoverOut)
async def discover_feeds(
    payload: DiscoverIn, session: AsyncSession = Depends(session_dep)
) -> DiscoverOut:
    """从 GitHub 仓库 / OPML / 页面 URL 发掘候选 Feed 并并发探测可达性(不落库)。"""
    url = payload.url.strip()
    try:
        candidates = await collect_candidates(url, limit=payload.limit)
    except Exception as exc:  # noqa: BLE001 - 反馈给操作者
        detail = f"候选收集失败: {describe_error(exc)[:200]}"
        raise HTTPException(status_code=502, detail=detail) from exc
    if not candidates:
        return DiscoverOut(source_url=url)
    probed = await probe_candidates(candidates)
    existing = await _existing_feed_keys(session)
    out = [
        DiscoverCandidateOut(
            name=candidate.name,
            url=candidate.url,
            ok=result.ok,
            entries=result.entries,
            latest=result.latest,
            title=result.title,
            error=result.error,
            already_exists=normalize_url(candidate.url) in existing,
        )
        for candidate, result in probed
    ]
    return DiscoverOut(source_url=url, ok_count=sum(1 for item in out if item.ok), candidates=out)


@router.post("/import-candidates", response_model=list[SourceOut])
async def import_candidates(
    payload: ImportCandidatesIn, session: AsyncSession = Depends(session_dep)
) -> list[SourceOut]:
    """批量导入发现结果。按 URL 去重,同名信源自动加序号后缀。"""
    existing_names = set(await session.scalars(select(Source.name)))
    existing_keys = {normalize_url(url) for url in await session.scalars(select(Source.url)) if url}
    created: list[Source] = []
    for item in payload.items:
        url = item.url.strip()
        key = normalize_url(url)
        if key in existing_keys:
            continue
        base_name = (item.name or url).strip()[:140] or url
        name = base_name
        suffix = 2
        while name in existing_names:
            name = f"{base_name} ({suffix})"[:150]
            suffix += 1
        source = Source(
            name=name,
            channel=item.channel,
            collector_kind="stream",
            url=url,
            config={},
            tier=item.tier,
        )
        session.add(source)
        created.append(source)
        existing_names.add(name)
        existing_keys.add(key)
    if created:
        await session.commit()
        for source in created:
            await session.refresh(source)
    return [_source_out(source) for source in created]


@router.post("", response_model=SourceOut, status_code=201)
async def create_source(
    payload: SourceIn, session: AsyncSession = Depends(session_dep)
) -> SourceOut:
    source = Source(
        name=payload.name.strip(),
        channel=payload.channel,
        collector_kind=payload.collector_kind,
        url=payload.url.strip(),
        config=payload.config,
        tier=payload.tier,
        enabled=payload.enabled,
        fetch_interval_minutes=payload.fetch_interval_minutes,
    )
    session.add(source)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="信源名称已存在") from exc
    await session.commit()
    await session.refresh(source)
    return _source_out(source)


@router.put("/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: int,
    payload: SourceUpdate,
    session: AsyncSession = Depends(session_dep),
) -> SourceOut:
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="信源不存在")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(source, field, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="信源名称已存在") from exc
    await session.refresh(source)
    return _source_out(source)


@router.delete("/{source_id}", status_code=204)
async def delete_source(source_id: int, session: AsyncSession = Depends(session_dep)) -> None:
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="信源不存在")
    await session.delete(source)
    await session.commit()


@router.post("/{source_id}/test", response_model=SourceTestOut)
async def test_source(
    source_id: int,
    keywords: str | None = None,
    session: AsyncSession = Depends(session_dep),
) -> SourceTestOut:
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="信源不存在")
    collector = collector_for(source)
    if collector is None:
        return SourceTestOut(ok=False, items_found=0, error=f"未知渠道: {source.channel}")
    words = [word.strip() for word in (keywords or "").split(",") if word.strip()]
    if not words:
        words = ["AI"]
    ctx = CollectContext(keywords=words, lookback_hours=168, timeout=20, max_items=5)
    try:
        items = await collector.collect(source, ctx)
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator
        return SourceTestOut(ok=False, items_found=0, error=str(exc)[:300])
    return SourceTestOut(
        ok=True,
        items_found=len(items),
        sample=[
            {
                "title": item.title[:120],
                "url": item.url,
                "published_at": item.published_at.isoformat() if item.published_at else None,
            }
            for item in items[:5]
        ],
    )
