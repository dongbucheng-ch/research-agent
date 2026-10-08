"""Schemas for items, digests, jobs and stats."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScoreOut(BaseModel):
    heat: float
    relevance: float
    freshness: float
    total: float
    detail: dict[str, Any] = {}


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: str
    content_type: str
    title: str
    url: str
    author: str | None
    published_at: datetime | None
    lang: str | None
    tags: list[Any]
    status: str
    first_seen_at: datetime | None
    source_id: int | None
    source_name: str | None = None
    translated_title: str | None = None
    summary: str | None = None
    # 采集来源:来自哪次采集(研究方向 / 关键词),origin=backfill 表示由辐射词补采得到。
    collect_name: str | None = None
    collect_keywords: list[str] = []
    keyword_hits: list[str] = []
    origin: str | None = None
    score: ScoreOut | None = None


class ItemRefOut(BaseModel):
    """素材被哪些产出物引用(日报 / 完整文章)。"""

    kind: str
    id: int
    title: str
    created_at: datetime | None = None


class ItemDetailOut(ItemOut):
    raw_text: str | None = None
    translated_text: str | None = None
    card: dict[str, Any] | None = None
    references: list[ItemRefOut] = []


class DigestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    lead: str | None
    content_md: str
    highlights: list[Any]
    period_start: datetime | None
    period_end: datetime | None
    item_count: int
    status: str
    model: str | None
    meta: dict[str, Any] = {}
    created_at: datetime


class DigestGenerateIn(BaseModel):
    scope: Literal["global", "topic"] = "global"
    topic: str | None = Field(default=None, max_length=50)
    keywords: list[str] = []
    period_hours: int = Field(default=24, ge=6, le=720)
    max_items: int = Field(default=10, ge=3, le=20)
    github_count: int = Field(default=5, ge=3, le=5)
    github_language: str | None = Field(default=None, max_length=30)
    min_score: int = Field(default=60, ge=0, le=100)
    push_channel_id: int | None = None

    @model_validator(mode="after")
    def _topic_needs_keywords(self) -> DigestGenerateIn:
        if self.scope == "topic" and not [word for word in self.keywords if word.strip()]:
            raise ValueError("定向模式至少需要一个关键词")
        return self


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    topic: str | None
    keywords: list[Any]
    content_md: str
    source_item_ids: list[Any]
    status: str
    model: str | None
    meta: dict[str, Any] = {}
    created_at: datetime


class ArticleGenerateIn(BaseModel):
    topic: str | None = Field(default=None, max_length=50)
    keywords: list[str] = Field(min_length=1)
    period_hours: int = Field(default=168, ge=6, le=720)
    max_sources: int = Field(default=12, ge=3, le=30)
    target_words: int = Field(default=1800, ge=600, le=6000)
    min_score: int = Field(default=60, ge=0, le=100)
    push_channel_id: int | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    status: str
    params: dict[str, Any]
    result: dict[str, Any]
    log: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime | None


class FetchTriggerIn(BaseModel):
    source_id: int | None = None
    # Keywords are typed at collection time; nothing is persisted as a preset.
    name: str | None = None
    keywords: list[str] = []
    exclude_keywords: list[str] = []
    source_ids: list[int] = []
    # 采集流水线硬约束:回看窗口最长 48 小时,入库门槛最低 75 分。
    lookback_hours: int = Field(default=24, ge=1, le=48)
    min_score: int = Field(default=75, ge=75, le=100)
    score_weights: dict[str, float] | None = None
    # 采集范围:info=资讯/新闻/论文(rss+news 引擎),github=代码与模型资源。
    scopes: list[Literal["info", "github"]] = ["info", "github"]
    # GitHub 独立关键词;留空沿用主关键词。
    github_keywords: list[str] = []
    # strict=只按关键词检索;trending_fallback=关键词命中不足时并入热榜。
    github_mode: Literal["strict", "trending_fallback"] = "trending_fallback"
    # 新入库不足时的补量策略:auto=用辐射词自动补采一轮;off=仅提示。
    backfill: Literal["auto", "off"] = "auto"

    @model_validator(mode="after")
    def _normalize_scopes(self) -> FetchTriggerIn:
        if not self.scopes:
            raise ValueError("至少选择一个采集范围")
        ordered = [scope for scope in ("info", "github") if scope in self.scopes]
        if self.scopes != ordered:
            self.scopes = ordered
        return self


class PushTriggerIn(BaseModel):
    """推送任一产出物:target_kind=digest|article;digest_id 保留旧调用兼容。

    可选覆盖:title/source/author/tags(推送弹窗填写,留空走渠道配置或默认)。
    """

    target_kind: Literal["digest", "article"] = "digest"
    target_id: int | None = None
    digest_id: int | None = None
    channel_id: int
    title: str | None = Field(default=None, max_length=255)
    source: str | None = Field(default=None, max_length=128)
    author: str | None = Field(default=None, max_length=128)
    tags: list[str] | None = Field(default=None, max_length=9)

    @model_validator(mode="after")
    def _resolve_target(self) -> PushTriggerIn:
        if self.target_id is None:
            self.target_id = self.digest_id
        if self.target_id is None:
            raise ValueError("target_id(或 digest_id)必填")
        return self


class PushChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern="^(webhook|export)$")
    config: dict[str, Any] = {}
    enabled: bool = True


class PushChannelUpdate(BaseModel):
    name: str | None = None
    kind: str | None = Field(default=None, pattern="^(webhook|export)$")
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class PushChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: str
    config: dict[str, Any]
    enabled: bool
    created_at: datetime


class PushLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_id: int | None
    digest_id: int | None
    target_kind: str | None = None
    target_id: int | None = None
    status: str
    error: str | None
    created_at: datetime | None


class StatsOut(BaseModel):
    items_total: int
    items_today: int
    digests_total: int
    sources_total: int
    sources_active: int
    jobs_running: int
    by_content_type: dict[str, int] = {}
