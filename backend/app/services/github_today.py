"""GitHub「今日最新最热」实时取数(日报 GitHub 板块专用)。

口径:
- 今日热榜:`github.com/trending?since=daily`,即过去 24 小时新增 star 排序,是「今日最热」的权威来源;
- 关键词补位:今日榜命中不足 3 条时,用官方 Search API 补两路 ——
  「新锐」近 NEW_DAYS 天创建按星速排序、「活跃」近 ACTIVE_DAYS 天推送按总星排序,
  星速 `stars_per_day` 由 `repo_to_item` 同口径计算,避免多年前的大仓库霸榜。

失败隔离:任何一路失败只记日志返回空,不阻断日报生成。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.collectors.base import get_with_retries, make_client
from app.collectors.github_search import (
    GITHUB_SEARCH_URL,
    github_search_query,
    github_token,
    repo_to_item,
)
from app.collectors.github_trending import fetch_trending_repos

logger = logging.getLogger(__name__)

NEW_DAYS = 45
ACTIVE_DAYS = 7
MIN_STARS_NEW = 10
MIN_STARS_ACTIVE = 30
MAX_KEYWORDS = 8


def match_keywords(repo: dict[str, Any], keywords: list[str]) -> list[str]:
    haystack = " ".join(
        str(repo.get(field) or "") for field in ("full_name", "description", "language")
    ).lower()
    return [word for word in keywords if word.strip() and word.strip().lower() in haystack]


def pick_trending(
    repos: list[dict[str, Any]], keywords: list[str], limit: int
) -> list[dict[str, Any]]:
    """今日榜按关键词过滤(无关键词则不过滤),按今日新增 star 排序。"""
    picked = [repo for repo in repos if not keywords or match_keywords(repo, keywords)]
    picked.sort(key=lambda repo: int(repo.get("stars_today") or 0), reverse=True)
    return [_trending_candidate(repo) for repo in picked[:limit]]


def _trending_candidate(repo: dict[str, Any]) -> dict[str, Any]:
    stars_today = int(repo.get("stars_today") or 0)
    return {
        "full_name": str(repo.get("full_name") or "").strip(),
        "url": str(repo.get("url") or "").strip(),
        "description": str(repo.get("description") or "").strip(),
        "language": str(repo.get("language") or "").strip(),
        "stars_total": int(repo.get("stars_total") or 0),
        "stars_today": stars_today,
        "stars_per_day": None,
        "source": "trending",
        "hot": f"今日 +{stars_today} ★" if stars_today else "今日榜单",
    }


def _search_candidate(repo: dict[str, Any]) -> dict[str, Any] | None:
    item = repo_to_item(repo, "repo")
    if item is None:
        return None
    stars = int(item.metrics.get("stars") or 0)
    per_day = item.metrics.get("stars_per_day")
    hot = f"日均 +{per_day} ★" if per_day else f"★ {stars}"
    return {
        "full_name": str(repo.get("full_name") or "").strip(),
        "url": item.url,
        "description": str(repo.get("description") or "").strip(),
        "language": str(repo.get("language") or "").strip(),
        "topics": [str(topic) for topic in (repo.get("topics") or [])][:6],
        "stars_total": stars,
        "stars_today": 0,
        "stars_per_day": per_day,
        "source": "search",
        "hot": hot,
    }


async def _search_lane(
    *,
    keywords: list[str],
    min_stars: int,
    limit: int,
    timeout: float,
    sort: Literal["stars", "velocity"],
    language: str | None = None,
    created_after: datetime | None = None,
    pushed_after: datetime | None = None,
    topic: str | None = None,
) -> list[dict[str, Any]]:
    query = github_search_query(
        keywords=keywords,
        topic=topic,
        min_stars=min_stars,
        created_after=created_after,
        pushed_after=pushed_after,
        language=language,
    )
    if not query:
        return []
    headers = {"Accept": "application/vnd.github+json"}
    token = github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with make_client(timeout) as client:
            response = await get_with_retries(
                client,
                GITHUB_SEARCH_URL,
                params={
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": str(max(1, min(limit * 2, 30))),
                },
                headers=headers,
            )
    except Exception:  # noqa: BLE001 - 取数失败不阻断日报
        logger.warning("GitHub 检索失败(网络),supplement skipped", exc_info=True)
        return []
    if response.status_code in (403, 429):
        logger.warning("GitHub 检索被限流(HTTP %s),supplement skipped", response.status_code)
        return []
    if response.status_code >= 400:
        logger.warning("GitHub 检索失败(HTTP %s)", response.status_code)
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    candidates = [
        candidate
        for repo in (payload.get("items") or [])
        if isinstance(repo, dict) and not repo.get("archived")
        if (candidate := _search_candidate(repo)) is not None
    ]
    if sort == "velocity":
        candidates.sort(key=lambda entry: float(entry.get("stars_per_day") or 0), reverse=True)
    return candidates


def _merge(groups: list[list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for group in groups:
        for candidate in group:
            name = str(candidate.get("full_name") or "")
            if not name or name in seen:
                continue
            seen.add(name)
            merged.append(candidate)
            if len(merged) >= limit:
                return merged
    return merged


async def _fetch_trending(*, language: str | None, timeout: float) -> list[dict[str, Any]]:
    """今日榜取数:网络抖动由 `get_with_retries` 内部重试,仍失败由调用方降级。"""
    return await fetch_trending_repos(since="daily", language=language, timeout=timeout)


async def collect_github_today(
    *,
    keywords: list[str] | None = None,
    limit: int = 5,
    language: str | None = None,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    """取「今日最新最热」仓库:今日榜优先,关键词命中不足时检索补位。"""
    words = [str(word).strip() for word in (keywords or []) if str(word).strip()][:MAX_KEYWORDS]
    limit = max(1, min(int(limit), 10))
    try:
        repos = await _fetch_trending(language=language, timeout=timeout)
    except Exception:  # noqa: BLE001 - 网络受限时退化为检索
        logger.warning("GitHub Trending 取数失败,改为关键词检索补位", exc_info=True)
        repos = []
    trending = pick_trending(repos, words, limit)
    if words and len(trending) >= 3:
        return trending[:limit]
    if not words:
        if trending:
            return trending[:limit]
        # 全局兜底:今日榜取数失败时,用「近 NEW_DAYS 天新锐高星」检索补位
        # (keywords 为空时检索式会为空,所以这里用 topic 兜底)
        fallback = await _search_lane(
            keywords=[],
            topic="llm",
            min_stars=100,
            limit=limit,
            timeout=timeout,
            language=language,
            created_after=datetime.now(UTC) - timedelta(days=NEW_DAYS),
            sort="velocity",
        )
        logger.info("GitHub Trending 不可用,兜底检索返回 %s 条", len(fallback))
        return fallback

    now = datetime.now(UTC)
    new_hot = await _search_lane(
        keywords=words,
        min_stars=MIN_STARS_NEW,
        limit=limit,
        timeout=timeout,
        language=language,
        created_after=now - timedelta(days=NEW_DAYS),
        sort="velocity",
    )
    merged = _merge([trending, new_hot], limit)
    if len(merged) >= 3:
        return merged
    active_hot = await _search_lane(
        keywords=words,
        min_stars=MIN_STARS_ACTIVE,
        limit=limit,
        timeout=timeout,
        language=language,
        pushed_after=now - timedelta(days=ACTIVE_DAYS),
        sort="stars",
    )
    return _merge([trending, new_hot, active_hot], limit)
