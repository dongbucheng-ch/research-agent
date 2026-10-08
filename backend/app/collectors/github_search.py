"""GitHub / HuggingFace 资源采集器(engine=`github`,preset=`repo` / `skill` / `model`)。

Adapted from Thysrael/Horizon (MIT) — src/scrapers/github.py
保留其做法:可选 token 走环境变量、每个请求带 Accept/UA、限流或失败只记日志不抛。
关键词查询沿用 GitHub 官方检索语法(`OR` + `in:name,description,topics` + `pushed:>=`),
Skills 用 `topic:` 约束,HuggingFace 模型走免鉴权 models API。
踩坑:① `in:readme` 会把「README 里顺带提过该词」的泛化仓库(awesome-* / hackathon 题集)
当成命中,已弃用;② 检索式里带中文词时 GitHub 会返回完全无关的结果,因此中文词不进检索式,
改由 `services.keyword_translate` 先翻成英文再用。
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.collectors.base import (
    BaseCollector,
    CollectContext,
    RawItem,
    get_with_retries,
    make_client,
)
from app.pipeline.text import truncate

if TYPE_CHECKING:
    from app.models import Source

logger = logging.getLogger(__name__)

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
HF_MODELS_URL = "https://huggingface.co/api/models"
MAX_QUERY_KEYWORDS = 8
MAX_PER_KEYWORD = 20


def github_token() -> str | None:
    """GitHub Token 解析顺序:进程环境 → settings(.env)→ 空。"""
    token = os.getenv("RA_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        from app.core.config import get_settings

        token = get_settings().github_token
    return token.strip() if token and token.strip() else None


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def is_searchable(word: str) -> bool:
    """GitHub 检索式只接受非中文词(中文词会让检索结果整体跑偏)。"""
    return not CJK_RE.search(str(word or ""))


def github_search_query(
    *,
    keywords: list[str],
    topic: str | None = None,
    min_stars: int | None = None,
    pushed_after: datetime | None = None,
    created_after: datetime | None = None,
    language: str | None = None,
) -> str:
    """拼 GitHub 仓库检索表达式。

    `pushed_after` 表达「最近还在活跃」,`created_after` 表达「新项目」——
    两者分别对应「最新」与「近期最热」两种口径。
    """
    raw_words = [str(word).strip() for word in keywords if str(word).strip()]
    words = [word for word in raw_words if is_searchable(word)][:MAX_QUERY_KEYWORDS]
    if raw_words and not words:
        # 关键词全是中文且没有译名:宁可不查,也不给「泛化热门仓库」充数
        return ""
    parts: list[str] = []
    if words:
        # 实测(2026-09-30):OR 组外面套括号会被 GitHub 当成另一种解析,结果骤降 ——
        # `(biotech OR biotechnology) in:name,description,topics` 只有 2 条,
        # 去掉括号后 `biotech OR biotechnology in:name,description,topics` 有 11 条。
        terms = " OR ".join(f'"{word}"' if " " in word else word for word in words)
        parts.append(f"{terms} in:name,description,topics")
    if topic:
        parts.append(f"topic:{str(topic).strip()}")
    if language:
        parts.append(f"language:{str(language).strip()}")
    if min_stars:
        parts.append(f"stars:>={int(min_stars)}")
    if pushed_after is not None:
        parts.append(f"pushed:>={pushed_after.astimezone(UTC).strftime('%Y-%m-%d')}")
    if created_after is not None:
        parts.append(f"created:>={created_after.astimezone(UTC).strftime('%Y-%m-%d')}")
    return " ".join(parts)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)


def repo_to_item(repo: dict[str, Any], object_type: str) -> RawItem | None:
    url = str(repo.get("html_url") or "").strip()
    full_name = str(repo.get("full_name") or "").strip()
    if not url or not full_name:
        return None
    topics = [str(t) for t in (repo.get("topics") or []) if str(t).strip()]
    language = str(repo.get("language") or "").strip()
    stars = int(repo.get("stargazers_count") or 0)
    license_info = repo.get("license") or {}
    created = _parse_dt(repo.get("created_at"))
    pushed = _parse_dt(repo.get("pushed_at"))
    stars_per_day = None
    age_days = None
    if created is not None:
        end = pushed or datetime.now(UTC)
        age_days = max(1.0, (end - created).total_seconds() / 86400)
        stars_per_day = round(stars / age_days, 2)
    lines = [str(repo.get("description") or "").strip()]
    if language:
        lines.append(f"语言: {language}")
    if stars:
        detail = f"Stars: {stars}"
        if stars_per_day is not None:
            detail += f"(日均 +{stars_per_day})"
        lines.append(detail)
    if pushed:
        lines.append(f"最近更新: {pushed.strftime('%Y-%m-%d')}")
    if topics:
        lines.append(f"Topics: {', '.join(topics[:10])}")
    return RawItem(
        url=url,
        title=truncate(full_name, 300),
        published_at=pushed or created,
        author=str((repo.get("owner") or {}).get("login") or "") or None,
        raw_text=truncate("\n".join(line for line in lines if line), 4000) or None,
        external_id=str(repo.get("id") or "") or None,
        content_type_hint=object_type,
        metrics={
            "stars": stars,
            "forks": int(repo.get("forks_count") or 0),
            **({"stars_per_day": stars_per_day} if stars_per_day is not None else {}),
        },
        extra={
            "language": language or None,
            "topics": topics,
            "license": license_info.get("spdx_id") if isinstance(license_info, dict) else None,
            "archived": bool(repo.get("archived")),
            "created_at": created.isoformat() if created else None,
            "pushed_at": pushed.isoformat() if pushed else None,
        },
    )


def model_to_item(model: dict[str, Any]) -> RawItem | None:
    model_id = str(model.get("id") or model.get("modelId") or "").strip()
    if not model_id:
        return None
    tags = [str(t) for t in (model.get("tags") or []) if str(t).strip()]
    downloads = int(model.get("downloads") or 0)
    likes = int(model.get("likes") or 0)
    trending_score = model.get("trendingScore")
    pipeline = str(model.get("pipeline_tag") or "").strip()
    lines = [f"模型: {model_id}"]
    if pipeline:
        lines.append(f"任务: {pipeline}")
    lines.append(f"下载量: {downloads} · 点赞: {likes}")
    if tags:
        lines.append(f"标签: {', '.join(tags[:12])}")
    metrics: dict[str, Any] = {"downloads": downloads, "likes": likes}
    if isinstance(trending_score, (int, float)):
        metrics["trending_score"] = float(trending_score)
    return RawItem(
        url=f"https://huggingface.co/{model_id}",
        title=truncate(model_id, 300),
        published_at=_parse_dt(model.get("lastModified")) or _parse_dt(model.get("createdAt")),
        author=model_id.split("/")[0] if "/" in model_id else None,
        raw_text=truncate("\n".join(lines), 4000) or None,
        external_id=model_id,
        content_type_hint="model",
        metrics=metrics,
        extra={"tags": tags, "pipeline_tag": pipeline or None},
    )


class GitHubRepoSearchCollector(BaseCollector):
    """按关键词检索 GitHub 仓库;`object_type` 为 `repo`(通用)或 `skill`(Skills 主题)。

    支持两路查询合并(config):
    - `sorts: ["updated"]` —— 「最新」:最近仍在推送的仓库,按更新时间排序;
    - `sorts: ["stars"]` + `max_age_days` —— 「近期最热」:限定创建时间的新项目按星数排序,
      避免十年前的巨型仓库长期霸榜;热度由 `stars_per_day`(日均新增星)在打分环节衡量。
    """

    def __init__(self, object_type: str) -> None:
        self.object_type = object_type
        self.channel = object_type

    async def collect(self, source: Source, ctx: CollectContext) -> list[RawItem]:
        config = source.config if isinstance(source.config, dict) else {}
        now = datetime.now(UTC)
        sorts = config.get("sorts") or config.get("sort") or ["updated"]
        if isinstance(sorts, str):
            sorts = [sorts]
        per_page = max(1, min(int(config.get("per_page") or 30), 50))
        max_age_days = int(config.get("max_age_days") or 0)
        topic = config.get("topic")
        min_stars = config.get("min_stars")

        headers = {"Accept": "application/vnd.github+json"}
        token = github_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        seen: set[str] = set()
        items: list[RawItem] = []
        async with make_client(ctx.timeout) as client:
            for sort in list(sorts)[:2]:
                recent_star_mode = str(sort) == "stars" and max_age_days > 0
                query = github_search_query(
                    keywords=list(ctx.keywords),
                    topic=topic,
                    min_stars=min_stars,
                    pushed_after=None
                    if recent_star_mode
                    else now - timedelta(hours=max(1, int(ctx.lookback_hours))),
                    created_after=now - timedelta(days=max_age_days) if recent_star_mode else None,
                )
                if not query:
                    query = f"topic:{topic or 'llm'}"
                response = await get_with_retries(
                    client,
                    GITHUB_SEARCH_URL,
                    params={
                        "q": query,
                        "sort": str(sort),
                        "order": "desc",
                        "per_page": str(per_page),
                    },
                    headers=headers,
                )
                if response.status_code in (403, 429):
                    logger.warning(
                        "GitHub 检索被限流(HTTP %s),source=%s", response.status_code, source.name
                    )
                    continue
                response.raise_for_status()
                payload = response.json()
                for repo in payload.get("items") or []:
                    if bool((repo or {}).get("archived")):
                        continue
                    item = repo_to_item(repo, self.object_type)
                    if item is None or item.url in seen:
                        continue
                    seen.add(item.url)
                    items.append(item)
        return items


class HuggingFaceModelCollector(BaseCollector):
    channel = "model"

    async def collect(self, source: Source, ctx: CollectContext) -> list[RawItem]:
        config = source.config if isinstance(source.config, dict) else {}
        words = [str(word).strip() for word in ctx.keywords if str(word).strip()]
        queries = [str(config.get("query")).strip()] if config.get("query") else words[:3]
        if not queries:
            return []
        limit = max(1, min(int(config.get("per_keyword_limit") or MAX_PER_KEYWORD), 50))
        sort = str(config.get("sort") or "trendingScore")

        seen: set[str] = set()
        items: list[RawItem] = []
        async with make_client(ctx.timeout) as client:
            for query in queries:
                response = await get_with_retries(
                    client,
                    HF_MODELS_URL,
                    params={
                        "search": query,
                        "sort": sort,
                        "direction": "-1",
                        "limit": str(limit),
                    },
                )
                if response.status_code >= 400:
                    logger.warning(
                        "HuggingFace 检索失败(HTTP %s),source=%s", response.status_code, source.name
                    )
                    continue
                payload = response.json()
                if not isinstance(payload, list):
                    continue
                for model in payload:
                    item = model_to_item(model if isinstance(model, dict) else {})
                    if item is None or item.external_id in seen:
                        continue
                    seen.add(str(item.external_id))
                    items.append(item)
        return items
