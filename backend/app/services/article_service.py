"""完整文章生成:召回 → LLM 过滤 → 选题大纲 → 逐节写作 → 合成(搬 STORM 流程形状)。

流程与约束见 docs/collect-engine-plan.md §4.1。关键点:
- 召回只取非资源类素材(repo/skill/model 由 GitHub 板块承载),关键词未命中的直接丢弃;
- 逐节写作必须引用 `[n]` 编号,编号由本地映射(不依赖 LLM 复述 URL),参考文献列表本地拼装;
- 任何一步 LLM 失败都尽量降级(小节跳过 / 合成本地拼接),但不会编造素材之外的事实。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Article, Item, ItemScore, PushChannel
from app.prompts import render_prompt
from app.services.app_settings import get_llm_config
from app.services.digest_service import RESOURCE_TYPES, _item_brief, _rank_candidates
from app.services.keyword_translate import translate_keywords
from app.services.llm import LLMClient, LLMError
from app.services.push import send_target

logger = logging.getLogger(__name__)
LogFn = Callable[[str], None]

_REF_RE = re.compile(r"\[(\d{1,2})\](?!\()")
_MIN_SECTIONS = 2
_MAX_SECTIONS = 5


async def run_article(
    session: AsyncSession,
    *,
    topic: str | None = None,
    keywords: list[str] | None = None,
    period_hours: int = 168,
    max_sources: int = 12,
    target_words: int = 1800,
    min_score: int = 60,
    push_channel_id: int | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    log = log or (lambda _message: None)
    words = [str(word).strip() for word in (keywords or []) if str(word).strip()]
    if not words:
        raise ValueError("生成完整文章至少需要一个关键词")
    topic_name = str(topic).strip() if topic else ""
    max_sources = max(3, min(int(max_sources), 30))
    target_words = max(600, min(int(target_words), 6000))
    now = datetime.now(UTC)
    since = now - timedelta(hours=int(period_hours))

    # 与采集/日报一致:中文关键词先补英文译名,否则英文素材会被相关度过滤掉
    llm_config = await get_llm_config(session)
    llm = LLMClient.from_config(llm_config)
    search_words = list(words)
    translations: dict[str, list[str]] = {}
    if llm is not None:
        translations = await translate_keywords(llm, words, log=log)
        search_words = words + [alias for variants in translations.values() for alias in variants]

    pool = min(160, max(max_sources * 4, 40))
    candidates = await _recall(session, since=since, min_score=min_score, pool=pool)
    if not candidates:
        log(f"[召回] 窗口 {period_hours}h 内没有达到 {min_score} 分的素材")
        return {"article_id": None, "reason": "no_candidates"}
    ranked = _rank_candidates(candidates, scope="topic", keywords=search_words)
    if not ranked:
        log("[召回] 窗口内素材未命中关键词;先用这些关键词到采集工作台采一次再试")
        return {"article_id": None, "reason": "no_keyword_matches"}
    briefs = [_item_brief(item, rank=rank) for item, rank in ranked[: max(max_sources * 3, 24)]]
    log(f"[召回] 召回 {len(candidates)} 条 → 排序取 {len(briefs)} 条进入过滤")

    if llm is None:
        raise RuntimeError("LLM 未配置,无法生成完整文章(请先在「设置」中配置)")
    concurrency = max(1, min(int((llm_config or {}).get("max_concurrency") or 3), 4))

    by_id = {brief["id"]: brief for brief in briefs}
    kept_ids = await _filter_items(llm, topic_name, search_words, briefs, max_sources, log)
    kept = [dict(by_id[item_id]) for item_id in kept_ids if item_id in by_id]
    if not kept:
        raise RuntimeError("LLM 过滤后没有可用素材")
    for ref, brief in enumerate(kept, start=1):
        brief["ref"] = ref
    log(f"[过滤] 过滤后保留 {len(kept)} 条素材(事件归并完成)")

    outline = await _outline(llm, topic_name, search_words, kept, target_words, log)
    sections = _validate_sections(outline, kept)
    log(f"[大纲] {outline.get('title') or '-'} · {len(sections)} 节")

    semaphore = asyncio.Semaphore(concurrency)

    async def _draft(section: dict[str, Any]) -> dict[str, Any] | None:
        async with semaphore:
            try:
                text = await _write_section(llm, outline, section, kept, target_words)
            except LLMError as exc:
                log(f"[写作] 小节「{section['heading']}」写作失败,跳过: {exc}")
                return None
            return {"heading": section["heading"], "text": text}

    drafted = await asyncio.gather(*(_draft(section) for section in sections))
    section_drafts = [draft for draft in drafted if draft is not None]
    if not section_drafts:
        raise RuntimeError("所有小节写作均失败,未生成文章")

    try:
        final = await _compose(llm, outline, section_drafts, kept, target_words)
    except LLMError as exc:
        log(f"[合成] 失败,使用各节初稿直接拼接: {exc}")
        final = {
            "title": outline.get("title"),
            "lead": outline.get("lead"),
            "body_md": "\n\n".join(
                f"## {draft['heading']}\n\n{draft['text']}" for draft in section_drafts
            ),
        }

    title = str(final.get("title") or outline.get("title") or f"{topic_name or '研究'}进展").strip()
    lead = str(final.get("lead") or outline.get("lead") or "").strip()
    body = _strip_reference_block(str(final.get("body_md") or "").strip())
    if not body:
        body = "\n\n".join(f"## {d['heading']}\n\n{d['text']}" for d in section_drafts)

    cited_refs = _parse_refs(body)
    refs_used = cited_refs or list(range(1, len(kept) + 1))
    content_md = _assemble(title, lead, body, refs_used, kept)
    source_item_ids = [kept[ref - 1]["id"] for ref in refs_used if 1 <= ref <= len(kept)]
    char_count = len(re.sub(r"\s", "", content_md))
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", content_md))
    shortfall: dict[str, Any] = {}
    if char_count < target_words * 0.6:
        log(f"[提示] 正文 {char_count} 字,低于目标的 60%({target_words} 字)")
        shortfall["words"] = {"expected": int(target_words * 0.6), "actual": char_count}
    if len(kept) < min(6, max_sources):
        shortfall["materials"] = {"expected": min(6, max_sources), "actual": len(kept)}
        log(
            f"[提示] 可用素材仅 {len(kept)} 条(建议 ≥{min(6, max_sources)} 条);"
            "可先补充该方向素材后重新生成"
        )

    article = Article(
        title=title,
        topic=topic_name or None,
        keywords=words,
        content_md=content_md,
        source_item_ids=source_item_ids,
        status="draft",
        model=llm.model,
        meta={
            "topic": topic_name or None,
            "keywords": words,
            "keywords_expanded": search_words if search_words != words else None,
            "keyword_translations": translations or None,
            "window_hours": int(period_hours),
            "min_score": int(min_score),
            "target_words": target_words,
            "recall_pool": len(candidates),
            "kept": len(kept),
            "sections": [draft["heading"] for draft in section_drafts],
            "cited_refs": cited_refs,
            "char_count": char_count,
            "cjk_count": cjk_count,
            "shortfall": shortfall or None,
        },
    )
    session.add(article)
    await session.commit()
    log(
        f"[完成] 已生成文章 #{article.id}: {article.title}"
        f"({char_count} 字 / 引用 {len(source_item_ids)} 条)"
    )

    if push_channel_id is not None:
        channel = await session.get(PushChannel, push_channel_id)
        if channel is None or not channel.enabled:
            log("[推送] 推送渠道不存在或未启用,跳过推送")
        else:
            push_log = await send_target(
                session, target_kind="article", target_id=article.id, channel=channel
            )
            await session.commit()
            if push_log.status == "success":
                log(f"[推送] {channel.name} 推送成功")
            else:
                log(f"[推送] {channel.name} 推送失败: {push_log.error}")
    return {
        "article_id": article.id,
        "title": article.title,
        "char_count": char_count,
        "source_count": len(source_item_ids),
        "llm_usage": llm.usage.as_dict() if llm is not None else {},
    }


async def _recall(
    session: AsyncSession, *, since: datetime, min_score: int, pool: int
) -> list[Item]:
    published = func.coalesce(Item.published_at, Item.first_seen_at)
    stmt = (
        select(Item)
        .join(ItemScore, ItemScore.item_id == Item.id)
        .where(
            Item.status == "active",
            ItemScore.total >= min_score,
            published >= since,
            Item.content_type.not_in(RESOURCE_TYPES),
        )
        .order_by(ItemScore.relevance.desc(), ItemScore.total.desc())
        .limit(pool)
    )
    return list(await session.scalars(stmt))


def _parse_refs(text: str) -> list[int]:
    """提取正文中的 [n] 引用编号(排除 markdown 链接 [1](url))。"""
    return sorted({int(match) for match in _REF_RE.findall(text or "")})


def _count_refs(text: str) -> int:
    return len(_parse_refs(text))


def _validate_sections(outline: dict[str, Any], kept: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """校验大纲小节:source_ids 必须指向保留素材;无有效引用的节直接丢弃。"""
    valid_ids = {brief["id"] for brief in kept}
    sections: list[dict[str, Any]] = []
    for raw in outline.get("sections") or []:
        if not isinstance(raw, dict):
            continue
        heading = str(raw.get("heading") or "").strip()
        if not heading:
            continue
        source_ids: list[int] = []
        for value in raw.get("source_ids") or []:
            try:
                item_id = int(value)
            except (TypeError, ValueError):
                continue
            if item_id in valid_ids and item_id not in source_ids:
                source_ids.append(item_id)
        if not source_ids:
            continue
        points = [str(point).strip() for point in (raw.get("points") or []) if str(point).strip()]
        sections.append({"heading": heading, "points": points, "source_ids": source_ids})
        if len(sections) >= _MAX_SECTIONS:
            break
    if len(sections) >= _MIN_SECTIONS:
        return sections
    # 兜底:LLM 大纲不可用时,用全部素材合成单节
    return [
        {
            "heading": "核心进展",
            "points": ["按素材梳理背景、关键进展与影响"],
            "source_ids": [brief["id"] for brief in kept],
        }
    ]


def _filter_items_result(
    payload: Any, candidates: list[dict[str, Any]], max_sources: int
) -> list[int]:
    """校验过滤结果:只保留候选内 id,去重且保序。"""
    valid_ids = [brief["id"] for brief in candidates]
    valid = set(valid_ids)
    kept: list[int] = []
    for value in (payload or {}).get("kept") or []:
        try:
            item_id = int(value)
        except (TypeError, ValueError):
            continue
        if item_id in valid and item_id not in kept:
            kept.append(item_id)
    return kept[:max_sources]


def _ref_sources(kept: list[dict[str, Any]], refs: list[int]) -> str:
    lines = []
    by_ref = {brief["ref"]: brief for brief in kept}
    for ref in refs:
        brief = by_ref.get(ref)
        if brief is None:
            continue
        summary = str(brief.get("summary") or "").strip()
        lines.append(
            f"[{ref}] {brief['title']} —— {summary}({brief['url']})"
            if summary
            else f"[{ref}] {brief['title']}({brief['url']})"
        )
    return "\n".join(lines) or "(无)"


def _strip_reference_block(body: str) -> str:
    marker = body.find("## 参考来源")
    return body[:marker].strip() if marker >= 0 else body.strip()


def _assemble(
    title: str,
    lead: str,
    body: str,
    refs: list[int],
    kept: list[dict[str, Any]],
) -> str:
    by_ref = {brief["ref"]: brief for brief in kept}
    lines = [f"# {title}", ""]
    if lead:
        lines += [f"> {lead}", ""]
    lines += [body.strip(), "", "## 参考来源", ""]
    for position, ref in enumerate(refs, start=1):
        brief = by_ref.get(ref)
        if brief is None:
            continue
        published = str(brief.get("published_at") or "")[:10]
        detail = " · ".join(part for part in (brief.get("channel"), published) if part)
        link = f"{position}. [{brief['title']}]({brief['url']})"
        lines.append(link + (f" · {detail}" if detail else ""))
    return "\n".join(lines).strip() + "\n"


async def _filter_items(
    llm: LLMClient,
    topic_name: str,
    keywords: list[str],
    briefs: list[dict[str, Any]],
    max_sources: int,
    log: LogFn,
) -> list[int]:
    prompt = render_prompt(
        "article_filter",
        topic_name=topic_name or "未指定",
        keywords="、".join(keywords),
        max_sources=str(max_sources),
        items_json=json.dumps(briefs, ensure_ascii=False),
    )
    data = await llm.chat_json(prompt)
    kept = _filter_items_result(data, briefs, max_sources)
    if not kept:
        log("[过滤] 结果为空,回退为按相关度取前 N 条")
        kept = [brief["id"] for brief in briefs[:max_sources]]
    return kept


async def _outline(
    llm: LLMClient,
    topic_name: str,
    keywords: list[str],
    kept: list[dict[str, Any]],
    target_words: int,
    log: LogFn,
) -> dict[str, Any]:
    prompt = render_prompt(
        "article_outline",
        topic_name=topic_name or "未指定",
        keywords="、".join(keywords),
        target_words=str(target_words),
        items_json=json.dumps(kept, ensure_ascii=False),
    )
    try:
        data = await llm.chat_json(prompt)
    except LLMError as exc:
        log(f"[大纲] 失败,使用兜底结构: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


async def _write_section(
    llm: LLMClient,
    outline: dict[str, Any],
    section: dict[str, Any],
    kept: list[dict[str, Any]],
    target_words: int,
) -> str:
    by_ref = {brief["ref"]: brief for brief in kept}
    refs = [by_ref[item_id]["ref"] for item_id in section["source_ids"] if item_id in by_ref]
    section_count = min(len(outline.get("sections") or []) or 4, 5)
    section_words = max(250, target_words // max(1, section_count))
    prompt = render_prompt(
        "article_section",
        article_title=str(outline.get("title") or "研究进展"),
        angle=str(outline.get("angle") or ""),
        heading=section["heading"],
        points="\n".join(f"- {point}" for point in section["points"]) or "- 结合证据梳理关键信息",
        sources=_ref_sources(kept, refs),
        section_words=str(section_words),
    )
    text = (await llm.chat_text(prompt)).strip()
    if _count_refs(text) == 0:
        retry_prompt = prompt + (
            f"\n\n【重要】上一稿没有引用编号。请重写,并确保正文中至少出现一个引用编号,"
            f"且只能使用: {', '.join(f'[{ref}]' for ref in refs)}。"
        )
        text = (await llm.chat_text(retry_prompt)).strip()
    return text


async def _compose(
    llm: LLMClient,
    outline: dict[str, Any],
    drafts: list[dict[str, Any]],
    kept: list[dict[str, Any]],
    target_words: int,
) -> dict[str, Any]:
    sections_md = "\n\n".join(f"## {draft['heading']}\n\n{draft['text']}" for draft in drafts)
    prompt = render_prompt(
        "article_compose",
        article_title=str(outline.get("title") or "研究进展"),
        angle=str(outline.get("angle") or ""),
        target_words=str(target_words),
        sources=_ref_sources(kept, [brief["ref"] for brief in kept]),
        sections_md=sections_md,
    )
    data = await llm.chat_json(prompt, temperature=0.2)
    if not isinstance(data, dict):
        raise LLMError("compose response is not a JSON object")
    return data
