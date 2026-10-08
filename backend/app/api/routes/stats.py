"""Dashboard statistics."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import session_dep
from app.models import Digest, Item, JobRun, Source
from app.schemas.content import StatsOut

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview", response_model=StatsOut)
async def overview(session: AsyncSession = Depends(session_dep)) -> StatsOut:
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    items_total = await session.scalar(select(func.count()).select_from(Item)) or 0
    items_today = (
        await session.scalar(
            select(func.count()).select_from(Item).where(Item.first_seen_at >= day_start)
        )
        or 0
    )
    digests_total = await session.scalar(select(func.count()).select_from(Digest)) or 0
    sources_total = await session.scalar(select(func.count()).select_from(Source)) or 0
    sources_active = (
        await session.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.enabled.is_(True), Source.status == "active")
        )
        or 0
    )
    jobs_running = (
        await session.scalar(
            select(func.count())
            .select_from(JobRun)
            .where(JobRun.status.in_(("pending", "running")))
        )
        or 0
    )
    type_rows = await session.execute(
        select(Item.content_type, func.count()).group_by(Item.content_type)
    )
    return StatsOut(
        items_total=items_total,
        items_today=items_today,
        digests_total=digests_total,
        sources_total=sources_total,
        sources_active=sources_active,
        jobs_running=jobs_running,
        by_content_type={row[0]: row[1] for row in type_rows.all()},
    )
