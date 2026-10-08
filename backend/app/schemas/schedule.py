"""定时采集配置的进出参 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    keywords: list[str] = []
    exclude_keywords: list[str] = []
    source_ids: list[int] = []
    scopes: list[Literal["info", "github"]] = ["info", "github"]
    github_keywords: list[str] = []
    github_mode: Literal["strict", "trending_fallback"] = "trending_fallback"
    backfill: Literal["auto", "off"] = "auto"
    # 与采集流水线一致:回看窗口 ≤48h,入库门槛 ≥75 分。
    lookback_hours: int = Field(default=24, ge=1, le=48)
    min_score: int = Field(default=75, ge=75, le=100)
    interval_minutes: int = Field(default=360, ge=5, le=10080)
    enabled: bool = True
    # 「立即采集并保存为定时任务」时由前端回填,便于展示最近一次任务。
    last_job_id: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> ScheduleIn:
        if not [word for word in self.keywords if str(word).strip()]:
            raise ValueError("定时采集至少需要一个关键词")
        if not self.scopes:
            raise ValueError("至少选择一个采集范围")
        ordered = [scope for scope in ("info", "github") if scope in self.scopes]
        if self.scopes != ordered:
            self.scopes = ordered
        return self


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    source_ids: list[int] | None = None
    scopes: list[Literal["info", "github"]] | None = None
    github_keywords: list[str] | None = None
    github_mode: Literal["strict", "trending_fallback"] | None = None
    backfill: Literal["auto", "off"] | None = None
    lookback_hours: int | None = Field(default=None, ge=1, le=48)
    min_score: int | None = Field(default=None, ge=75, le=100)
    interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    enabled: bool | None = None

    @model_validator(mode="after")
    def _validate(self) -> ScheduleUpdate:
        if self.keywords is not None and not [w for w in self.keywords if str(w).strip()]:
            raise ValueError("关键词不能为空")
        if self.scopes is not None and not self.scopes:
            raise ValueError("至少选择一个采集范围")
        return self


class ScheduleOut(BaseModel):
    id: str
    name: str
    keywords: list[str]
    exclude_keywords: list[str]
    source_ids: list[int]
    scopes: list[str]
    github_keywords: list[str]
    github_mode: str
    backfill: str
    lookback_hours: int
    min_score: int
    interval_minutes: int
    enabled: bool
    created_at: datetime | None = None
    last_run_at: datetime | None = None
    last_job_id: str | None = None
    next_run_at: datetime | None = None
    last_skip: dict | None = None
