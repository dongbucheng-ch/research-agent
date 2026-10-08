"""Job center: run records and manual triggers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_executor, session_dep
from app.models import JobRun
from app.schemas.config import Page
from app.schemas.content import FetchTriggerIn, JobOut, PushTriggerIn

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=Page[JobOut])
async def list_jobs(
    kind: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(session_dep),
) -> Page[JobOut]:
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    stmt = select(JobRun).order_by(JobRun.created_at.desc(), JobRun.id.desc())
    if kind:
        stmt = stmt.where(JobRun.kind == kind)
    if status:
        stmt = stmt.where(JobRun.status == status)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(await session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)))
    return Page(items=[JobOut.model_validate(row) for row in rows], total=total)


@router.post("/fetch", response_model=JobOut, status_code=202)
async def trigger_fetch(
    payload: FetchTriggerIn,
    request: Request,
    session: AsyncSession = Depends(session_dep),
) -> JobOut:
    executor = get_executor(request)
    try:
        job = await executor.submit(session, "fetch", payload.model_dump(exclude_none=True))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JobOut.model_validate(job)


@router.post("/push", response_model=JobOut, status_code=202)
async def trigger_push(
    payload: PushTriggerIn,
    request: Request,
    session: AsyncSession = Depends(session_dep),
) -> JobOut:
    executor = get_executor(request)
    try:
        job = await executor.submit(session, "push", payload.model_dump())
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JobOut.model_validate(job)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, session: AsyncSession = Depends(session_dep)) -> JobOut:
    job = await session.get(JobRun, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return JobOut.model_validate(job)
