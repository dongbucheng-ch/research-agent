"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.services.jobs import JobExecutor


async def session_dep() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


async def require_token(authorization: str | None = Header(default=None)) -> None:
    token = (get_settings().api_token or "").strip()
    if not token:
        return
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api token")


def get_executor(request: Request) -> JobExecutor:
    executor = getattr(request.app.state, "executor", None)
    if executor is None:
        raise HTTPException(status_code=503, detail="job executor not ready")
    return executor
