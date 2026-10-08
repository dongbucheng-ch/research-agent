"""Three-dimension scoring: relevance, heat and freshness."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

FRESHNESS_TAU_HOURS = {
    "paper": 168.0,
    "tech": 72.0,
    "industry": 48.0,
    "community": 24.0,
    # 资源类对象不会「过期」,用更长的衰减常数,热度主要由平台指标决定
    "repo": 720.0,
    "skill": 720.0,
    "model": 720.0,
}
DEFAULT_TAU_HOURS = 72.0

DEFAULT_WEIGHTS = {"relevance": 0.45, "heat": 0.35, "freshness": 0.20}


@dataclass
class ScoreResult:
    relevance: float
    heat: float
    freshness: float
    total: float
    detail: dict[str, Any] = field(default_factory=dict)


def keyword_relevance(text: str, keywords: list[dict[str, Any]]) -> tuple[float, list[str]]:
    """Weighted keyword hit score in 0-100. keywords: [{word, weight, kind, group?}]。

    同义/译名用 `group` 归组(缺省即 `word` 本身):一组内命中任意一个即按该组权重计一次,
    这样「生物科技 / biotech」这类中文词 + LLM 译名不会互相稀释相关度。
    """
    haystack = (text or "").lower()
    include = [k for k in keywords if k.get("kind", "include") == "include"]
    if not include or not haystack:
        return 0.0, []
    groups: dict[str, list[dict[str, Any]]] = {}
    for keyword in include:
        key = str(keyword.get("group") or keyword.get("word") or "").strip().lower()
        if key:
            groups.setdefault(key, []).append(keyword)
    hit_weight = 0.0
    total_weight = 0.0
    hits: list[str] = []
    for members in groups.values():
        weights = [float(k.get("weight") or 1.0) for k in members]
        total_weight += max(weights) if weights else 1.0
        matched = [
            k
            for k in members
            if str(k.get("word") or "").lower() and str(k.get("word") or "").lower() in haystack
        ]
        if matched:
            hit_weight += max(float(k.get("weight") or 1.0) for k in matched)
            hits.extend(str(k.get("word")) for k in matched)
    if hit_weight <= 0:
        return 0.0, []
    ratio = hit_weight / max(1.0, min(total_weight, 6.0))
    return round(min(100.0, 100.0 * ratio), 2), hits


def excluded_by_keywords(text: str, keywords: list[dict[str, Any]]) -> str | None:
    haystack = (text or "").lower()
    for keyword in keywords:
        if keyword.get("kind") != "exclude":
            continue
        word = str(keyword.get("word") or "").lower()
        if word and word in haystack:
            return str(keyword.get("word"))
    return None


def freshness_score(
    published_at: datetime | None,
    content_type: str,
    now: datetime | None = None,
) -> float:
    if published_at is None:
        return 40.0
    moment = now or datetime.now(UTC)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    age_hours = max(0.0, (moment - published_at).total_seconds() / 3600)
    tau = FRESHNESS_TAU_HOURS.get(content_type, DEFAULT_TAU_HOURS)
    return round(100.0 * math.exp(-age_hours / tau), 2)


def metric_heat_score(metrics: dict[str, Any] | None) -> float | None:
    """把平台指标换算成 0-100 热度。

    按来源类型分套:GitHub 榜单(总星+今日新增)、仓库检索(星速)、
    HuggingFace 模型(下载/点赞)、Hacker News(分数)。
    """
    if not metrics:
        return None
    if "stars_total" in metrics or "stars_today" in metrics:
        # GitHub Trending:总星数 + 今日新增星
        total = float(metrics.get("stars_total") or 0)
        today = float(metrics.get("stars_today") or 0)
        total_score = min(1.0, math.log10(1 + total) / 5.0) * 100
        today_score = min(1.0, today / 300.0) * 100
        return round(0.55 * total_score + 0.45 * today_score, 2)
    if "downloads" in metrics or "likes" in metrics:
        # HuggingFace 模型:下载量为主,点赞为辅
        downloads = float(metrics.get("downloads") or 0)
        likes = float(metrics.get("likes") or 0)
        download_score = min(1.0, math.log10(1 + downloads) / 6.0) * 100
        like_score = min(1.0, math.log10(1 + likes) / 3.0) * 100
        return round(0.6 * download_score + 0.4 * like_score, 2)
    if "stars_per_day" in metrics:
        # 仓库检索:用「日均新增星」衡量当下热度,避免老牌大仓库长期霸榜
        velocity = float(metrics.get("stars_per_day") or 0)
        velocity_score = min(1.0, math.log10(1 + velocity) / 2.2) * 100
        total_score = min(1.0, math.log10(1 + float(metrics.get("stars") or 0)) / 5.0) * 100
        return round(0.7 * velocity_score + 0.3 * total_score, 2)
    if "stars" in metrics:
        stars = float(metrics.get("stars") or 0)
        return round(min(1.0, math.log10(1 + stars) / 5.0) * 100, 2)
    if "points" in metrics:
        points = float(metrics.get("points") or 0)
        return round(min(1.0, math.log10(1 + points) / 3.0) * 100, 2)
    if "score" in metrics:
        # Hacker News:分数 + 评论数
        score = float(metrics.get("score") or 0)
        comments = float(metrics.get("comments") or 0)
        score_part = min(1.0, math.log10(1 + score) / 3.0) * 100
        comment_part = min(1.0, math.log10(1 + comments) / 2.5) * 100
        return round(0.75 * score_part + 0.25 * comment_part, 2)
    return None


def combine_scores(
    *,
    keyword_rel: float,
    llm_rel: float | None,
    llm_heat: float | None,
    metric_heat: float | None,
    freshness: float,
    weights: dict[str, float] | None = None,
    keyword_hits: list[str] | None = None,
) -> ScoreResult:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    relevance = 0.6 * keyword_rel + 0.4 * llm_rel if llm_rel is not None else keyword_rel
    if metric_heat is not None:
        heat = metric_heat
    elif llm_heat is not None:
        heat = llm_heat
    else:
        heat = 45.0
    total = w["relevance"] * relevance + w["heat"] * heat + w["freshness"] * freshness
    detail = {
        "keyword_relevance": round(keyword_rel, 2),
        "llm_relevance": llm_rel,
        "metric_heat": metric_heat,
        "llm_heat": llm_heat,
        "keyword_hits": keyword_hits or [],
        "weights": w,
    }
    return ScoreResult(
        relevance=round(relevance, 2),
        heat=round(heat, 2),
        freshness=round(freshness, 2),
        total=round(total, 2),
        detail=detail,
    )
