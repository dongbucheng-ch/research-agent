"""定时采集配置:收藏(settings 表)+ 立即执行。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_executor, session_dep
from app.schemas.content import JobOut
from app.schemas.schedule import ScheduleIn, ScheduleOut, ScheduleUpdate
from app.services.schedules import (
    create_schedule,
    delete_schedule,
    list_schedules,
    next_run_at,
    run_schedule_now,
    update_schedule,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _out(item: dict[str, Any]) -> ScheduleOut:
    data = dict(item)
    if not data.get("next_run_at"):
        computed = next_run_at(data)
        data["next_run_at"] = computed.isoformat() if computed else None
    return ScheduleOut.model_validate(data)


@router.get("", response_model=list[ScheduleOut])
async def list_schedules_route(
    session: AsyncSession = Depends(session_dep),
) -> list[ScheduleOut]:
    return [_out(item) for item in await list_schedules(session)]


@router.post("", response_model=ScheduleOut, status_code=201)
async def create_schedule_route(
    payload: ScheduleIn, session: AsyncSession = Depends(session_dep)
) -> ScheduleOut:
    item = await create_schedule(session, payload.model_dump(exclude_none=True))
    await session.commit()
    return _out(item)


@router.put("/{schedule_id}", response_model=ScheduleOut)
async def update_schedule_route(
    schedule_id: str,
    payload: ScheduleUpdate,
    session: AsyncSession = Depends(session_dep),
) -> ScheduleOut:
    item = await update_schedule(session, schedule_id, payload.model_dump(exclude_unset=True))
    if item is None:
        raise HTTPException(status_code=404, detail="定时配置不存在")
    await session.commit()
    return _out(item)


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule_route(
    schedule_id: str, session: AsyncSession = Depends(session_dep)
) -> None:
    if not await delete_schedule(session, schedule_id):
        raise HTTPException(status_code=404, detail="定时配置不存在")
    await session.commit()


@router.post("/{schedule_id}/run", response_model=JobOut, status_code=202)
async def run_schedule_route(
    schedule_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dep),
) -> JobOut:
    target = next(
        (item for item in await list_schedules(session) if item.get("id") == schedule_id), None
    )
    if target is None:
        raise HTTPException(status_code=404, detail="定时配置不存在")
    try:
        result = await run_schedule_now(session, get_executor(request), target)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return JobOut.model_validate(result["job"])
