"""信源发现器:从 GitHub 仓库 / OPML / 页面发掘候选 Feed 并探测可达性。

把 2026-10-08 方案 A 的脚本流程产品化(收集候选 → 去重 → 探测 → 交给 UI 批量导入):
- GitHub 仓库:走 GitHub API 找 `*.opml` / feeds.json / sources.json,再扫 README 中的 feed 链接;
- OPML / Feed 文件:直接解析;
- 普通网页:抽 `<link rel=alternate>` 与带 feed 特征的链接。
探测判定与「信源池-测试」一致:HTTP 200 且能解析出 ≥1 条条目。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import feedparser

from app.collectors.base import describe_error, get_with_retries, make_client
from app.collectors.github_search import github_token

GITHUB_REPO_RE = re.compile(
    r"^https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?(?:$|[?#])"
)
URL_RE = re.compile(r"https?://[^\s\"'<>)\]}]+")
FEED_HINT = re.compile(
    r"(\.rss\b|\.atom\b|/rss(?:/|$|[?#])|/feed(?:/|$|[?#])|/atom(?:/|$|[?#])"
    r"|rss\.xml|feed\.xml|index\.xml|/feeds?/|\?format=rss)",
    re.I,
)
CANDIDATE_FILE = re.compile(r"(\.opml$|feeds?\.(json|ya?ml)$|sources?\.(json|ya?ml)$)", re.I)
MAX_CANDIDATES = 400


@dataclass
class FeedCandidate:
    name: str
    url: str


@dataclass
class ProbeResult:
    ok: bool
    entries: int = 0
    latest: str | None = None
    title: str | None = None
    error: str | None = None


def normalize_url(url: str) -> str:
    text = (url or "").strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    return re.sub(r"/+$", "", text)


def dedupe_candidates(
    candidates: list[FeedCandidate], limit: int = MAX_CANDIDATES
) -> list[FeedCandidate]:
    seen: set[str] = set()
    out: list[FeedCandidate] = []
    for candidate in candidates:
        url = (candidate.url or "").strip()
        if not url.startswith("http"):
            continue
        key = normalize_url(url)
        if key in seen:
            continue
        seen.add(key)
        name = (candidate.name or "").strip() or url
        out.append(FeedCandidate(name=name[:150], url=url))
        if len(out) >= limit:
            break
    return out


def parse_opml(text: str) -> list[FeedCandidate]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out: list[FeedCandidate] = []
    for outline in root.iter("outline"):
        url = (outline.get("xmlUrl") or "").strip()
        if not url:
            continue
        title = (outline.get("title") or outline.get("text") or "").strip()
        out.append(FeedCandidate(name=title or url, url=url))
    return out


def urls_from_text(text: str) -> list[FeedCandidate]:
    return [
        FeedCandidate(name=url, url=url)
        for url in URL_RE.findall(text or "")
        if FEED_HINT.search(url)
    ]


def extract_from_html(text: str, base_url: str) -> list[FeedCandidate]:
    out: list[FeedCandidate] = []
    for match in re.finditer(r"<link\b[^>]*>", text or "", re.I):
        tag = match.group(0)
        if not re.search(r'type=["\']application/(?:rss|atom)\+xml', tag, re.I):
            continue
        href = re.search(r'href=["\']([^"\']+)', tag, re.I)
        if href:
            resolved = urljoin(base_url, href.group(1))
            out.append(FeedCandidate(name=resolved, url=resolved))
    anchor_re = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
    for match in anchor_re.finditer(text or ""):
        href = match.group(1)
        if not FEED_HINT.search(href):
            continue
        label = re.sub(r"<[^>]+>", "", match.group(2)).strip() or href
        out.append(FeedCandidate(name=label[:150], url=urljoin(base_url, href)))
    return out


def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    token = github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _github_candidates(client: Any, owner: str, repo: str) -> list[FeedCandidate]:
    api = f"https://api.github.com/repos/{owner}/{repo}"
    headers = _github_headers()
    meta = await get_with_retries(client, api, headers=headers)
    branch = str(meta.json().get("default_branch") or "main")
    tree = await get_with_retries(client, f"{api}/git/trees/{branch}?recursive=1", headers=headers)
    paths = [
        str(node.get("path"))
        for node in tree.json().get("tree", [])
        if node.get("type") == "blob" and node.get("path")
    ]
    out: list[FeedCandidate] = []
    for path in [p for p in paths if CANDIDATE_FILE.search(p)][:6]:
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
        try:
            raw = await get_with_retries(client, raw_url)
        except Exception:  # noqa: BLE001 - 单个文件失败不影响整体
            continue
        text = raw.text
        if path.lower().endswith(".opml"):
            out.extend(parse_opml(text))
        else:
            out.extend(urls_from_text(text))
    for path in [p for p in paths if p.lower().startswith("readme")][:1]:
        try:
            raw = await get_with_retries(
                client, f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
            )
        except Exception:  # noqa: BLE001
            continue
        out.extend(extract_from_html(raw.text, f"https://github.com/{owner}/{repo}"))
        out.extend(urls_from_text(raw.text))
    return out


async def collect_candidates(
    url: str, *, limit: int = 120, timeout: float = 20.0
) -> list[FeedCandidate]:
    """从输入 URL 收集候选 Feed(不探测)。"""
    async with make_client(timeout) as client:
        repo_match = GITHUB_REPO_RE.match(url.strip())
        if repo_match:
            candidates = await _github_candidates(client, repo_match.group(1), repo_match.group(2))
            return dedupe_candidates(candidates, limit)
        response = await get_with_retries(client, url.strip())
        text = response.text
        head = text[:3000].lower()
        if "<opml" in head:
            candidates = parse_opml(text)
        elif "<rss" in head or "<feed" in head or "<rdf" in head:
            candidates = [FeedCandidate(name=url, url=url)]
        else:
            candidates = extract_from_html(text, str(response.url))
            if not candidates:
                candidates = urls_from_text(text)
        return dedupe_candidates(candidates, limit)


async def probe_candidate(candidate: FeedCandidate, *, timeout: float = 15.0) -> ProbeResult:
    try:
        async with make_client(timeout) as client:
            response = await get_with_retries(
                client, candidate.url, attempts=2, backoff_seconds=0.5
            )
        parsed = feedparser.parse(response.content)
        if not parsed.entries:
            return ProbeResult(ok=False, error="无可解析条目")
        latest = 0.0
        for entry in parsed.entries[:8]:
            stamp = entry.get("published_parsed") or entry.get("updated_parsed")
            if stamp:
                latest = max(latest, datetime(*stamp[:6], tzinfo=UTC).timestamp())
        return ProbeResult(
            ok=True,
            entries=len(parsed.entries),
            latest=datetime.fromtimestamp(latest, UTC).isoformat() if latest else None,
            title=(parsed.feed.get("title") or "").strip()[:150] or None,
        )
    except Exception as exc:  # noqa: BLE001 - 探测失败以结果返回
        return ProbeResult(ok=False, error=describe_error(exc)[:160])


async def probe_candidates(
    candidates: list[FeedCandidate], *, concurrency: int = 12, timeout: float = 15.0
) -> list[tuple[FeedCandidate, ProbeResult]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run(candidate: FeedCandidate) -> tuple[FeedCandidate, ProbeResult]:
        async with semaphore:
            return candidate, await probe_candidate(candidate, timeout=timeout)

    return list(await asyncio.gather(*(run(candidate) for candidate in candidates)))
