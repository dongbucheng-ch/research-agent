"""Fetch pipeline: collect -> normalize -> dedup -> enrich -> score -> store."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import (
    ENGINE_GITHUB,
    CollectContext,
    RawItem,
    collector_for,
    engine_of,
    object_type_of,
    route_of,
)
from app.collectors.base import describe_error
from app.core.config import get_settings
from app.models import (
    Item,
    ItemContent,
    ItemScore,
    RawDocument,
    Source,
)
from app.pipeline.enrich import EnrichInput, EnrichResult, enrich_many, fallback_enrich
from app.pipeline.scoring import (
    combine_scores,
    excluded_by_keywords,
    freshness_score,
    keyword_relevance,
    metric_heat_score,
)
from app.pipeline.text import (
    detect_lang,
    hamming_hex,
    normalize_url,
    sha256_hex,
    simhash64,
    title_fingerprint,
    truncate,
)
from app.services.app_settings import bound_int, get_general_config, get_llm_config
from app.services.keyword_expand import expand_keywords
from app.services.keyword_translate import (
    alias_keyword_entries,
    needs_translation,
    translate_keywords,
)
from app.services.llm import LLMClient, usage_delta
from app.services.stage_tracker import StageTracker

logger = logging.getLogger(__name__)

NEAR_DUP_HAMMING = 3
NEAR_DUP_WINDOW_HOURS = 48
NEAR_DUP_MAX_CANDIDATES = 800

# 采集流水线的固定阶段(顺序即前端展示顺序)。
FETCH_STAGE_KEYS: tuple[str, ...] = (
    "setup",
    "sources",
    "collect",
    "normalize",
    "dedup",
    "enrich",
    "score",
    "store",
    "expand",
    "backfill",
)

# 单轮采集新入库低于该值时触发一次辐射补量(可被 backfill=off 关闭)。
MIN_EXPECTED_NEW = 5


def collect_meta(spec: CollectionSpec) -> dict[str, Any]:
    """记录「这条素材由哪次采集(研究方向 / 关键词)收进来」,供素材池打标。

    - 主轮:collect_keywords = 本轮用户输入的关键词;
    - 补量轮:保留原始研究方向与关键词,并记录实际使用的辐射词(origin=backfill)。
    """
    origin = str(spec.extra.get("origin") or "main")
    expanded_from = [str(word) for word in (spec.extra.get("expanded_from") or [])]
    keywords = expanded_from or spec.include_words or spec.github_include_words
    meta: dict[str, Any] = {
        "collect_name": spec.extra.get("origin_name") or spec.name,
        "collect_keywords": keywords,
        "origin": origin,
    }
    if origin == "backfill":
        meta["expanded_keywords"] = spec.include_words
        meta["collect_name"] = str(meta["collect_name"]).replace("·补量", "")
    return meta


LogFn = Callable[[str], None]


@dataclass(slots=True)
class CollectionSpec:
    """One collection run: keywords typed by the operator."""

    name: str
    keywords: list[dict[str, Any]]
    source_ids: list[int]
    lookback_hours: int = 24
    min_score: int = 75
    scopes: tuple[str, ...] = ("info", "github")
    github_keywords: list[str] = field(default_factory=list)
    github_mode: str = "trending_fallback"
    backfill: str = "auto"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def include_words(self) -> list[str]:
        return [
            str(k["word"])
            for k in self.keywords
            if k.get("kind") == "include" and k.get("channel") != "github"
        ]

    @property
    def github_include_words(self) -> list[str]:
        """GitHub 通道使用的检索词;未配置专属词时沿用主关键词。"""
        explicit = [
            entry
            for entry in self.keywords
            if entry.get("kind") == "include" and entry.get("channel") == "github"
        ]
        if explicit:
            return [str(k["word"]) for k in explicit]
        return self.include_words


def _clean_words(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    words: list[str] = []
    for item in raw:
        word = str(item or "").strip()
        if word and word not in words:
            words.append(word)
    return words


def spec_from_params(params: dict[str, Any]) -> CollectionSpec:
    keywords = [
        {"word": word, "kind": "include", "weight": 1.0}
        for word in _clean_words(params.get("keywords"))
    ] + [
        {"word": word, "kind": "exclude", "weight": 1.0}
        for word in _clean_words(params.get("exclude_keywords"))
    ]
    github_words = _clean_words(params.get("github_keywords"))
    for word in github_words:
        keywords.append({"word": word, "kind": "include", "weight": 1.0, "channel": "github"})
    requested = params.get("scopes") or ["info", "github"]
    scopes = tuple(scope for scope in ("info", "github") if scope in requested) or (
        "info",
        "github",
    )
    weights = params.get("score_weights")
    return CollectionSpec(
        name=str(params.get("name") or "").strip() or "临时采集",
        keywords=keywords,
        source_ids=[int(i) for i in (params.get("source_ids") or [])],
        lookback_hours=bound_int(params.get("lookback_hours"), default=24, low=1, high=48),
        min_score=bound_int(params.get("min_score"), default=75, low=75, high=100),
        scopes=scopes,
        github_keywords=github_words,
        github_mode=str(params.get("github_mode") or "trending_fallback"),
        backfill=str(params.get("backfill") or "auto"),
        extra={"score_weights": weights} if isinstance(weights, dict) and weights else {},
    )


@dataclass
class FetchStats:
    runs: int = 0
    sources: int = 0
    fetched: int = 0
    new_items: int = 0
    duplicates: int = 0
    filtered: int = 0
    failed_sources: int = 0
    llm_errors: int = 0
    llm_degraded: int = 0
    low_score: int = 0
    llm_usage: dict[str, Any] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "runs": self.runs,
            "sources": self.sources,
            "fetched": self.fetched,
            "new_items": self.new_items,
            "duplicates": self.duplicates,
            "filtered": self.filtered,
            "failed_sources": self.failed_sources,
            "llm_errors": self.llm_errors,
            "llm_degraded": self.llm_degraded,
            "llm_usage": dict(self.llm_usage),
            "low_score": self.low_score,
            "items": self.items,
        }


MAX_REPORT_ITEMS = 200

_TIER_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3}


def enrich_rank_key(
    tier: str, hits: int, published_at: datetime | None
) -> tuple[float, int, float]:
    """富化排队键:关键词命中多优先 → 高等级信源 → 更近发布。"""
    stamp = published_at.timestamp() if isinstance(published_at, datetime) else 0.0
    return (-float(hits or 0), _TIER_ORDER.get(str(tier or "").upper(), 4), -stamp)


def split_enrich_indexes(
    rank_keys: list[tuple[float, int, float]], limit: int
) -> tuple[list[int], list[int]]:
    """按上限拆分「走 LLM 富化」与「零成本降级」的序号;limit<=0 表示不限制。"""
    order = list(range(len(rank_keys)))
    if limit <= 0 or len(order) <= limit:
        return order, []
    order.sort(key=lambda index: rank_keys[index])
    return order[:limit], order[limit:]


async def run_fetch(
    session: AsyncSession,
    *,
    source_id: int | None = None,
    spec_params: dict[str, Any] | None = None,
    log: LogFn | None = None,
    tracker: StageTracker | None = None,
) -> dict[str, Any]:
    log = log or (lambda _msg: None)
    tracker = tracker or StageTracker()
    tracker.plan(FETCH_STAGE_KEYS)
    stats = FetchStats()
    general = await get_general_config(session)
    llm_config = await get_llm_config(session)
    llm_client = LLMClient.from_config(llm_config)
    if llm_client is None:
        log("[配置] LLM 未配置,使用降级模式(不翻译/不 LLM 摘要)")
    llm_sem = asyncio.Semaphore(int(llm_config.get("max_concurrency") or 3))

    if not spec_params:
        log("[系统] 未提供采集参数(关键词),已取消采集")
        tracker.skip_rest("未提供采集参数")
        return _finish_result(tracker, stats.as_dict())
    spec = spec_from_params(spec_params)
    if not spec.include_words:
        log("[系统] 未提供包含关键词,已取消采集")
        tracker.skip_rest("未提供包含关键词")
        return _finish_result(tracker, stats.as_dict())
    tracker.start("setup", f"配置「{spec.name}」· 关键词 {len(spec.include_words)} 个")
    usage_mark = llm_client.usage.as_dict() if llm_client else {}
    await _expand_keywords_with_translation(spec, llm_client, log)
    setup_tokens = (
        usage_delta(usage_mark, llm_client.usage.as_dict())["total_tokens"] if llm_client else 0
    )
    translations = len(spec.extra.get("keyword_translations") or {})
    tracker.finish(
        "setup",
        f"关键词 {len(spec.include_words)} 个(翻译 {translations} 组)",
        keywords=len(spec.include_words),
        translations=translations,
        tokens=setup_tokens,
    )
    specs: list[CollectionSpec] = [spec]

    collect_cache: dict[tuple[int, tuple[str, ...] | None], list[RawItem]] = {}

    for spec in specs:
        stats.runs += 1
        log(f"[系统] 开始采集「{spec.name}」")
        await _process_spec(
            session,
            spec,
            source_id=source_id,
            llm_client=llm_client,
            llm_sem=llm_sem,
            general=general,
            stats=stats,
            log=log,
            collect_cache=collect_cache,
            tracker=tracker,
        )

    if llm_client is not None:
        stats.llm_usage = llm_client.usage.as_dict()
        log(
            f"[Token] LLM 调用 {stats.llm_usage['calls']} 次, 输入 "
            f"{stats.llm_usage['prompt_tokens']} / 输出 "
            f"{stats.llm_usage['completion_tokens']} = 共 "
            f"{stats.llm_usage['total_tokens']} tokens"
        )
    log(
        "[完成] " + f"新入库 {stats.new_items} 条, 去重 {stats.duplicates} 条, "
        f"过滤 {stats.filtered} 条, 低于门槛 {stats.low_score} 条, "
        f"失败源 {stats.failed_sources} 个, 降级 {stats.llm_degraded} 条"
    )
    if stats.new_items == 0 and stats.low_score > 0:
        log("[提示] 本次有条目因低于入库门槛被跳过,可在采集工作台调整「入库门槛」后重采")
    backfill_info = await _maybe_backfill(
        session,
        spec,
        stats=stats,
        log=log,
        tracker=tracker,
        llm_client=llm_client,
        llm_sem=llm_sem,
        general=general,
        source_id=source_id,
        collect_cache=collect_cache,
    )
    tracker.skip_rest()
    payload = _finish_result(tracker, stats.as_dict(), spec=spec)
    if backfill_info is not None:
        payload["backfill"] = backfill_info
    if stats.new_items < MIN_EXPECTED_NEW:
        payload["shortfall"] = {"expected": MIN_EXPECTED_NEW, "actual": stats.new_items}
        log(
            f"[提示] 本轮新入库 {stats.new_items} 条,低于期望 {MIN_EXPECTED_NEW} 条;"
            "可放宽关键词、延长回看窗口或降低入库门槛后重采"
        )
    return payload


async def _maybe_backfill(
    session: AsyncSession,
    spec: CollectionSpec,
    *,
    stats: FetchStats,
    log: LogFn,
    tracker: StageTracker,
    llm_client: LLMClient | None,
    llm_sem: asyncio.Semaphore,
    general: dict[str, Any],
    source_id: int | None,
    collect_cache: dict[tuple[int, tuple[str, ...] | None], list[RawItem]],
) -> dict[str, Any] | None:
    """素材不足时的补量:LLM 生成辐射词后补采**一轮**(不递归)。"""
    if spec.backfill != "auto":
        tracker.skip("expand", "补量已关闭")
        tracker.skip("backfill", "补量已关闭")
        return None
    if stats.new_items >= MIN_EXPECTED_NEW:
        tracker.skip("expand", f"新入库 {stats.new_items} 条,素材充足")
        tracker.skip("backfill", "无需补量")
        return None
    if stats.sources and stats.failed_sources >= stats.sources:
        tracker.skip("expand", "信源全部抓取失败,跳过补量")
        tracker.skip("backfill", "无可用信源")
        return {"skipped": "all_sources_failed", "new_items": 0}
    if llm_client is None:
        tracker.skip("expand", "LLM 未配置,无法生成辐射词")
        tracker.skip("backfill", "跳过补量")
        return {"skipped": "llm_unavailable", "new_items": 0}

    tracker.start("expand", f"新入库 {stats.new_items} 条 < {MIN_EXPECTED_NEW},生成辐射词")
    seed_words = list(dict.fromkeys(spec.include_words + list(spec.github_keywords)))
    usage_mark = llm_client.usage.as_dict()
    words = await expand_keywords(llm_client, topic=spec.name, keywords=seed_words, log=log)
    expand_tokens = usage_delta(usage_mark, llm_client.usage.as_dict())["total_tokens"]
    if not words:
        tracker.finish("expand", "未生成可用辐射词")
        tracker.skip("backfill", "无辐射词")
        return {"skipped": "no_expanded_keywords", "new_items": 0}
    tracker.finish(
        "expand",
        f"辐射词 {len(words)} 个: {' / '.join(words)}",
        count=len(words),
        tokens=expand_tokens,
    )
    tracker.start("backfill", f"补采一轮: {' / '.join(words)}")

    exclude_entries = [entry for entry in spec.keywords if entry.get("kind") == "exclude"]
    expanded = CollectionSpec(
        name=f"{spec.name}·补量",
        keywords=[
            {"word": word, "kind": "include", "weight": 0.55, "group": word, "origin": "expanded"}
            for word in words
        ]
        + exclude_entries,
        source_ids=list(spec.source_ids),
        lookback_hours=spec.lookback_hours,
        min_score=spec.min_score,
        scopes=spec.scopes,
        github_keywords=[],
        github_mode=spec.github_mode,
        backfill="off",
        extra={
            "score_weights": spec.extra.get("score_weights"),
            "origin": "backfill",
            "origin_name": spec.extra.get("origin_name") or spec.name,
            "expanded_from": spec.include_words,
        },
    )
    sub_stats = FetchStats()
    sub_tracker = StageTracker(
        plan=("sources", "collect", "normalize", "dedup", "enrich", "score", "store")
    )
    await _process_spec(
        session,
        expanded,
        source_id=source_id,
        llm_client=llm_client,
        llm_sem=llm_sem,
        general=general,
        stats=sub_stats,
        log=log,
        collect_cache=collect_cache,
        tracker=sub_tracker,
    )
    for row in sub_tracker.sources_detail:
        tracker.add_source({**row, "round": "backfill"})
    stats.runs += 1
    stats.sources += sub_stats.sources
    stats.fetched += sub_stats.fetched
    stats.new_items += sub_stats.new_items
    stats.duplicates += sub_stats.duplicates
    stats.filtered += sub_stats.filtered
    stats.failed_sources += sub_stats.failed_sources
    stats.llm_errors += sub_stats.llm_errors
    stats.llm_degraded += sub_stats.llm_degraded
    stats.low_score += sub_stats.low_score
    room = max(0, MAX_REPORT_ITEMS - len(stats.items))
    stats.items.extend(sub_stats.items[:room])
    tracker.finish("backfill", f"补采新增 {sub_stats.new_items} 条(抓取 {sub_stats.fetched} 条)")
    return {
        "keywords": words,
        "fetched": sub_stats.fetched,
        "new_items": sub_stats.new_items,
        "stages": sub_tracker.stages(),
    }


def _finish_result(
    tracker: StageTracker, payload: dict[str, Any], spec: CollectionSpec | None = None
) -> dict[str, Any]:
    tracker.attach(payload)
    if spec is not None:
        payload["spec"] = {
            "name": spec.name,
            "keywords": spec.include_words,
            "exclude_keywords": [
                str(k["word"]) for k in spec.keywords if k.get("kind") == "exclude"
            ],
            "source_ids": list(spec.source_ids),
            "lookback_hours": spec.lookback_hours,
            "min_score": spec.min_score,
            "scopes": list(spec.scopes),
            "github_keywords": list(spec.github_keywords),
            "github_mode": spec.github_mode,
            "backfill": spec.backfill,
            "keyword_translations": dict(spec.extra.get("keyword_translations") or {}),
        }
    return payload


async def _expand_keywords_with_translation(
    spec: CollectionSpec, llm_client: LLMClient | None, log: LogFn
) -> None:
    """中文关键词先 LLM 翻成英文检索词,再和原词一起参与采集与打分。

    英文源(arXiv / GitHub / Hacker News)对中文词几乎零命中,翻译后同一批关键词
    才能在这些源上生效;译名与中文词同组,不额外稀释相关度(见 `pipeline.scoring`)。
    """
    words = spec.include_words
    github_words = spec.github_keywords
    if not needs_translation(words) and not needs_translation(github_words):
        return
    if llm_client is None:
        log("[配置] LLM 未配置,中文关键词未翻译(英文源可能命中不到)")
        return
    if needs_translation(words):
        mapping = await translate_keywords(llm_client, words, log=log)
        if mapping:
            spec.keywords.extend(alias_keyword_entries(mapping))
            spec.extra["keyword_translations"] = mapping
    if needs_translation(github_words):
        github_mapping = await translate_keywords(llm_client, github_words, log=log)
        if github_mapping:
            spec.keywords.extend(alias_keyword_entries(github_mapping, channel="github"))
            spec.extra["github_keyword_translations"] = github_mapping


def _all_enabled_sources():
    return select(Source).where(Source.enabled.is_(True)).order_by(Source.tier, Source.id)


async def _load_sources(
    session: AsyncSession, spec: CollectionSpec, source_id: int | None
) -> list[Source]:
    if source_id is not None:
        source = await session.get(Source, source_id)
        return [source] if source is not None and source.enabled else []
    if spec.source_ids:
        rows = list(
            await session.scalars(
                select(Source)
                .where(Source.id.in_(spec.source_ids), Source.enabled.is_(True))
                .order_by(Source.tier, Source.id)
            )
        )
        rows = [row for row in rows if _in_scope(row, spec.scopes)]
        if rows:
            return rows
    rows = list(await session.scalars(_all_enabled_sources()))
    return [row for row in rows if _in_scope(row, spec.scopes)]


def _in_scope(source: Source, scopes: tuple[str, ...]) -> bool:
    """info = rss/news 引擎(资讯·论文);github = github 引擎(代码与模型资源)。"""
    if engine_of(source) == ENGINE_GITHUB:
        return "github" in scopes
    return "info" in scopes


def _keywords_for(spec: CollectionSpec, source: Source) -> list[dict[str, Any]]:
    """GitHub 源使用专属关键词(若配置),其余源排除 GitHub 专属词。"""
    if engine_of(source) == ENGINE_GITHUB and spec.github_keywords:
        return [
            entry
            for entry in spec.keywords
            if entry.get("channel") == "github" or entry.get("kind") == "exclude"
        ]
    return [entry for entry in spec.keywords if entry.get("channel") != "github"]


def _is_hot_channel(spec: CollectionSpec, source: Source) -> bool:
    """热榜通道:GitHub Trending 在兜底模式下豁免关键词命中过滤。"""
    if engine_of(source) != ENGINE_GITHUB or spec.github_mode != "trending_fallback":
        return False
    route = route_of(source)
    return bool(route) and route[1] == "trending"


async def _process_spec(
    session: AsyncSession,
    spec: CollectionSpec,
    *,
    source_id: int | None,
    llm_client: LLMClient | None,
    llm_sem: asyncio.Semaphore,
    general: dict[str, Any],
    stats: FetchStats,
    log: LogFn,
    collect_cache: dict[tuple[int, tuple[str, ...] | None], list[RawItem]],
    tracker: StageTracker,
) -> None:
    keywords = spec.keywords
    include_words = spec.include_words
    github_words = spec.github_include_words

    def search_words_for(src: Source) -> list[str]:
        return github_words if engine_of(src) == ENGINE_GITHUB else include_words

    if not include_words:
        log(f"[系统] 采集「{spec.name}」未配置包含关键词,已跳过")
        tracker.skip_rest("未配置包含关键词")
        return
    tracker.start("sources", "加载启用信源")
    sources = await _load_sources(session, spec, source_id)
    if not sources:
        log(f"[系统] 采集「{spec.name}」没有可用信源")
        tracker.skip("sources", "没有可用信源")
        tracker.skip_rest("没有可用信源")
        return
    stats.sources += len(sources)
    tracker.finish("sources", f"启用 {len(sources)} 个信源", count=len(sources))
    tracker.set_counters(sources=len(sources), fetched=0, duplicates=0, filtered=0)

    timeout = float(get_settings().fetch_timeout_seconds)
    max_concurrency = int(general.get("fetch_max_concurrency") or 8)
    fetch_sem = asyncio.Semaphore(max_concurrency)

    async def collect_one(src: Source) -> tuple[Source, list[RawItem], str | None, float]:
        started = time.monotonic()
        words = search_words_for(src)
        cache_key = (
            (src.id, tuple(sorted(words))) if src.collector_kind == "search" else (src.id, None)
        )
        cached = collect_cache.get(cache_key)
        if cached is not None:
            return src, cached, None, time.monotonic() - started
        collector = collector_for(src)
        if collector is None:
            return src, [], f"未知渠道 {src.channel}", time.monotonic() - started
        ctx = CollectContext(
            keywords=words,
            lookback_hours=int(spec.lookback_hours),
            timeout=timeout,
            max_items=50,
        )
        try:
            async with fetch_sem:
                items = await collector.collect(src, ctx)
            collect_cache[cache_key] = items
            return src, items, None, time.monotonic() - started
        except Exception as exc:  # noqa: BLE001 - record and continue
            return src, [], describe_error(exc), time.monotonic() - started

    tracker.start("collect", f"并发抓取 {len(sources)} 个信源")
    results = await asyncio.gather(*[collect_one(src) for src in sources])
    detail_by_source: dict[int, dict[str, Any]] = {}
    for src, items, error, seconds in results:
        route = route_of(src)
        row: dict[str, Any] = {
            "source_id": src.id,
            "name": src.name,
            "engine": engine_of(src),
            "preset": route[1] if route else "",
            "kind": src.collector_kind,
            "seconds": round(seconds, 2),
            "fetched": len(items),
            "filtered": 0,
            "duplicates": 0,
            "low_score": 0,
            "ingested": 0,
            "error": error,
        }
        detail_by_source[src.id] = tracker.add_source(row)
        if error is not None:
            _record_source_result(src, ok=False, error=error)
            stats.failed_sources += 1
            log(f"[采集] {src.name} 抓取失败: {truncate(error, 160)}")
        else:
            _record_source_result(src, ok=True)
            stats.fetched += len(items)
            log(f"[采集] {src.name}·{object_type_of(src)} 抓取 {len(items)} 条 ({seconds:.2f}s)")
    await session.commit()
    tracker.set_counters(fetched=stats.fetched, failed_sources=stats.failed_sources)
    tracker.finish(
        "collect",
        f"抓取 {stats.fetched} 条 · 失败 {stats.failed_sources} 个信源",
        fetched=stats.fetched,
        failed=stats.failed_sources,
    )

    # Normalize + cheap filters (exclude words and include-word hits).
    tracker.start("normalize", "URL 规范化 / 排除词 / 关键词粗筛")
    prepared: list[
        tuple[Source, RawItem, str, str, str, str, list[str], list[dict[str, Any]], bool]
    ] = []
    seen_hashes: set[str] = set()
    for src, items, error, _seconds in results:
        if error is not None:
            continue
        src_keywords = _keywords_for(spec, src)
        hot_channel = _is_hot_channel(spec, src)
        hot_filtered = 0
        for raw in items:
            canonical = normalize_url(raw.url)
            if not canonical:
                continue
            url_hash = sha256_hex(canonical)
            if url_hash in seen_hashes:
                stats.duplicates += 1
                detail_by_source[src.id]["duplicates"] += 1
                continue
            seen_hashes.add(url_hash)
            text = f"{raw.title}\n{raw.raw_text or ''}"
            excluded = excluded_by_keywords(text, src_keywords)
            if excluded:
                stats.filtered += 1
                detail_by_source[src.id]["filtered"] += 1
                log(f"[标准化] 过滤(排除词「{excluded}」): {truncate(raw.title, 60)}")
                continue
            _score, hits = keyword_relevance(text, src_keywords)
            if not hits and not hot_channel:
                stats.filtered += 1
                detail_by_source[src.id]["filtered"] += 1
                continue
            if not hits and hot_channel:
                hot_filtered += 1
            fingerprint = title_fingerprint(raw.title)
            digest = simhash64(f"{raw.title} {raw.raw_text or ''}")
            prepared.append(
                (
                    src,
                    raw,
                    canonical,
                    url_hash,
                    fingerprint,
                    digest,
                    hits,
                    src_keywords,
                    hot_channel,
                )
            )
        if hot_filtered:
            log(f"[采集] {src.name} 热榜兜底: {hot_filtered} 条未命中关键词,按热榜通道放行")

    tracker.set_counters(filtered=stats.filtered, duplicates=stats.duplicates)
    if not prepared:
        log(f"[标准化] 「{spec.name}」本轮无新增候选")
        tracker.finish("normalize", "候选 0 条(粗筛后无命中)")
        tracker.skip_rest("本轮无新增候选")
        return
    tracker.finish(
        "normalize",
        f"候选 {len(prepared)} 条 · 过滤 {stats.filtered} 条",
        candidates=len(prepared),
        filtered=stats.filtered,
    )

    # Dedup against existing DB items.
    tracker.start("dedup", f"与素材库比对 {len(prepared)} 条")
    hashes = [row[3] for row in prepared]
    existing_by_hash: dict[str, int] = {}
    for chunk_start in range(0, len(hashes), 500):
        chunk = hashes[chunk_start : chunk_start + 500]
        rows = await session.execute(
            select(Item.canonical_url_hash, Item.id).where(Item.canonical_url_hash.in_(chunk))
        )
        existing_by_hash.update(dict(rows.all()))
    since = datetime.now(UTC) - timedelta(hours=NEAR_DUP_WINDOW_HOURS)
    recent_rows = (
        await session.execute(
            select(Item.id, Item.simhash, Item.title_fingerprint)
            .where(Item.first_seen_at >= since)
            .order_by(Item.id.desc())
            .limit(NEAR_DUP_MAX_CANDIDATES)
        )
    ).all()
    recent_fingerprints = {
        row.title_fingerprint: row.id for row in recent_rows if row.title_fingerprint
    }

    fresh_rows: list[
        tuple[Source, RawItem, str, str, str, str, list[str], list[dict[str, Any]], bool]
    ] = []
    for (
        src,
        raw,
        canonical,
        url_hash,
        fingerprint,
        digest,
        hits,
        src_keywords,
        hot_channel,
    ) in prepared:
        existing_id = existing_by_hash.get(url_hash)
        if existing_id is None:
            existing_id = recent_fingerprints.get(fingerprint)
        if existing_id is None:
            for row in recent_rows:
                if row.simhash and hamming_hex(digest, row.simhash) <= NEAR_DUP_HAMMING:
                    existing_id = row.id
                    break
        if existing_id is not None:
            stats.duplicates += 1
            detail_by_source[src.id]["duplicates"] += 1
            await _save_raw_document(session, src.id, raw, status="deduped", item_id=existing_id)
            continue
        fresh_rows.append(
            (src, raw, canonical, url_hash, fingerprint, digest, hits, src_keywords, hot_channel)
        )

    tracker.set_counters(duplicates=stats.duplicates)
    if not fresh_rows:
        await session.commit()
        log(f"[去重] 「{spec.name}」候选均已存在,去重 {len(prepared)} 条")
        tracker.finish("dedup", f"候选 {len(prepared)} 条全部已在库")
        tracker.skip_rest("候选均已存在")
        return
    tracker.finish(
        "dedup",
        f"新增 {len(fresh_rows)} 条 · 去重 {stats.duplicates} 条",
        fresh=len(fresh_rows),
        duplicates=stats.duplicates,
    )

    log(f"[去重] 候选 {len(prepared)} 条, 待富化 {len(fresh_rows)} 条")
    tracker.start(
        "enrich",
        f"LLM 富化 {len(fresh_rows)} 条" + ("(降级模式)" if llm_client is None else ""),
        total=len(fresh_rows),
    )

    now = datetime.now(UTC)
    enrich_done = 0
    enrich_inputs = [
        EnrichInput(
            title=raw.title,
            text=raw.raw_text,
            url=raw.url,
            channel=src.channel,
            content_type_hint=raw.content_type_hint,
        )
        for src, raw, *_ in fresh_rows
    ]

    def plain(item: EnrichInput) -> EnrichResult:
        return fallback_enrich(
            title=item.title,
            text=item.text,
            channel=item.channel,
            content_type_hint=item.content_type_hint,
        )

    # 候选/富化条数上限(默认 100,上限 500):按(关键词命中/信源等级/时效)
    # 预排序,只对 Top-N 走 LLM,其余零成本降级(仍参与打分入库,可在素材池按需再富化)。
    max_enrich = bound_int(general.get("enrich_max_items"), default=100, low=1, high=500)
    rank_keys = [
        enrich_rank_key(src.tier, len(_hits or []), raw.published_at)
        for src, raw, *_rest, _hits, _kw, _hot in fresh_rows
    ]
    if llm_client is None:
        llm_indexes, plain_indexes = list(range(len(enrich_inputs))), []
    else:
        llm_indexes, plain_indexes = split_enrich_indexes(rank_keys, max_enrich)
        if plain_indexes:
            stats.llm_degraded += len(plain_indexes)
            log(
                f"[富化] 候选 {len(enrich_inputs)} 条 > 上限 {max_enrich},预排序后仅富化 Top "
                f"{len(llm_indexes)} 条,其余 {len(plain_indexes)} 条降级(不消耗 token)"
            )
            tracker.update(f"富化 Top {len(llm_indexes)}/{len(enrich_inputs)} 条(其余降级)")

    def report_enrich_progress(done: int) -> None:
        nonlocal enrich_done
        enrich_done = done + len(plain_indexes)
        tracker.update(f"富化 {enrich_done}/{len(enrich_inputs)} 条", done=enrich_done)

    merged: list[EnrichResult | None] = [None] * len(enrich_inputs)
    enrich_tokens = 0
    if llm_client is None:
        for index, item in enumerate(enrich_inputs):
            merged[index] = plain(item)
        report_enrich_progress(len(enrich_inputs))
    else:
        usage_mark = llm_client.usage.as_dict()
        llm_inputs = [enrich_inputs[index] for index in llm_indexes]
        batch_size = max(1, int(general.get("enrich_batch_size") or 6))
        outcome = await enrich_many(
            llm_client,
            llm_inputs,
            topic_name=spec.name,
            keywords=keywords,
            batch_size=batch_size,
            semaphore=llm_sem,
            on_progress=report_enrich_progress,
            on_error=lambda exc: log(
                f"[富化] 批量调用失败,转单条重试(失败则降级): {truncate(str(exc), 160)}"
            ),
        )
        stats.llm_errors += outcome.fallback_items
        for position, index in enumerate(llm_indexes):
            merged[index] = outcome.results[position]
        for index in plain_indexes:
            merged[index] = plain(enrich_inputs[index])
        enrich_tokens = usage_delta(usage_mark, llm_client.usage.as_dict())["total_tokens"]
    enriched = [
        result if result is not None else plain(enrich_inputs[index])
        for index, result in enumerate(merged)
    ]
    token_note = f" · {enrich_tokens} tokens" if enrich_tokens else ""
    tracker.finish(
        "enrich",
        f"完成 {len(enriched)} 条 · LLM 失败 {stats.llm_errors} 条 · "
        f"降级 {len(plain_indexes)} 条{token_note}",
        done=len(enriched),
        llm_errors=stats.llm_errors,
        degraded=len(plain_indexes),
        tokens=enrich_tokens,
    )
    tracker.set_counters(llm_errors=stats.llm_errors, llm_degraded=stats.llm_degraded)

    weights = None
    if isinstance(spec.extra, dict):
        raw_weights = spec.extra.get("score_weights")
        if isinstance(raw_weights, dict):
            weights = raw_weights

    tracker.start("score", f"三维打分 {len(fresh_rows)} 条")
    accepted: list[tuple[Source, RawItem, str, str, str, str, EnrichResult, Any, bool]] = []
    for (
        src,
        raw,
        canonical,
        url_hash,
        fingerprint,
        digest,
        _hits,
        src_keywords,
        hot_channel,
    ), result in zip(fresh_rows, enriched, strict=True):
        text_all = " ".join(
            filter(
                None,
                [raw.title, raw.raw_text, result.translated_title, result.summary],
            )
        )
        kw_rel, kw_hits = keyword_relevance(text_all, src_keywords)
        if hot_channel and kw_rel < 50:
            # 热榜通道未命中关键词时按中性相关度计,让热度与时效决定是否入库。
            kw_rel = 50.0
        freshness = freshness_score(raw.published_at or now, result.content_type)
        heat = metric_heat_score(raw.metrics)
        score = combine_scores(
            keyword_rel=kw_rel,
            llm_rel=result.llm_relevance,
            llm_heat=result.llm_heat,
            metric_heat=heat,
            freshness=freshness,
            weights=weights,
            keyword_hits=kw_hits,
        )
        if score.total < spec.min_score:
            stats.low_score += 1
            detail_by_source[src.id]["low_score"] += 1
            log(
                f"[评分] 低于门槛({spec.min_score})跳过: {truncate(raw.title, 60)} "
                f"(相关 {score.relevance} / 热度 {score.heat} / "
                f"时效 {score.freshness} → {score.total})"
            )
            continue
        accepted.append(
            (src, raw, canonical, url_hash, fingerprint, digest, result, score, hot_channel)
        )

    tracker.set_counters(low_score=stats.low_score)
    tracker.finish(
        "score",
        f"达标 {len(accepted)} 条 · 低于门槛 {stats.low_score} 条",
        accepted=len(accepted),
        low_score=stats.low_score,
    )

    tracker.start("store", f"写入素材库 {len(accepted)} 条")
    meta_by_spec = collect_meta(spec)
    for src, raw, canonical, url_hash, fingerprint, digest, result, score, hot_channel in accepted:
        item = Item(
            source_id=src.id,
            channel=src.channel,
            content_type=result.content_type,
            title=raw.title,
            url=raw.url,
            canonical_url=canonical,
            canonical_url_hash=url_hash,
            title_fingerprint=fingerprint,
            simhash=digest,
            author=truncate(raw.author, 200) if raw.author else None,
            published_at=raw.published_at,
            lang=result.lang or detect_lang(raw.title),
            tags=(result.tags or []) + (["热榜"] if hot_channel else []),
            entities=result.entities or [],
        )
        session.add(item)
        await session.flush()
        session.add(
            ItemContent(
                item_id=item.id,
                raw_text=raw.raw_text,
                translated_title=result.translated_title,
                translated_text=result.translated_text,
                summary=result.summary,
                card=result.card,
            )
        )
        session.add(
            ItemScore(
                item_id=item.id,
                heat=score.heat,
                relevance=score.relevance,
                freshness=score.freshness,
                total=score.total,
                detail={**score.detail, **meta_by_spec, "enriched": result.model is not None},
                model=result.model,
            )
        )
        await _save_raw_document(session, src.id, raw, status="processed", item_id=item.id)
        stats.new_items += 1
        detail_by_source[src.id]["ingested"] += 1
        log(
            f"[入库] {result.content_type} {truncate(item.title, 60)} "
            f"(相关 {score.relevance} / 热度 {score.heat} / 时效 {score.freshness} → {score.total})"
        )
        if len(stats.items) < MAX_REPORT_ITEMS:
            stats.items.append(
                {
                    "id": item.id,
                    "type": result.content_type,
                    "title": item.title,
                    "url": item.url,
                    "relevance": score.relevance,
                    "heat": score.heat,
                    "freshness": score.freshness,
                    "total": score.total,
                }
            )
    await session.commit()
    tracker.set_counters(new_items=stats.new_items)
    tracker.finish("store", f"新增素材 {stats.new_items} 条", new_items=stats.new_items)


def _record_source_result(source: Source, *, ok: bool, error: str | None = None) -> None:
    source.last_fetch_at = datetime.now(UTC)
    if ok:
        source.last_success_at = source.last_fetch_at
        source.consecutive_failures = 0
        source.last_error = None
        if source.status == "degraded":
            source.status = "active"
    else:
        source.consecutive_failures = int(source.consecutive_failures or 0) + 1
        source.last_error = truncate(error or "unknown error", 500)
        if source.consecutive_failures >= 3 and source.status == "active":
            source.status = "degraded"


async def _save_raw_document(
    session: AsyncSession,
    source_id: int,
    raw: RawItem,
    *,
    status: str,
    item_id: int | None,
) -> None:
    session.add(
        RawDocument(
            source_id=source_id,
            url=raw.url,
            status=status,
            item_id=item_id,
            payload={
                "title": raw.title,
                "url": raw.url,
                "published_at": raw.published_at.isoformat() if raw.published_at else None,
                "author": raw.author,
                "external_id": raw.external_id,
                "metrics": raw.metrics,
                "extra": raw.extra,
                "raw_text": truncate(raw.raw_text or "", 4000),
            },
        )
    )
