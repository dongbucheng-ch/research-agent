"""Push registry: send a digest/article through a configured channel and record a log."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Article, Digest, DigestItem, Item, PushChannel, PushLog
from app.services.push.base import PushError, PushProvider, PushResult
from app.services.push.export import ExportPushProvider
from app.services.push.payload import compose_payload, normalize_tags, rank_tags
from app.services.push.webhook import WebhookPushProvider

_PROVIDERS: dict[str, PushProvider] = {
    provider.kind: provider for provider in (WebhookPushProvider(), ExportPushProvider())
}

TARGET_KINDS = ("digest", "article")


def available_providers() -> list[dict[str, str]]:
    return [{"kind": p.kind, "label": p.label} for p in _PROVIDERS.values()]


def get_provider(kind: str) -> PushProvider:
    provider = _PROVIDERS.get(kind)
    if provider is None:
        raise PushError(f"unknown push provider: {kind}")
    return provider


async def _material_tags(session: AsyncSession, target_kind: str, target: Any) -> list[str]:
    """标签按素材确定:日报取入选素材的标签频次,文章取自身关键词。"""
    if target_kind == "article":
        return normalize_tags(target.keywords or [])
    rows = await session.scalars(
        select(Item.tags)
        .join(DigestItem, DigestItem.item_id == Item.id)
        .where(DigestItem.digest_id == target.id)
    )
    return rank_tags(tags or [] for tags in rows)


def _target_fields(target_kind: str, target: Any) -> dict[str, Any]:
    """产出物自身的推送字段;文章的 lead 取 topic、标签素材取 keywords。"""
    if target_kind == "digest":
        return {
            "title": target.title,
            "lead": target.lead,
            "content_md": target.content_md,
            "highlights": list(target.highlights or []),
        }
    return {
        "title": target.title,
        "lead": target.topic,
        "content_md": target.content_md,
        "highlights": list(target.keywords or []),
    }


async def _build_payload(
    session: AsyncSession,
    *,
    target_kind: str,
    target: Any,
    channel: PushChannel,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields = _target_fields(target_kind, target)
    return compose_payload(
        target_id=target.id,
        title=fields["title"],
        lead=fields["lead"],
        content_md=fields["content_md"],
        highlights=fields["highlights"],
        material_tags=await _material_tags(session, target_kind, target),
        overrides=overrides,
        channel_config=channel.config or {},
    )


async def send_target(
    session: AsyncSession,
    *,
    target_kind: str,
    target_id: int,
    channel: PushChannel,
    overrides: dict[str, Any] | None = None,
) -> PushLog:
    """推送任一产出物(日报 / 完整文章),并把结果写入 push_logs。

    `overrides` 支持 title / source / author / tags(推送时手填;留空走渠道配置或默认)。
    """
    if target_kind not in TARGET_KINDS:
        raise PushError(f"不支持的推送目标: {target_kind}")
    model = Digest if target_kind == "digest" else Article
    target = await session.get(model, int(target_id))
    if target is None:
        raise PushError("推送目标不存在")
    provider = get_provider(channel.kind)
    payload = await _build_payload(
        session, target_kind=target_kind, target=target, channel=channel, overrides=overrides
    )
    result: PushResult
    try:
        result = await provider.send(digest=payload, config=channel.config or {})
    except Exception as exc:  # noqa: BLE001 - record any provider failure
        result = PushResult(ok=False, error=str(exc))
    log = PushLog(
        channel_id=channel.id,
        digest_id=target.id if target_kind == "digest" else None,
        target_kind=target_kind,
        target_id=target.id,
        status="success" if result.ok else "failed",
        request={
            "title": payload["title"],
            "source": payload["source"],
            "author": payload["author"],
            "tags": payload["tags"],
        },
        response=result.response,
        error=result.error,
    )
    session.add(log)
    await session.flush()
    return log


async def send_digest(
    session: AsyncSession,
    *,
    digest: Digest,
    channel: PushChannel,
) -> PushLog:
    """兼容旧调用:等价于 send_target(target_kind='digest')。"""
    return await send_target(
        session, target_kind="digest", target_id=digest.id, channel=channel
    )


__all__ = [
    "PushProvider",
    "PushResult",
    "PushError",
    "TARGET_KINDS",
    "available_providers",
    "get_provider",
    "send_target",
    "send_digest",
]
