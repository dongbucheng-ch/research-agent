"""Schemas for sources and settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    channel: str = Field(min_length=1, max_length=30)
    collector_kind: str = Field(default="stream", pattern="^(stream|trend|search)$")
    url: str = Field(min_length=1)
    config: dict[str, Any] = {}
    tier: str = Field(default="B", pattern="^[SABC]$")
    enabled: bool = True
    fetch_interval_minutes: int = Field(default=60, ge=5, le=1440)


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    channel: str | None = None
    collector_kind: str | None = Field(default=None, pattern="^(stream|trend|search)$")
    url: str | None = None
    config: dict[str, Any] | None = None
    tier: str | None = Field(default=None, pattern="^[SABC]$")
    enabled: bool | None = None
    status: str | None = Field(default=None, pattern="^(active|paused|degraded|archived)$")
    fetch_interval_minutes: int | None = Field(default=None, ge=5, le=1440)


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    channel: str
    collector_kind: str
    url: str
    config: dict[str, Any]
    engine: str = ""
    preset: str = ""
    object_type: str = ""
    tier: str
    status: str
    enabled: bool
    fetch_interval_minutes: int
    quality_score: float
    consecutive_failures: int
    last_error: str | None
    last_fetch_at: datetime | None
    last_success_at: datetime | None
    created_at: datetime


class SourceTestOut(BaseModel):
    ok: bool
    items_found: int
    sample: list[dict[str, Any]] = []
    error: str | None = None


class RecommendedSource(BaseModel):
    key: str
    name: str
    channel: str
    collector_kind: str
    url: str
    config: dict[str, Any] = {}
    tier: str = "B"
    category: str | None = None
    description: str | None = None


class DiscoverIn(BaseModel):
    """信源发现请求:输入 GitHub 仓库 / OPML / 页面 URL。"""

    url: str = Field(min_length=4, max_length=500)
    limit: int = Field(default=60, ge=1, le=300)


class DiscoverCandidateOut(BaseModel):
    name: str
    url: str
    ok: bool = False
    entries: int = 0
    latest: str | None = None
    title: str | None = None
    error: str | None = None
    already_exists: bool = False


class DiscoverOut(BaseModel):
    source_url: str
    ok_count: int = 0
    candidates: list[DiscoverCandidateOut] = []


class ImportCandidateIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    url: str = Field(min_length=1, max_length=500)
    channel: str = Field(default="rss", min_length=1, max_length=30)
    tier: str = Field(default="B", pattern="^[SABC]$")


class ImportCandidatesIn(BaseModel):
    items: list[ImportCandidateIn] = Field(min_length=1, max_length=200)


class SourceStatOut(BaseModel):
    """单个信源近 N 天的产出质量:候选(进入去重) / 入库 / 均分 / 最近入库。"""

    source_id: int
    candidates: int = 0
    ingested: int = 0
    avg_score: float | None = None
    last_item_at: datetime | None = None


class LLMSettingsIn(BaseModel):
    enabled: bool = True
    base_url: str = ""
    model: str = ""
    api_key: str | None = None
    protocol: str = "openai_chat"
    timeout_seconds: int = Field(default=180, ge=10, le=600)
    max_concurrency: int = Field(default=3, ge=1, le=16)
    translate_enabled: bool = True


class LLMSettingsOut(BaseModel):
    enabled: bool
    base_url: str
    model: str
    api_key_masked: str
    protocol: str
    timeout_seconds: int
    max_concurrency: int
    translate_enabled: bool


class LLMTestIn(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


class LLMTestOut(BaseModel):
    ok: bool
    message: str
    latency_ms: int | None = None


class GeneralSettingsIn(BaseModel):
    fetch_lookback_hours: int | None = Field(default=None, ge=1, le=48)
    fetch_max_concurrency: int | None = Field(default=None, ge=1, le=32)
    # 单轮候选/富化上限(超出部分零成本降级);默认 100,可调上限 500。
    enrich_max_items: int | None = Field(default=None, ge=1, le=500)
    # 批量富化的分块大小(单次请求条数)。
    enrich_batch_size: int | None = Field(default=None, ge=1, le=20)
