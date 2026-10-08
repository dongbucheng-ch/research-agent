"""Digest generation: recall scored items -> LLM merge -> markdown + store.

两种模式(见 docs/collect-engine-plan.md §4.2):
- `global`(默认):不依赖方向/关键词,按「热度 0.6 + 时效 0.4」取最新最热;
- `topic`:围绕研究方向与关键词,按「相关度 0.5 + 热度 0.3 + 时效 0.2」排序。

GitHub 板块通过 `services.github_today` 实时取数(今日热榜 + 关键词补位),
保证是「今日最新最热」而不是库内缓存。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Digest, DigestItem, Item, ItemScore, PushChannel
from app.prompts import render_prompt
from app.services.app_settings import get_llm_config
from app.services.github_today import collect_github_today
from app.services.keyword_translate import translate_keywords
from app.services.llm import LLMClient, LLMError
from app.services.push import send_digest

logger = logging.getLogger(__name__)
LogFn = Callable[[str], None]

RESOURCE_TYPES = ("repo", "skill", "model")
GLOBAL_WEIGHTS = {"heat": 0.6, "freshness": 0.4}
TOPIC_WEIGHTS = {"relevance": 0.5, "heat": 0.3, "freshness": 0.2}
TOPIC_MIN_RELEVANCE = 20.0
NEWS_DEFAULT = 10
GITHUB_DEFAULT = 5
GITHUB_MIN = 3
GITHUB_MAX = 5

# 版式长度要求(字符数,标点计入;见 docs/collect-engine-plan.md §4.2)
SUMMARY_MIN = 250
SUMMARY_MAX = 500
BLURB_MIN = 100
BLURB_MAX = 200
_SENTENCE_ENDS = "。!?!?;;…"


async def run_digest(
    session: AsyncSession,
    *,
    scope: str = "global",
    topic: str | None = None,
    keywords: list[str] | None = None,
    period_hours: int = 24,
    max_items: int | None = None,
    github_count: int = GITHUB_DEFAULT,
    github_language: str | None = None,
    push_channel_id: int | None = None,
    min_score: int = 60,
    log: LogFn | None = None,
) -> dict[str, Any]:
    log = log or (lambda _message: None)
    scope = "topic" if str(scope).strip().lower() == "topic" else "global"
    words = [str(word).strip() for word in (keywords or []) if str(word).strip()]
    if scope == "topic" and not words:
        log("[配置] 定向模式缺少关键词,自动降级为全局模式")
        scope = "global"
    topic_name = str(topic).strip() if topic else ""
    limit = max(3, min(int(max_items or NEWS_DEFAULT), 20))
    github_limit = max(GITHUB_MIN, min(int(github_count or GITHUB_DEFAULT), GITHUB_MAX))
    now = datetime.now(UTC)
    since = now - timedelta(hours=int(period_hours))

    llm = LLMClient.from_config(await get_llm_config(session))
    search_words = list(words)
    translations: dict[str, list[str]] = {}
    if scope == "topic" and llm is not None:
        translations = await translate_keywords(llm, words, log=log)
        search_words = words + [alias for variants in translations.values() for alias in variants]

    pool = max(limit * 6, 60)
    candidates = await _recall(session, scope=scope, since=since, min_score=min_score, pool=pool)
    if not candidates:
        log(f"[召回] 窗口 {period_hours}h 内没有达到 {min_score} 分的素材")
        return {"digest_id": None, "item_count": 0, "reason": "no_candidates"}
    ranked = _rank_candidates(candidates, scope=scope, keywords=search_words)
    if not ranked:
        log("[召回] 窗口内素材未命中关键词,未生成日报;先用这些关键词到采集工作台采一次再试")
        return {"digest_id": None, "item_count": 0, "reason": "no_keyword_matches"}

    briefs = [_item_brief(item, rank=rank) for item, rank in ranked[: max(limit * 3, limit + 8)]]
    log(f"[召回] 召回 {len(candidates)} 条 → 排序取 {len(briefs)} 条进入生成")

    github_items = await _safe_github_today(search_words, github_limit, github_language, log)

    if llm is not None:
        try:
            payload = await _generate_with_llm(
                llm,
                scope=scope,
                topic_name=topic_name,
                keywords=search_words,
                briefs=briefs,
                github=github_items,
                limit=limit,
                github_limit=github_limit,
                now=now,
            )
        except LLMError as exc:
            log(f"[生成] LLM 生成失败,使用降级模板: {exc}")
            payload = _fallback_payload(
                briefs, limit, now, github=github_items, github_limit=github_limit
            )
    else:
        log("[生成] LLM 未配置,使用降级模板生成")
        payload = _fallback_payload(
            briefs, limit, now, github=github_items, github_limit=github_limit
        )
    payload["items"] = [entry for entry in payload.get("items") or [] if isinstance(entry, dict)]
    _backfill_items(payload, briefs, limit, log=log)
    payload = await _fit_lengths(payload, briefs, llm=llm, log=log)

    github_selected = _select_github(payload, github_items, github_limit)
    short_github = sum(
        1 for entry in github_selected if _char_count(entry.get("blurb")) < BLURB_MIN
    )
    if short_github:
        log(f"[提示] {short_github} 条 GitHub 介绍偏短(LLM 未给足,已用候选 description 兜底)")
    if len(github_selected) < GITHUB_MIN:
        log(
            f"[提示] GitHub 今日推荐仅 {len(github_selected)} 条"
            f"(要求 {GITHUB_MIN}-{GITHUB_MAX} 条)"
            "; 该方向当日在 GitHub 的命中不足,可放宽关键词或稍后重试"
        )
    content_md, used_briefs = _render_markdown(payload, briefs, github_selected)
    news_items = len([entry for entry in payload.get("items") or [] if entry.get("source_ids")])
    shortfall = compute_shortfall(
        news_items=news_items, limit=limit, github_items=len(github_selected)
    )
    if "news" in shortfall:
        log(
            f"[提示] 本次资讯素材不足,只输出 {news_items} 条(目标 {limit} 条);"
            "可到采集工作台补充该方向素材后重新生成"
        )
    digest = Digest(
        title=str(payload.get("title") or _default_title(now)),
        lead=str(payload.get("lead") or ""),
        content_md=content_md,
        highlights=payload.get("highlights") or [],
        period_start=since,
        period_end=now,
        item_count=len({brief["id"] for brief in used_briefs}),
        status="draft",
        model=llm.model if llm is not None else None,
        meta={
            "batch": await next_batch(session, now),
            "scope": scope,
            "topic": topic_name or None,
            "keywords": words,
            "keywords_expanded": search_words if search_words != words else None,
            "keyword_translations": translations or None,
            "window_hours": int(period_hours),
            "min_score": int(min_score),
            "recall_pool": len(candidates),
            "news_count": news_items,
            "news_materials": len(used_briefs),
            "github_count": len(github_selected),
            "github_sources": sorted(
                {str(entry.get("source") or "") for entry in github_selected} - {""}
            ),
            "github": github_selected,
            "shortfall": shortfall or None,
        },
    )
    session.add(digest)
    await session.flush()
    for position, brief in enumerate(used_briefs, start=1):
        session.add(DigestItem(digest_id=digest.id, item_id=brief["id"], position=position))
    await session.commit()
    log(
        f"[完成] 已生成日报 #{digest.id}: {digest.title}"
        f"(资讯 {news_items} 条 · 素材 {digest.item_count} 条 / GitHub {len(github_selected)} 条)"
    )

    if push_channel_id is not None:
        channel = await session.get(PushChannel, push_channel_id)
        if channel is None or not channel.enabled:
            log("[推送] 推送渠道不存在或未启用,跳过推送")
        else:
            push_log = await send_digest(session, digest=digest, channel=channel)
            await session.commit()
            if push_log.status == "success":
                log(f"[推送] {channel.name} 推送成功")
            else:
                log(f"[推送] {channel.name} 推送失败: {push_log.error}")
    return {
        "digest_id": digest.id,
        "item_count": digest.item_count,
        "github_count": len(github_selected),
        "scope": scope,
        "title": digest.title,
        "llm_usage": llm.usage.as_dict() if llm is not None else {},
    }


def compute_shortfall(
    *, news_items: int, limit: int, github_items: int, github_min: int | None = None
) -> dict[str, dict[str, int]]:
    """产出数量不足时,给出「期望 / 实际」,供 meta 与前端提示使用。"""
    minimum = GITHUB_MIN if github_min is None else int(github_min)
    shortfall: dict[str, dict[str, int]] = {}
    if news_items < int(limit):
        shortfall["news"] = {"expected": int(limit), "actual": int(news_items)}
    if github_items < minimum:
        shortfall["github"] = {"expected": minimum, "actual": int(github_items)}
    return shortfall


async def _recall(
    session: AsyncSession,
    *,
    scope: str,
    since: datetime,
    min_score: int,
    pool: int,
) -> list[Item]:
    published = func.coalesce(Item.published_at, Item.first_seen_at)
    conditions = [
        Item.status == "active",
        ItemScore.total >= min_score,
        published >= since,
    ]
    if scope == "global":
        conditions.append(Item.content_type.not_in(RESOURCE_TYPES))
    order = ItemScore.heat.desc() if scope == "global" else ItemScore.relevance.desc()
    stmt = (
        select(Item)
        .join(ItemScore, ItemScore.item_id == Item.id)
        .where(*conditions)
        .order_by(order, ItemScore.total.desc())
        .limit(pool)
    )
    return list(await session.scalars(stmt))


def _item_text(item: Item) -> str:
    content = item.content
    parts = [
        item.title,
        content.translated_title if content else None,
        content.summary if content else None,
        " ".join(str(tag) for tag in (item.tags or [])),
    ]
    return " ".join(str(part) for part in parts if part).lower()


def _keyword_ratio(item: Item, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    text = _item_text(item)
    hits = sum(1 for word in keywords if word.lower() in text)
    return hits / len(keywords)


def _rank_score(item: Item, *, scope: str, relevance: float) -> float:
    score = item.score
    if score is None:
        return 0.0
    heat = float(score.heat or 0.0)
    freshness = float(score.freshness or 0.0)
    if scope == "global":
        return round(GLOBAL_WEIGHTS["heat"] * heat + GLOBAL_WEIGHTS["freshness"] * freshness, 2)
    return round(
        TOPIC_WEIGHTS["relevance"] * relevance
        + TOPIC_WEIGHTS["heat"] * heat
        + TOPIC_WEIGHTS["freshness"] * freshness,
        2,
    )


def _rank_candidates(
    items: list[Item], *, scope: str, keywords: list[str]
) -> list[tuple[Item, float]]:
    ranked: list[tuple[Item, float]] = []
    for item in items:
        db_relevance = float(item.score.relevance) if item.score else 0.0
        if scope == "topic":
            ratio = _keyword_ratio(item, keywords)
            if ratio <= 0 and db_relevance < TOPIC_MIN_RELEVANCE:
                continue
            relevance = max(db_relevance, round(100.0 * ratio, 2))
        else:
            relevance = db_relevance
        ranked.append((item, _rank_score(item, scope=scope, relevance=relevance)))
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return ranked


def _item_brief(item: Item, rank: float | None = None) -> dict[str, Any]:
    content = item.content
    score = item.score
    translated = content.translated_title if content else None
    return {
        "id": item.id,
        "title": translated or item.title,
        "original_title": item.title,
        "summary": (content.summary if content else None) or "",
        "url": item.url,
        "channel": item.channel,
        "content_type": item.content_type,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "score": score.total if score else None,
        "rank_score": rank,
        "tags": item.tags or [],
    }


async def _safe_github_today(
    keywords: list[str], limit: int, language: str | None, log: LogFn
) -> list[dict[str, Any]]:
    try:
        items = await collect_github_today(
            keywords=keywords,
            limit=limit,
            language=language,
            # 日报在后台生成,给 GitHub 取数留更宽裕的超时(代理抖动常见)
            timeout=max(float(get_settings().fetch_timeout_seconds), 30.0),
        )
    except Exception as exc:  # noqa: BLE001 - GitHub 取数失败不阻断日报
        logger.warning("github today fetch failed", exc_info=True)
        log(f"[召回] GitHub 今日推荐取数失败,跳过板块: {exc}")
        return []
    sources = ",".join(sorted({str(item.get("source") or "") for item in items} - {""}))
    log(f"[召回] GitHub 今日推荐 {len(items)} 条(来源: {sources or '-'})")
    return items


async def _generate_with_llm(
    llm: LLMClient,
    *,
    scope: str,
    topic_name: str,
    keywords: list[str],
    briefs: list[dict[str, Any]],
    github: list[dict[str, Any]],
    limit: int,
    github_limit: int,
    now: datetime,
) -> dict[str, Any]:
    if scope == "global":
        mode_desc = "全局模式:不限定方向与关键词,选取最近窗口内最新最热的资讯;GitHub 为今日热榜。"
    else:
        mode_desc = (
            f"定向模式:研究方向「{topic_name or '未命名'}」;"
            f"关键词:{'、'.join(keywords)}。素材须与方向或关键词直接相关。"
        )
    notes: list[str] = []
    if len(briefs) < limit:
        notes.append(
            f"资讯素材只有 {len(briefs)} 条(目标 {limit} 条):按实际数量输出,"
            "不得为凑数重复素材或编造事件;证据不足的条目在正文中写明「目前公开信息有限」。"
        )
    if len(github) < github_limit:
        notes.append(
            f"GitHub 候选只有 {len(github)} 个(目标 {github_limit} 个):"
            "不足则全部收录,严禁编造仓库。"
        )
    prompt = render_prompt(
        "digest",
        mode_desc=mode_desc,
        material_note="\n".join(notes) or f"素材充足,请写满 {limit} 条。",
        date_str=now.astimezone().strftime("%Y-%m-%d"),
        max_items=str(limit),
        github_max=str(github_limit),
        items_json=json.dumps(briefs, ensure_ascii=False),
        github_json=json.dumps(github, ensure_ascii=False),
    )
    data = await llm.chat_json(prompt)
    if not isinstance(data, dict):
        raise LLMError("digest response is not a JSON object")
    return data


def _default_title(now: datetime) -> str:
    return f"研讯日报 · {now.astimezone().strftime('%m-%d')}"


def batch_window(now: datetime) -> tuple[datetime, datetime]:
    """日报批次的本地自然日窗口 [start, end)。"""
    local = now.astimezone()
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


async def next_batch(session: AsyncSession, now: datetime) -> dict[str, Any]:
    """「日期 + 第 N 批」索引:当天本地时区已生成日报数 + 1(列表主键,标题保持 LLM 原文)。"""
    start, end = batch_window(now)
    count = await session.scalar(
        select(func.count())
        .select_from(Digest)
        .where(Digest.created_at >= start, Digest.created_at < end)
    )
    return {"date": start.date().isoformat(), "index": int(count or 0) + 1}


def _fallback_payload(
    briefs: list[dict[str, Any]],
    limit: int,
    now: datetime,
    github: list[dict[str, Any]] | None = None,
    github_limit: int = GITHUB_DEFAULT,
) -> dict[str, Any]:
    selected = briefs[:limit]
    github_selected = list(github or [])[:github_limit]
    lead = f"本期汇总最近时间窗内的 {len(selected)} 条高分资讯"
    lead += f",并附 GitHub 今日推荐 {len(github_selected)} 项。" if github_selected else "。"
    return {
        "title": _default_title(now),
        "lead": lead,
        "highlights": [brief["title"] for brief in selected[:3]],
        "items": [
            {
                "title": brief["title"],
                "summary": brief["summary"],
                "source_ids": [brief["id"]],
            }
            for brief in selected
        ],
        "github": [
            {
                "full_name": entry.get("full_name"),
                "blurb": entry.get("description") or entry.get("hot") or "",
            }
            for entry in github_selected
        ],
    }


def _select_github(
    payload: dict[str, Any],
    candidates: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """校验 LLM 选择的仓库(必须在候选内),不足时按候选顺序补齐。"""
    by_name = {str(entry.get("full_name") or ""): entry for entry in candidates}
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in payload.get("github") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("full_name") or "").strip()
        candidate = by_name.get(name)
        if candidate is None or name in seen:
            continue
        seen.add(name)
        enriched = dict(candidate)
        enriched["blurb"] = _clamp_text(
            str(entry.get("blurb") or "").strip() or str(candidate.get("description") or ""),
            BLURB_MAX,
        )
        selected.append(enriched)
        if len(selected) >= limit:
            return selected
    for candidate in candidates:
        if len(selected) >= min(limit, len(candidates)):
            break
        name = str(candidate.get("full_name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        enriched = dict(candidate)
        enriched["blurb"] = str(candidate.get("description") or "")
        selected.append(enriched)
    return selected


def _format_stars(value: Any) -> str:
    try:
        stars = int(value or 0)
    except (TypeError, ValueError):
        return "0"
    if stars >= 1000:
        return f"{stars / 1000:.1f}k".replace(".0k", "k")
    return str(stars)


def _github_detail(entry: dict[str, Any]) -> str:
    """GitHub 条目的「标签:」行:语言 · 星数 · 今日/日均新增。"""
    parts: list[str] = []
    language = str(entry.get("language") or "").strip()
    if language:
        parts.append(language)
    total = int(entry.get("stars_total") or 0)
    today = int(entry.get("stars_today") or 0)
    per_day = entry.get("stars_per_day")
    if total:
        parts.append(f"★{_format_stars(total)}")
    if today:
        parts.append(f"今日 +{today}")
    elif per_day:
        parts.append(f"日均 +{per_day}")
    return " · ".join(parts)


def _normalize_space(text: Any) -> str:
    return " ".join(str(text or "").split())


def _char_count(text: Any) -> int:
    """版式字数:只数非空白字符,中文/英文/标点都按 1 个字符算。"""
    return len("".join(str(text or "").split()))


def _slice_chars(text: str, limit: int) -> str:
    """按「非空白字符数」截取前 limit 个字符。"""
    count = 0
    end = 0
    for index, char in enumerate(text):
        if char != " ":
            count += 1
        if count > limit:
            break
        end = index + 1
    return text[:end].rstrip()


def _clamp_text(text: Any, limit: int) -> str:
    """超长时截断:优先在句末断开,否则硬截断加省略号,总长不超过 limit。"""
    raw = _normalize_space(text)
    if _char_count(raw) <= limit:
        return raw
    trimmed = _slice_chars(raw, limit)
    floor = max(1, int(limit * 0.6))
    for index in range(len(trimmed) - 1, -1, -1):
        if trimmed[index] in _SENTENCE_ENDS and _char_count(trimmed[: index + 1]) >= floor:
            return trimmed[: index + 1]
    return _slice_chars(raw, max(1, limit - 1)) + "…"


def _brief_refs(
    entry: dict[str, Any], by_id: dict[int, dict[str, Any]], limit: int = 3
) -> list[dict[str, str]]:
    """给长度补写用的参考素材(标题 + 摘要),避免模型凭空扩写。"""
    refs: list[dict[str, str]] = []
    for value in entry.get("source_ids") or []:
        try:
            brief = by_id.get(int(value))
        except (TypeError, ValueError):
            continue
        if not brief:
            continue
        refs.append(
            {
                "title": str(brief.get("title") or ""),
                "summary": _clamp_text(brief.get("summary"), 300),
                "url": str(brief.get("url") or ""),
            }
        )
        if len(refs) >= limit:
            break
    return refs


def _backfill_items(
    payload: dict[str, Any],
    briefs: list[dict[str, Any]],
    limit: int,
    *,
    log: LogFn,
) -> int:
    """LLM 少写时,用排名靠前的未引用素材补足条数(仍受素材总量限制)。

    日报版式要求「最多 10 条资讯」,但 LLM 遇到同质素材容易只写 5-6 条;
    这里做确定性补齐,同时把「LLM 少写 / 丢弃无效引用」写进日志,便于排查条数异常。
    """
    brief_ids = {brief["id"] for brief in briefs}
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raw_items = []
    items: list[dict[str, Any]] = []
    used: set[int] = set()
    dropped = 0
    for entry in raw_items:
        if not isinstance(entry, dict):
            dropped += 1
            continue
        ids: list[int] = []
        for value in entry.get("source_ids") or []:
            try:
                item_id = int(value)
            except (TypeError, ValueError):
                continue
            if item_id in brief_ids and item_id not in ids:
                ids.append(item_id)
        if not ids:
            dropped += 1
            continue
        entry["source_ids"] = ids
        used.update(ids)
        items.append(entry)
    payload["items"] = items

    target = min(int(limit), len(briefs))
    added = 0
    for brief in briefs:
        if len(items) >= target:
            break
        if brief["id"] in used:
            continue
        used.add(brief["id"])
        items.append(
            {
                "title": str(brief.get("title") or "")[:32],
                "summary": str(brief.get("summary") or ""),
                "source_ids": [brief["id"]],
                "auto": True,
            }
        )
        added += 1
    if added or dropped:
        log(
            f"资讯条数:LLM 输出 {len(items) - added} 条(丢弃 {dropped} 条),"
            f"补齐 {added} 条 → 共 {len(items)} 条(目标 {target} 条)"
        )
    elif len(items) < target:
        log(f"[生成] 资讯条数:{len(items)} 条(素材不足,target {target} 条)")
    return added


def _length_targets(payload: dict[str, Any], briefs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {brief["id"]: brief for brief in briefs}
    targets: list[dict[str, Any]] = []
    for index, entry in enumerate(payload.get("items") or []):
        if not isinstance(entry, dict):
            continue
        chars = _char_count(entry.get("summary"))
        if SUMMARY_MIN <= chars <= SUMMARY_MAX:
            continue
        targets.append(
            {
                "kind": "item",
                "key": str(index),
                "title": _normalize_space(entry.get("title")),
                "text": _clamp_text(entry.get("summary"), SUMMARY_MAX),
                "chars": chars,
                "min": SUMMARY_MIN,
                "max": SUMMARY_MAX,
                "refs": _brief_refs(entry, by_id),
            }
        )
    for entry in payload.get("github") or []:
        if not isinstance(entry, dict):
            continue
        chars = _char_count(entry.get("blurb"))
        if BLURB_MIN <= chars <= BLURB_MAX:
            continue
        targets.append(
            {
                "kind": "github",
                "key": _normalize_space(entry.get("full_name")),
                "title": _normalize_space(entry.get("full_name")),
                "text": _clamp_text(entry.get("blurb"), BLURB_MAX),
                "chars": chars,
                "min": BLURB_MIN,
                "max": BLURB_MAX,
            }
        )
    return targets


def _apply_repair(payload: dict[str, Any], data: Any) -> int:
    """把补写结果回填到 payload,返回成功改写条数。"""
    if not isinstance(data, dict):
        return 0
    applied = 0
    items = payload.get("items") or []
    for row in data.get("items") or []:
        if not isinstance(row, dict):
            continue
        try:
            index = int(row.get("key"))
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(items) and isinstance(items[index], dict):
            text = _normalize_space(row.get("text") or row.get("summary"))
            if text:
                items[index]["summary"] = text
                applied += 1
    by_name = {
        _normalize_space(entry.get("full_name")): entry
        for entry in payload.get("github") or []
        if isinstance(entry, dict)
    }
    for row in data.get("github") or []:
        if not isinstance(row, dict):
            continue
        entry = by_name.get(_normalize_space(row.get("key") or row.get("full_name")))
        if entry is None:
            continue
        text = _normalize_space(row.get("text") or row.get("blurb"))
        if text:
            entry["blurb"] = text
            applied += 1
    return applied


async def _fit_lengths(
    payload: dict[str, Any],
    briefs: list[dict[str, Any]],
    *,
    llm: LLMClient | None,
    log: LogFn,
) -> dict[str, Any]:
    """把资讯正文夹到 250-500 字符、GitHub 介绍夹到 100-200 字符。

    超长的直接截断(硬约束);偏短的先让 LLM 按素材补写一次,仍偏短只记日志不再纠缠。
    """
    targets = _length_targets(payload, briefs)
    if not targets:
        return payload
    repaired = 0
    if llm is not None:
        try:
            data = await llm.chat_json(
                render_prompt(
                    "digest_repair",
                    targets_json=json.dumps(targets, ensure_ascii=False),
                )
            )
            repaired = _apply_repair(payload, data)
        except LLMError as exc:
            log(f"[生成] 正文长度补写失败,仅做超长截断: {exc}")
    for entry in payload.get("items") or []:
        if isinstance(entry, dict):
            entry["summary"] = _clamp_text(entry.get("summary"), SUMMARY_MAX)
    for entry in payload.get("github") or []:
        if isinstance(entry, dict):
            entry["blurb"] = _clamp_text(entry.get("blurb"), BLURB_MAX)
    short = sum(
        1
        for entry in (payload.get("items") or [])
        if isinstance(entry, dict) and _char_count(entry.get("summary")) < SUMMARY_MIN
    ) + sum(
        1
        for entry in (payload.get("github") or [])
        if isinstance(entry, dict) and _char_count(entry.get("blurb")) < BLURB_MIN
    )
    log(
        f"正文长度整形:{len(targets)} 条不达标,补写 {repaired} 条"
        + (f",仍有 {short} 条偏短" if short else "")
    )
    return payload


def _link_label(brief: dict[str, Any]) -> str:
    """链接列表里的原文标题(优先原始标题),转义 markdown 方括号。"""
    label = str(brief.get("original_title") or brief.get("title") or "原文链接")
    label = " ".join(label.split())
    return label.replace("[", "\\[").replace("]", "\\]") or "原文链接"


def _render_markdown(
    payload: dict[str, Any],
    briefs: list[dict[str, Any]],
    github: list[dict[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    by_id = {brief["id"]: brief for brief in briefs}
    lines: list[str] = [f"# {payload.get('title') or '研讯日报'}", ""]
    lead = str(payload.get("lead") or "").strip()
    if lead:
        lines += [f"> {lead}", ""]

    lines += ["## 今日资讯", ""]
    used: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    position = 0
    for entry in payload.get("items") or []:
        title = str(entry.get("title") or "").strip()
        summary = str(entry.get("summary") or "").strip()
        source_ids: list[int] = []
        for value in entry.get("source_ids") or []:
            try:
                source_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        refs = [by_id[sid] for sid in source_ids if sid in by_id]
        if not title or not refs:
            continue
        position += 1
        lines.append(f"### {position}. {title}")
        if summary:
            lines.append(summary)
        lines.append("")
        for ref in refs:
            lines.append(f"- [{_link_label(ref)}]({ref['url']})")
            if ref["id"] not in seen_ids:
                seen_ids.add(ref["id"])
                used.append(ref)
        lines.append("")
    if not used:
        lines += ["(本期无可用条目)", ""]

    lines += ["## GitHub 今日推荐", ""]
    if github:
        for index, entry in enumerate(github, start=1):
            name = str(entry.get("full_name") or "").strip()
            url = str(entry.get("url") or "").strip()
            blurb = str(entry.get("blurb") or entry.get("description") or "").strip()
            lines.append(f"### {index}. {name}")
            lines.append(f"标签：{_github_detail(entry)}")
            if blurb:
                lines += ["", blurb]
            if url:
                lines += ["", f"- [{name}]({url})"]
            lines.append("")
    else:
        lines += ["(本期未取到 GitHub 数据)", ""]
    return "\n".join(lines).rstrip() + "\n", used
