"""Collector registry: 3 engines (`rss` / `news` / `github`), presets declared by config.

Design adapted from Thysrael/Horizon (MIT) — src/scrapers/*: 每个数据源族一个薄 scraper,
具体源用配置声明,不按站点写代码。这里进一步收敛为 3 个引擎:

| engine | 覆盖 | preset |
| --- | --- | --- |
| `rss` | 标准 Feed | `feed`(RSS/Atom/JSON Feed,含 RSSHub/RSS-Bridge 生成的 URL) |
| `news` | 资讯 / 新闻 / 论文 | `arxiv` / `google_news` / `bing_news` / `hackernews` |
| `github` | 代码与模型资源 | `trending` / `repo` / `skill` / `model` |

信源表沿用 `channel` 字段存「渠道键」(见 `CHANNEL_ROUTES`),因此新增来源零迁移;
也可以在 `Source.config` 里写 `{"engine": "...", "preset": "..."}` 覆盖。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.collectors.arxiv import ArxivCollector
from app.collectors.base import BaseCollector, CollectContext, RawItem
from app.collectors.bing_news import BingNewsCollector
from app.collectors.github_search import GitHubRepoSearchCollector, HuggingFaceModelCollector
from app.collectors.github_trending import GitHubTrendingCollector
from app.collectors.google_news import GoogleNewsCollector
from app.collectors.hackernews import HackerNewsCollector
from app.collectors.hf_papers import HFDailyPapersCollector
from app.collectors.rss import RSSCollector

if TYPE_CHECKING:
    from app.models import Source

ENGINE_RSS = "rss"
ENGINE_NEWS = "news"
ENGINE_GITHUB = "github"
ENGINES: tuple[str, ...] = (ENGINE_RSS, ENGINE_NEWS, ENGINE_GITHUB)

DEFAULT_PRESET: dict[str, str] = {
    ENGINE_RSS: "feed",
    ENGINE_NEWS: "google_news",
    ENGINE_GITHUB: "trending",
}

PRESETS: dict[str, tuple[str, ...]] = {
    ENGINE_RSS: ("feed",),
    ENGINE_NEWS: ("arxiv", "google_news", "bing_news", "hackernews", "hf_papers"),
    ENGINE_GITHUB: ("trending", "repo", "skill", "model"),
}

# 渠道键 → (engine, preset)。信源以 `channel` 存左侧键。
CHANNEL_ROUTES: dict[str, tuple[str, str]] = {
    "rss": (ENGINE_RSS, "feed"),
    "feed": (ENGINE_RSS, "feed"),
    "arxiv": (ENGINE_NEWS, "arxiv"),
    "google_news": (ENGINE_NEWS, "google_news"),
    "bing_news": (ENGINE_NEWS, "bing_news"),
    "hackernews": (ENGINE_NEWS, "hackernews"),
    "hn": (ENGINE_NEWS, "hackernews"),
    "hf_papers": (ENGINE_NEWS, "hf_papers"),
    "github": (ENGINE_GITHUB, "trending"),
    "github_trending": (ENGINE_GITHUB, "trending"),
    "trending": (ENGINE_GITHUB, "trending"),
    "repo": (ENGINE_GITHUB, "repo"),
    "skill": (ENGINE_GITHUB, "skill"),
    "model": (ENGINE_GITHUB, "model"),
}

# 采集对象类型:决定打分口径与日报分节
OBJECT_TYPES: tuple[str, ...] = ("paper", "news", "community", "repo", "skill", "model", "other")

_PRESET_OBJECT_TYPE: dict[tuple[str, str], str] = {
    (ENGINE_NEWS, "arxiv"): "paper",
    (ENGINE_NEWS, "google_news"): "news",
    (ENGINE_NEWS, "bing_news"): "news",
    (ENGINE_NEWS, "hackernews"): "community",
    (ENGINE_NEWS, "hf_papers"): "paper",
    (ENGINE_GITHUB, "trending"): "repo",
    (ENGINE_GITHUB, "repo"): "repo",
    (ENGINE_GITHUB, "skill"): "skill",
    (ENGINE_GITHUB, "model"): "model",
}

_REGISTRY: dict[tuple[str, str], BaseCollector] = {
    (ENGINE_RSS, "feed"): RSSCollector(),
    (ENGINE_NEWS, "arxiv"): ArxivCollector(),
    (ENGINE_NEWS, "google_news"): GoogleNewsCollector(),
    (ENGINE_NEWS, "bing_news"): BingNewsCollector(),
    (ENGINE_NEWS, "hackernews"): HackerNewsCollector(),
    (ENGINE_NEWS, "hf_papers"): HFDailyPapersCollector(),
    (ENGINE_GITHUB, "trending"): GitHubTrendingCollector(),
    (ENGINE_GITHUB, "repo"): GitHubRepoSearchCollector("repo"),
    (ENGINE_GITHUB, "skill"): GitHubRepoSearchCollector("skill"),
    (ENGINE_GITHUB, "model"): HuggingFaceModelCollector(),
}


def _config_of(source: Source) -> dict:
    config = getattr(source, "config", None)
    return config if isinstance(config, dict) else {}


def route_of(source: Source) -> tuple[str, str] | None:
    """返回信源的 (engine, preset);未知渠道返回 None。"""
    config = _config_of(source)
    engine = str(config.get("engine") or "").strip().lower()
    preset = str(config.get("preset") or "").strip().lower()
    if engine in ENGINES:
        return engine, preset or DEFAULT_PRESET[engine]
    return CHANNEL_ROUTES.get(str(getattr(source, "channel", "") or "").strip().lower())


def collector_for(source: Source) -> BaseCollector | None:
    route = route_of(source)
    return _REGISTRY.get(route) if route else None


def object_type_of(source: Source) -> str:
    """采集对象类型:显式 config.object_type 优先,否则按 (engine, preset) 推断。"""
    config = _config_of(source)
    explicit = str(config.get("object_type") or "").strip().lower()
    if explicit in OBJECT_TYPES:
        return explicit
    route = route_of(source)
    return _PRESET_OBJECT_TYPE.get(route, "other") if route else "other"


def engine_of(source: Source) -> str:
    route = route_of(source)
    return route[0] if route else ""


def get_collector(channel: str) -> BaseCollector | None:
    """按渠道键取采集器(兼容旧调用点)。"""
    route = CHANNEL_ROUTES.get(str(channel or "").strip().lower())
    return _REGISTRY.get(route) if route else None


__all__ = [
    "CHANNEL_ROUTES",
    "DEFAULT_PRESET",
    "ENGINE_GITHUB",
    "ENGINE_NEWS",
    "ENGINE_RSS",
    "ENGINES",
    "OBJECT_TYPES",
    "PRESETS",
    "BaseCollector",
    "CollectContext",
    "RawItem",
    "collector_for",
    "engine_of",
    "get_collector",
    "object_type_of",
    "route_of",
]
