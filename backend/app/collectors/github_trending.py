"""GitHub Trending collector (HTML scraping, adapted from news-agent, MIT).

`since=daily` 榜按「过去 24 小时新增 star」排序,是「今日最热」的权威口径;
`weekly` / `monthly` 通过 `since` 切换,解析结果统一放进 `stars_today`(语义为所选周期内新增 star)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from app.collectors.base import (
    BaseCollector,
    CollectContext,
    RawItem,
    get_with_retries,
    make_client,
)

if TYPE_CHECKING:
    from app.models import Source

TRENDING_URL = "https://github.com/trending"
_NUM_RE = re.compile(r"[\d,]+")


def _parse_int(text: str) -> int:
    match = _NUM_RE.search(text or "")
    return int(match.group(0).replace(",", "")) if match else 0


def parse_trending_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    repos: list[dict] = []
    seen: set[str] = set()
    for article in soup.select("article.Box-row"):
        heading = article.find("h2")
        anchor = heading.find("a") if heading else None
        if not anchor or not anchor.get("href"):
            continue
        full_name = str(anchor["href"]).strip().lstrip("/")
        url = f"https://github.com/{full_name}"
        if not full_name or url in seen:
            continue
        seen.add(url)
        desc_tag = article.find("p")
        language_tag = article.find("span", attrs={"itemprop": "programmingLanguage"})
        stars_total = 0
        star_link = article.find("a", href=re.compile(r"/stargazers$"))
        if star_link:
            stars_total = _parse_int(star_link.get_text(strip=True))
        stars_today = 0
        for span in article.find_all("span"):
            text = span.get_text(strip=True)
            if "stars today" in text or "stars this week" in text or "stars this month" in text:
                stars_today = _parse_int(text)
                break
        repos.append(
            {
                "url": url,
                "full_name": full_name,
                "description": desc_tag.get_text(strip=True) if desc_tag else "",
                "language": language_tag.get_text(strip=True) if language_tag else "",
                "stars_total": stars_total,
                "stars_today": stars_today,
            }
        )
    return repos


async def fetch_trending_repos(
    *,
    since: str = "daily",
    language: str | None = None,
    timeout: float = 20.0,
) -> list[dict]:
    """实时抓取 Trending 榜;采集器与日报 GitHub 板块共用同一实现。"""
    params: dict[str, str] = {"since": since}
    if language:
        params["language"] = language
    async with make_client(timeout) as client:
        response = await get_with_retries(client, TRENDING_URL, params=params)
    return parse_trending_html(response.text)


class GitHubTrendingCollector(BaseCollector):
    channel = "github"

    async def collect(self, source: Source, ctx: CollectContext) -> list[RawItem]:
        config = source.config or {}
        since = str(config.get("since") or "daily")
        language = str(config.get("language") or "").strip() or None
        repos = await fetch_trending_repos(since=since, language=language, timeout=ctx.timeout)
        items: list[RawItem] = []
        for repo in repos[: ctx.max_items]:
            description = repo["description"] or ""
            items.append(
                RawItem(
                    url=repo["url"],
                    title=repo["full_name"],
                    raw_text=description or None,
                    content_type_hint="tech",
                    metrics={
                        "stars_total": repo["stars_total"],
                        "stars_today": repo["stars_today"],
                    },
                    extra={"language": repo["language"], "trending_since": since},
                )
            )
        return items
