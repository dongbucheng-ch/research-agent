"""Background job executor with run records (fetch / digest / push)."""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope
from app.models import JobRun, PushChannel
from app.services.article_service import run_article
from app.services.digest_service import run_digest
from app.services.fetch_service import FETCH_STAGE_KEYS, run_fetch
from app.services.push import send_target
from app.services.stage_tracker import StageTracker

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("pending", "running")


class ProgressFlusher:
    """把运行中的任务进度以节流方式写回 job 行(独立 session,不干扰业务事务)。"""

    def __init__(self, job_id: str, lines: list[str], *, coalesce_seconds: float = 0.4) -> None:
        self._job_id = job_id
        self._lines = lines
        self._coalesce = coalesce_seconds
        self._pending: dict[str, Any] | None = None
        self._task: asyncio.Task | None = None

    def push(self, progress: dict[str, Any]) -> None:
        self._pending = progress
        if self._task is None or self._task.done():
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:  # 非事件循环环境(测试)直接忽略
                return
            self._task = loop.create_task(self._flush())

    async def _flush(self) -> None:
        await asyncio.sleep(self._coalesce)
        payload, self._pending = self._pending, None
        if payload is None:
            return
        try:
            async with session_scope() as session:
                job = await session.get(JobRun, self._job_id)
                if job is None or job.status not in ACTIVE_STATUSES:
                    return
                job.log = "\n".join(self._lines[-500:])
                merged = dict(job.result or {})
                merged["progress"] = payload
                job.result = merged
                await session.commit()
        except Exception:  # noqa: BLE001 - 进度写失败不影响任务本身
            logger.debug("job %s progress flush failed", self._job_id, exc_info=True)
        finally:
            if self._pending is not None:
                self._task = None
                self.push(self._pending)


class JobExecutor:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    async def submit(
        self, session: AsyncSession, kind: str, params: dict[str, Any] | None = None
    ) -> JobRun:
        running = await session.scalar(
            select(JobRun.id)
            .where(JobRun.kind == kind, JobRun.status.in_(ACTIVE_STATUSES))
            .limit(1)
        )
        if running is not None:
            raise RuntimeError(f"已有同类任务在运行中: {running}")
        job = JobRun(kind=kind, params=params or {}, status="pending")
        session.add(job)
        await session.commit()
        await session.refresh(job)
        task = asyncio.create_task(self._execute(job.id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def recover_stale(self) -> int:
        """Fail jobs left behind by a previous process.

        A crash or restart leaves ``pending`` / ``running`` rows behind, and those
        rows would block every future job of the same kind forever.
        """
        async with session_scope() as session:
            rows = list(
                await session.scalars(select(JobRun).where(JobRun.status.in_(ACTIVE_STATUSES)))
            )
            if not rows:
                return 0
            now = datetime.now(UTC)
            for job in rows:
                job.status = "failed"
                job.finished_at = now
                job.result = {"error": "服务重启,任务被中断"}
                job.log = f"{job.log or ''}\n[系统] 服务重启,任务被中断".strip()
                logger.warning("recovered stale job %s (%s)", job.id, job.kind)
            await session.commit()
            return len(rows)

    async def _execute(self, job_id: str) -> None:
        async with session_scope() as session:
            job = await session.get(JobRun, job_id)
            if job is None:
                return
            job.status = "running"
            job.started_at = datetime.now(UTC)
            await session.commit()

            lines: list[str] = ["[系统] 任务开始"]
            flusher = ProgressFlusher(job_id, lines)
            tracker = (
                StageTracker(plan=FETCH_STAGE_KEYS, on_update=flusher.push)
                if job.kind == "fetch"
                else None
            )

            def log(message: str) -> None:
                lines.append(message)
                if tracker is not None:
                    tracker.note(message)
                logger.info("[job %s] %s", job_id, message)

            try:
                params = dict(job.params or {})
                result: dict[str, Any]
                if job.kind == "fetch":
                    result = await run_fetch(
                        session,
                        source_id=params.get("source_id"),
                        spec_params=params,
                        log=log,
                        tracker=tracker,
                    )
                elif job.kind == "digest":
                    result = await run_digest(
                        session,
                        scope=str(params.get("scope") or "global"),
                        topic=params.get("topic"),
                        keywords=params.get("keywords") or [],
                        period_hours=int(params.get("period_hours") or 24),
                        max_items=params.get("max_items"),
                        github_count=int(params.get("github_count") or 5),
                        github_language=params.get("github_language"),
                        min_score=int(params["min_score"])
                        if params.get("min_score") is not None
                        else 60,
                        push_channel_id=params.get("push_channel_id"),
                        log=log,
                    )
                elif job.kind == "article":
                    result = await run_article(
                        session,
                        topic=params.get("topic"),
                        keywords=params.get("keywords") or [],
                        period_hours=int(params.get("period_hours") or 168),
                        max_sources=int(params.get("max_sources") or 12),
                        target_words=int(params.get("target_words") or 1800),
                        min_score=int(params["min_score"])
                        if params.get("min_score") is not None
                        else 60,
                        push_channel_id=params.get("push_channel_id"),
                        log=log,
                    )
                elif job.kind == "push":
                    result = await self._run_push(session, params, log)
                else:
                    raise ValueError(f"未知任务类型: {job.kind}")
                job.status = "succeeded"
                job.result = result or {}
                lines.append("[系统] 任务完成")
            except Exception as exc:  # noqa: BLE001 - job boundary
                logger.exception("job %s failed", job_id)
                if tracker is not None:
                    tracker.fail(message=str(exc))
                job.status = "failed"
                job.result = {"error": str(exc)}
                lines.append(f"[系统] 任务失败: {exc}")
                lines.append(traceback.format_exc()[-2000:])
            finally:
                if tracker is not None:
                    tracker.skip_rest()
                job.log = "\n".join(lines[-500:])
                result_payload = dict(job.result or {})
                if tracker is not None:
                    result_payload.setdefault("stages", tracker.stages())
                    result_payload.setdefault("progress", tracker.snapshot())
                    result_payload.setdefault("elapsed_seconds", round(tracker.elapsed(), 2))
                job.result = result_payload
                job.finished_at = datetime.now(UTC)
                await session.commit()

    async def _run_push(self, session: AsyncSession, params: dict[str, Any], log) -> dict[str, Any]:
        default_kind = "digest" if params.get("digest_id") else ""
        target_kind = str(params.get("target_kind") or default_kind)
        raw_target_id = params.get("target_id") or params.get("digest_id")
        if target_kind not in ("digest", "article") or raw_target_id is None:
            raise ValueError("推送参数不完整(target_kind/target_id)")
        target_id = int(raw_target_id)
        channel = await session.get(PushChannel, int(params["channel_id"]))
        if channel is None:
            raise ValueError("推送渠道不存在")
        overrides = {
            key: params[key]
            for key in ("title", "source", "author", "tags")
            if params.get(key) not in (None, "", [])
        }
        label = "日报" if target_kind == "digest" else "文章"
        push_log = await send_target(
            session,
            target_kind=target_kind,
            target_id=target_id,
            channel=channel,
            overrides=overrides,
        )
        await session.commit()
        if push_log.status == "success":
            log(f"[推送] {channel.name} 推送{label} #{target_id} 成功")
        else:
            log(f"[推送] {channel.name} 推送{label} #{target_id} 失败: {push_log.error}")
        return {
            "push_log_id": push_log.id,
            "status": push_log.status,
            "target_kind": target_kind,
            "target_id": target_id,
        }
