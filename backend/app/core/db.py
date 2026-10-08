"""Async SQLAlchemy engine and session helpers."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.models import Base

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().db_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with session_scope() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


# 启动时的增量 DDL(Postgres;create_all 不会给已存在的表补列)。
ADDITIVE_SCHEMA_DDL = (
    "ALTER TABLE digests ADD COLUMN IF NOT EXISTS meta JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE push_logs ADD COLUMN IF NOT EXISTS target_kind VARCHAR(20)",
    "ALTER TABLE push_logs ADD COLUMN IF NOT EXISTS target_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_push_logs_target ON push_logs (target_kind, target_id)",
)


async def ensure_schema() -> None:
    """建表 + 幂等补列;补列失败只记日志,不阻断启动。"""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with engine.begin() as conn:
            for statement in ADDITIVE_SCHEMA_DDL:
                await conn.execute(text(statement))
    except Exception:  # noqa: BLE001 - 老库补列失败不应阻断启动
        logger.exception("additive schema upgrade failed")
