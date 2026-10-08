"""LLM settings, general options, push channels and providers."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import session_dep
from app.models import PushChannel, PushLog
from app.schemas.config import (
    GeneralSettingsIn,
    LLMSettingsIn,
    LLMSettingsOut,
    LLMTestIn,
    LLMTestOut,
)
from app.schemas.content import (
    PushChannelIn,
    PushChannelOut,
    PushChannelUpdate,
    PushLogOut,
)
from app.services.app_settings import (
    GENERAL_KEY,
    LLM_KEY,
    get_general_config,
    get_llm_config,
    get_setting,
    mask_api_key,
    set_setting,
)
from app.services.llm import LLMClient, LLMError
from app.services.push import available_providers, get_provider

router = APIRouter(prefix="/settings", tags=["settings"])
logger = logging.getLogger(__name__)


async def _llm_out(session: AsyncSession) -> LLMSettingsOut:
    config = await get_llm_config(session)
    return LLMSettingsOut(
        enabled=bool(config.get("enabled", True)),
        base_url=str(config.get("base_url") or ""),
        model=str(config.get("model") or ""),
        api_key_masked=mask_api_key(str(config.get("api_key") or "")),
        protocol=str(config.get("protocol") or "openai_chat"),
        timeout_seconds=int(config.get("timeout_seconds") or 180),
        max_concurrency=int(config.get("max_concurrency") or 3),
        translate_enabled=bool(config.get("translate_enabled", True)),
    )


@router.get("/llm", response_model=LLMSettingsOut)
async def get_llm_settings(session: AsyncSession = Depends(session_dep)) -> LLMSettingsOut:
    return await _llm_out(session)


@router.put("/llm", response_model=LLMSettingsOut)
async def update_llm_settings(
    payload: LLMSettingsIn, session: AsyncSession = Depends(session_dep)
) -> LLMSettingsOut:
    stored = dict(await get_setting(session, LLM_KEY, {}) or {})
    stored.update(
        {
            "enabled": payload.enabled,
            "base_url": payload.base_url.strip(),
            "model": payload.model.strip(),
            "protocol": payload.protocol,
            "timeout_seconds": payload.timeout_seconds,
            "max_concurrency": payload.max_concurrency,
            "translate_enabled": payload.translate_enabled,
        }
    )
    if payload.api_key and payload.api_key.strip():
        stored["api_key"] = payload.api_key.strip()
    stored.setdefault("api_key", "")
    await set_setting(session, LLM_KEY, stored)
    await session.commit()
    return await _llm_out(session)


@router.post("/llm/test", response_model=LLMTestOut)
async def test_llm_settings(
    payload: LLMTestIn, session: AsyncSession = Depends(session_dep)
) -> LLMTestOut:
    config = await get_llm_config(session)
    base_url = (payload.base_url or str(config.get("base_url") or "")).strip()
    model = (payload.model or str(config.get("model") or "")).strip()
    api_key = (payload.api_key or str(config.get("api_key") or "")).strip()
    if not (base_url and model and api_key):
        return LLMTestOut(ok=False, message="base_url / model / api_key 不完整")
    client = LLMClient(base_url=base_url, api_key=api_key, model=model, timeout=60)
    try:
        reply, latency = await client.test()
    except LLMError as exc:
        return LLMTestOut(ok=False, message=str(exc)[:300])
    except Exception as exc:  # noqa: BLE001 - a test button must never 500
        logger.warning("llm test failed", exc_info=exc)
        return LLMTestOut(ok=False, message=f"测试失败: {exc}"[:300])
    snippet = reply.strip()[:50] or "(模型返回空内容,推理模型可忽略)"
    return LLMTestOut(ok=True, message=f"连接成功,模型回复: {snippet}", latency_ms=latency)


@router.get("/general")
async def get_general(session: AsyncSession = Depends(session_dep)) -> dict:
    return await get_general_config(session)


@router.put("/general")
async def update_general(
    payload: GeneralSettingsIn, session: AsyncSession = Depends(session_dep)
) -> dict:
    stored = dict(await get_setting(session, GENERAL_KEY, {}) or {})
    stored.update(payload.model_dump(exclude_none=True))
    await set_setting(session, GENERAL_KEY, stored)
    await session.commit()
    return await get_general_config(session)


@router.get("/push-logs", response_model=list[PushLogOut])
async def list_push_logs(
    target_kind: str | None = None,
    target_id: int | None = None,
    channel_id: int | None = None,
    limit: int = 20,
    session: AsyncSession = Depends(session_dep),
) -> list[PushLogOut]:
    stmt = select(PushLog).order_by(PushLog.created_at.desc(), PushLog.id.desc())
    if target_kind:
        stmt = stmt.where(PushLog.target_kind == target_kind)
    if target_id is not None:
        stmt = stmt.where(PushLog.target_id == int(target_id))
    if channel_id is not None:
        stmt = stmt.where(PushLog.channel_id == int(channel_id))
    rows = list(await session.scalars(stmt.limit(min(100, max(1, int(limit))))))
    return [PushLogOut.model_validate(row) for row in rows]


@router.get("/providers")
async def list_providers() -> list[dict[str, str]]:
    return available_providers()


@router.get("/push-channels", response_model=list[PushChannelOut])
async def list_push_channels(
    session: AsyncSession = Depends(session_dep),
) -> list[PushChannelOut]:
    rows = list(await session.scalars(select(PushChannel).order_by(PushChannel.id)))
    return [PushChannelOut.model_validate(row) for row in rows]


@router.post("/push-channels", response_model=PushChannelOut, status_code=201)
async def create_push_channel(
    payload: PushChannelIn, session: AsyncSession = Depends(session_dep)
) -> PushChannelOut:
    channel = PushChannel(
        name=payload.name.strip(),
        kind=payload.kind,
        config=payload.config,
        enabled=payload.enabled,
    )
    session.add(channel)
    await session.commit()
    await session.refresh(channel)
    return PushChannelOut.model_validate(channel)


@router.put("/push-channels/{channel_id}", response_model=PushChannelOut)
async def update_push_channel(
    channel_id: int,
    payload: PushChannelUpdate,
    session: AsyncSession = Depends(session_dep),
) -> PushChannelOut:
    channel = await session.get(PushChannel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="推送渠道不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(channel, field, value)
    await session.commit()
    await session.refresh(channel)
    return PushChannelOut.model_validate(channel)


@router.delete("/push-channels/{channel_id}", status_code=204)
async def delete_push_channel(
    channel_id: int, session: AsyncSession = Depends(session_dep)
) -> None:
    channel = await session.get(PushChannel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="推送渠道不存在")
    await session.delete(channel)
    await session.commit()


@router.post("/push-channels/{channel_id}/test")
async def test_push_channel(channel_id: int, session: AsyncSession = Depends(session_dep)) -> dict:
    channel = await session.get(PushChannel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="推送渠道不存在")
    provider = get_provider(channel.kind)
    result = await provider.send(
        digest={
            "title": "research-agent 测试消息",
            "lead": "",
            "content_md": "这是一条来自 research-agent 的测试消息。",
            "highlights": [],
        },
        config=channel.config or {},
    )
    return {"ok": result.ok, "message": result.response or result.error}
