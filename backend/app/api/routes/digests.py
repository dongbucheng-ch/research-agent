"""Digest listing and generation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_executor, session_dep
from app.api.routes.items import _collect_relations, _item_out
from app.models import Digest, DigestItem, Item
from app.schemas.config import Page
from app.schemas.content import DigestGenerateIn, DigestOut, ItemOut, JobOut

router = APIRouter(prefix="/digests", tags=["digests"])


@router.get("", response_model=Page[DigestOut])
async def list_digests(
    page: int = 1,
    page_size: int = 10,
    session: AsyncSession = Depends(session_dep),
) -> Page[DigestOut]:
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    stmt = select(Digest).order_by(Digest.created_at.desc(), Digest.id.desc())
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(await session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)))
    return Page(items=[DigestOut.model_validate(row) for row in rows], total=total)


@router.post("/generate", response_model=JobOut, status_code=202)
async def generate_digest(
    payload: DigestGenerateIn,
    request: Request,
    session: AsyncSession = Depends(session_dep),
) -> JobOut:
    executor = get_executor(request)
    try:
        job = await executor.submit(session, "digest", payload.model_dump(exclude_none=True))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JobOut.model_validate(job)


@router.get("/{digest_id}/items", response_model=list[ItemOut])
async def list_digest_items(
    digest_id: int, session: AsyncSession = Depends(session_dep)
) -> list[ItemOut]:
    """日报引用的素材(素材池 → 产出物 → 溯源)。"""
    digest = await session.get(Digest, digest_id)
    if digest is None:
        raise HTTPException(status_code=404, detail="日报不存在")
    rows = list(
        await session.scalars(
            select(Item)
            .join(DigestItem, DigestItem.item_id == Item.id)
            .where(DigestItem.digest_id == digest_id)
            .order_by(DigestItem.position, Item.id)
        )
    )
    source_names = await _collect_relations(session, rows)
    return [_item_out(item, source_names) for item in rows]


@router.get("/{digest_id}", response_model=DigestOut)
async def get_digest(digest_id: int, session: AsyncSession = Depends(session_dep)) -> DigestOut:
    digest = await session.get(Digest, digest_id)
    if digest is None:
        raise HTTPException(status_code=404, detail="日报不存在")
    return DigestOut.model_validate(digest)


@router.delete("/{digest_id}", status_code=204)
async def delete_digest(digest_id: int, session: AsyncSession = Depends(session_dep)) -> None:
    digest = await session.get(Digest, digest_id)
    if digest is None:
        raise HTTPException(status_code=404, detail="日报不存在")
    await session.delete(digest)
    await session.commit()
