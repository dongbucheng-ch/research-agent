"""HuggingFace Daily Papers 采集器(engine=`news`, preset=`hf_papers`,免鉴权 JSON API)。

来源 `https://huggingface.co/api/daily_papers`:社区每日投票精选的 arXiv 论文,
带 upvotes/numComments 等热度指标。与 `arxiv` 采集器不同,它**不按关键词检索**,
拉取当日精选后由三维打分按研究方向过滤(方向不匹配会自然落在门槛之下)。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.collectors.base import (
    BaseCollector,
    CollectContext,
    RawItem,
    describe_error,
    get_with_retries,
    make_client,
)
from app.pipeline.text import truncate

if TYPE_CHECKING:
    from app.models import Source

logger = logging.getLogger(__name__)

HF_DAILY_API = "https://huggingface.co/api/daily_papers"
HF_PAPER_URL = "https://huggingface.co/papers/{paper_id}"


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def daily_paper_to_item(row: Any) -> RawItem | None:
    """把 HF daily_papers 的一条记录转成 RawItem;字段不全时返回 None。"""
    if not isinstance(row, dict):
        return None
    paper = row.get("paper") if isinstance(row.get("paper"), dict) else {}
    paper_id = str(paper.get("id") or "").strip()
    title = " ".join(str(paper.get("title") or row.get("title") or "").split())
    if not paper_id or not title:
        return None
    summary = " ".join(str(paper.get("summary") or row.get("summary") or "").split())
    authors = paper.get("authors") if isinstance(paper.get("authors"), list) else []
    author = ", ".join(
        str(a.get("name")) for a in authors[:3] if isinstance(a, dict) and a.get("name")
    )
    published = _parse_dt(
        row.get("publishedAt") or paper.get("submittedOnDailyAt") or paper.get("publishedAt")
    )
    metrics: dict[str, Any] = {}
    try:
        metrics["upvotes"] = int(paper.get("upvotes") or 0)
    except (TypeError, ValueError):
        metrics["upvotes"] = 0
    try:
        metrics["comments"] = int(row.get("numComments") or 0)
    except (TypeError, ValueError):
        metrics["comments"] = 0
    return RawItem(
        url=HF_PAPER_URL.format(paper_id=paper_id),
        title=truncate(title, 400),
        published_at=published,
        author=author or None,
        raw_text=truncate(summary, 6000) or None,
        external_id=paper_id,
        content_type_hint="paper",
        metrics=metrics,
        extra={
            "hf_paper_id": paper_id,
            "github_repo": paper.get("githubRepo"),
            "organization": paper.get("organization"),
        },
    )


class HFDailyPapersCollector(BaseCollector):
    channel = "hf_papers"

    async def collect(self, source: Source, ctx: CollectContext) -> list[RawItem]:
        limit = max(1, min(ctx.max_items, 50))
        try:
            async with make_client(ctx.timeout) as client:
                resp = await get_with_retries(client, HF_DAILY_API, params={"limit": str(limit)})
            rows = resp.json()
        except Exception as exc:  # noqa: BLE001 - 单源失败不拖垮采集
            logger.warning("HF daily papers failed for %s: %s", source.name, describe_error(exc))
            return []
        if not isinstance(rows, list):
            logger.warning("HF daily papers unexpected payload for %s", source.name)
            return []
        items: list[RawItem] = []
        for row in rows:
            item = daily_paper_to_item(row)
            if item is not None:
                items.append(item)
        return items
