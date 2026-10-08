"""定时采集:配置收藏(settings 表,不新增表)+ 进程内 asyncio 调度器。

存储:`settings[key=collection_schedules] = {"schedules": [...]}`;
调度:lifespan 启动一个 60s tick 的协程,到点的配置提交一次 fetch 任务;
若有同类任务运行中则跳过,并记录 `last_skip`(不推进 next_run_at,下个 tick 重试)。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope
from app.services.app_settings import get_setting, set_setting
from app.services.jobs import JobExecutor

logger = logging.getLogger(__name__)

SCHEDULES_KEY = "collection_schedules"
TICK_SECONDS = 60
MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 10080

PARAM_FIELDS = (
    "keywords",
    "exclude_keywords",
    "source_ids",
    "scopes",
    "github_keywords",
    "github_mode",
    "backfill",
    "lookback_hours",
    "min_score",
)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def interval_minutes(schedule: dict[str, Any]) -> int:
    value = int(schedule.get("interval_minutes") or 360)
    return max(MIN_INTERVAL_MINUTES, min(MAX_INTERVAL_MINUTES, value))


def next_run_at(schedule: dict[str, Any], *, now: datetime | None = None) -> datetime | None:
    """下次运行时间:enabled 时按 `last_run_at + interval` 计算。"""
    if not schedule.get("enabled", True):
        return parse_dt(schedule.get("next_run_at")) if schedule.get("next_run_at") else None
    now = now or datetime.now(UTC)
    base = parse_dt(schedule.get("last_run_at")) or now
    return base + timedelta(minutes=interval_minutes(schedule))


def fetch_params(schedule: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"name": schedule.get("name") or "定时采集"}
    for field in PARAM_FIELDS:
        value = schedule.get(field)
        if value is not None:
            params[field] = value
    return params


async def list_schedules(session: AsyncSession) -> list[dict[str, Any]]:
    stored = await get_setting(session, SCHEDULES_KEY, {}) or {}
    if isinstance(stored, list):
        items = stored
    else:
        items = stored.get("schedules") or []
    return [item for item in items if isinstance(item, dict)]


async def _save(session: AsyncSession, items: list[dict[str, Any]]) -> None:
    await set_setting(session, SCHEDULES_KEY, {"schedules": items})


def _new_schedule(payload: dict[str, Any]) -> dict[str, Any]:
    item = {
        "id": uuid.uuid4().hex[:10],
        "created_at": _iso(datetime.now(UTC)),
        "last_run_at": None,
        "last_job_id": None,
        "last_skip": None,
    }
    item.update(payload)
    item["next_run_at"] = _iso(next_run_at(item))
    return item


async def create_schedule(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    items = await list_schedules(session)
    item = _new_schedule(payload)
    items.append(item)
    await _save(session, items)
    return item


async def update_schedule(
    session: AsyncSession, schedule_id: str, changes: dict[str, Any]
) -> dict[str, Any] | None:
    items = await list_schedules(session)
    for item in items:
        if item.get("id") == schedule_id:
            item.update(changes)
            if "enabled" in changes:
                # 停用时保留 next_run_at 供展示;重新启用按最新配置顺延。
                item["next_run_at"] = _iso(next_run_at(item))
                item["last_skip"] = None
            await _save(session, items)
            return item
    return None


async def delete_schedule(session: AsyncSession, schedule_id: str) -> bool:
    items = await list_schedules(session)
    remaining = [item for item in items if item.get("id") != schedule_id]
    if len(remaining) == len(items):
        return False
    await _save(session, remaining)
    return True


async def run_schedule_now(
    session: AsyncSession, executor: JobExecutor, schedule: dict[str, Any]
) -> dict[str, Any]:
    """立即执行一次定时配置,并更新 last_run_at / next_run_at / last_job_id。"""
    job = await executor.submit(session, "fetch", fetch_params(schedule))
    items = await list_schedules(session)
    now = datetime.now(UTC)
    updated: dict[str, Any] = dict(schedule)
    for item in items:
        if item.get("id") == schedule.get("id"):
            item["last_run_at"] = _iso(now)
            item["last_job_id"] = job.id
            item["next_run_at"] = _iso(now + timedelta(minutes=interval_minutes(item)))
            item["last_skip"] = None
            updated = item
            break
    await _save(session, items)
    return {"job": job, "schedule": updated}


class CollectionScheduler:
    """进程内调度器:每 60s 检查一次到期配置(单实例部署足够)。"""

    def __init__(self, executor: JobExecutor) -> None:
        self._executor = executor
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="collection-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        logger.info("collection scheduler started (tick %ss)", TICK_SECONDS)
        while True:
            try:
                triggered = await self.tick()
                if triggered:
                    logger.info("schedules triggered: %s", ", ".join(triggered))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - 调度失败不影响服务
                logger.exception("scheduler tick failed")
            await asyncio.sleep(TICK_SECONDS)

    async def tick(self) -> list[str]:
        triggered: list[str] = []
        now = datetime.now(UTC)
        async with session_scope() as session:
            items = await list_schedules(session)
            changed = False
            for item in items:
                if not item.get("enabled", True):
                    continue
                due = parse_dt(item.get("next_run_at"))
                if due is None:
                    item["next_run_at"] = _iso(
                        now + timedelta(minutes=interval_minutes(item))
                    )
                    changed = True
                    continue
                if due > now:
                    continue
                try:
                    job = await self._executor.submit(session, "fetch", fetch_params(item))
                except RuntimeError as exc:
                    item["last_skip"] = {"at": _iso(now), "reason": str(exc)}
                    changed = True
                    logger.warning("schedule %s skipped: %s", item.get("id"), exc)
                    continue
                item["last_run_at"] = _iso(now)
                item["last_job_id"] = job.id
                item["next_run_at"] = _iso(now + timedelta(minutes=interval_minutes(item)))
                item["last_skip"] = None
                triggered.append(str(item.get("id")))
                changed = True
            if changed:
                await _save(session, items)
                # session_scope 不会自动提交,这里必须显式 commit,
                # 否则 next_run_at 不推进,同一个配置会被每个 tick 反复触发。
                await session.commit()
        return triggered


__all__ = [
    "SCHEDULES_KEY",
    "TICK_SECONDS",
    "CollectionScheduler",
    "create_schedule",
    "delete_schedule",
    "fetch_params",
    "interval_minutes",
    "list_schedules",
    "next_run_at",
    "parse_dt",
    "run_schedule_now",
    "update_schedule",
]
