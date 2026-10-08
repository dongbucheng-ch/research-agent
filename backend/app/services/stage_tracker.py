"""流水线阶段追踪:为任务提供真实的阶段耗时与实时进度快照。

设计要点:
- 阶段在创建时一次性 ``plan``,前端从第一秒就能看到完整流水线(其余为 pending);
- 进度更新按 ``throttle_seconds`` 合流,避免高频写库;阶段切换强制上报;
- 快照是纯 JSON,可直接放进 ``JobRun.result``(JSONB),不需要新增数据库列。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# 阶段 key → 中文标签;未知 key 原样使用。
STAGE_LABELS: dict[str, str] = {
    "setup": "配置",
    "sources": "信源",
    "collect": "采集",
    "normalize": "标准化",
    "dedup": "去重",
    "enrich": "富化",
    "score": "评分",
    "store": "入库",
    "expand": "扩词",
    "backfill": "补量",
    "recall": "召回",
    "generate": "生成",
    "persist": "产出入库",
    "push": "推送",
}

ProgressFn = Callable[[dict[str, Any]], None]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Stage:
    key: str
    label: str
    status: str = "pending"  # pending | running | success | skipped | error
    started_at: str | None = None
    ended_at: str | None = None
    seconds: float | None = None
    message: str = ""
    counters: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"key": self.key, "label": self.label, "status": self.status}
        if self.started_at:
            payload["started_at"] = self.started_at
        if self.ended_at:
            payload["ended_at"] = self.ended_at
        if self.seconds is not None:
            payload["seconds"] = round(self.seconds, 2)
        if self.message:
            payload["message"] = self.message
        if self.counters:
            payload["counters"] = dict(self.counters)
        return payload


class StageTracker:
    """记录阶段状态,并把节流后的快照推给 ``on_update``。"""

    def __init__(
        self,
        plan: tuple[str, ...] | list[str] = (),
        *,
        on_update: ProgressFn | None = None,
        throttle_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_update = on_update
        self._throttle = max(0.0, float(throttle_seconds))
        self._clock = clock
        self._started = clock()
        self._last_emit: float | None = None
        self._order: list[str] = []
        self._stages: dict[str, Stage] = {}
        self._marks: dict[str, float] = {}
        self._current: str | None = None
        self._last_message = ""
        self.counters: dict[str, Any] = {}
        self.sources_detail: list[dict[str, Any]] = []
        self.context: dict[str, Any] = {}
        self.plan(plan)

    # ------------------------------------------------------------------ 计划

    def plan(self, keys: tuple[str, ...] | list[str]) -> None:
        for key in keys:
            self._ensure(str(key))

    def _ensure(self, key: str) -> Stage:
        stage = self._stages.get(key)
        if stage is None:
            stage = Stage(key=key, label=STAGE_LABELS.get(key, key))
            self._stages[key] = stage
            self._order.append(key)
        return stage

    # ------------------------------------------------------------------ 状态

    def start(self, key: str, message: str = "", **counters: Any) -> Stage:
        stage = self._ensure(key)
        self._current = key
        stage.status = "running"
        self._marks[key] = self._clock()
        if stage.started_at is None:
            stage.started_at = _now_iso()
        if message:
            stage.message = message
        if counters:
            stage.counters.update(counters)
        self._emit(force=True)
        return stage

    def update(self, message: str = "", **counters: Any) -> None:
        stage = self._stages.get(self._current or "")
        if stage is None:
            return
        if message:
            stage.message = message
        if counters:
            stage.counters.update(counters)
        self._emit()

    def note(self, message: str) -> None:
        """记录最新一条日志(节流上报),不覆盖阶段的摘要 message。"""
        self._last_message = message
        self._emit()

    def finish(self, key: str | None = None, message: str = "", **counters: Any) -> None:
        stage = self._stages.get(key or self._current or "")
        if stage is None:
            return
        mark = self._marks.pop(stage.key, None)
        if mark is not None:
            stage.seconds = self._clock() - mark
        if stage.ended_at is None:
            stage.ended_at = _now_iso()
        stage.status = "success"
        if message:
            stage.message = message
        if counters:
            stage.counters.update(counters)
        self._emit(force=True)

    def skip(self, key: str, message: str = "") -> None:
        stage = self._ensure(key)
        self._marks.pop(key, None)
        stage.status = "skipped"
        stage.seconds = 0.0
        stage.ended_at = _now_iso()
        if message:
            stage.message = message
        self._emit(force=True)

    def fail(self, key: str | None = None, message: str = "") -> None:
        stage = self._stages.get(key or self._current or "")
        if stage is None:
            return
        mark = self._marks.pop(stage.key, None)
        if mark is not None and stage.seconds is None:
            stage.seconds = self._clock() - mark
        stage.status = "error"
        stage.ended_at = _now_iso()
        if message:
            stage.message = message
        self._emit(force=True)

    def skip_rest(self, message: str = "未执行") -> None:
        """把仍是 pending 的阶段标记为跳过(早退 / 无素材时使用)。"""
        touched = False
        for key in self._order:
            stage = self._stages[key]
            if stage.status == "pending":
                stage.status = "skipped"
                stage.seconds = 0.0
                stage.ended_at = _now_iso()
                stage.message = stage.message or message
                touched = True
        if touched:
            self._emit(force=True)

    # ------------------------------------------------------------------ 数据

    def set_counters(self, **counters: Any) -> None:
        self.counters.update(counters)
        self._emit()

    def add_source(self, row: dict[str, Any]) -> dict[str, Any]:
        self.sources_detail.append(row)
        self._emit()
        return row

    # ------------------------------------------------------------------ 输出

    def elapsed(self) -> float:
        return max(0.0, self._clock() - self._started)

    def stages(self) -> list[dict[str, Any]]:
        return [self._stages[key].as_dict() for key in self._order]

    def snapshot(self) -> dict[str, Any]:
        stage = self._stages.get(self._current or "")
        index = self._order.index(self._current) + 1 if self._current in self._order else 0
        return {
            "stage": self._current or "",
            "stage_label": stage.label if stage else "",
            "stage_index": index,
            "stage_total": len(self._order),
            "message": stage.message if stage else self._last_message,
            "last_log": self._last_message,
            "elapsed_seconds": round(self.elapsed(), 2),
            "counters": dict(self.counters),
            "stages": self.stages(),
            "sources_detail": [dict(row) for row in self.sources_detail],
            "updated_at": _now_iso(),
        }

    def attach(self, payload: dict[str, Any]) -> dict[str, Any]:
        """把阶段数据合并进任务结果。"""
        payload["stages"] = self.stages()
        payload["sources_detail"] = [dict(row) for row in self.sources_detail]
        payload["progress"] = self.snapshot()
        payload["elapsed_seconds"] = round(self.elapsed(), 2)
        return payload

    # ------------------------------------------------------------------ 上报

    def _emit(self, *, force: bool = False) -> None:
        if self._on_update is None:
            return
        now = self._clock()
        if not force and self._last_emit is not None and now - self._last_emit < self._throttle:
            return
        self._last_emit = now
        self._on_update(self.snapshot())


__all__ = ["STAGE_LABELS", "Stage", "StageTracker"]
