"""Persistence helpers for app settings (LLM config, general options)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Setting

LLM_KEY = "llm"
GENERAL_KEY = "general"

# 采集流水线硬约束(与 schemas 保持一致,防止历史存量值绕过)。
LOOKBACK_HOURS_MAX = 48
FALLBACK_LOOKBACK_HOURS = 24
ENRICH_MAX_ITEMS_DEFAULT = 100
ENRICH_MAX_ITEMS_LIMIT = 500

DEFAULT_LLM: dict[str, Any] = {
    "enabled": True,
    "base_url": "",
    "model": "",
    "api_key": "",
    "protocol": "openai_chat",
    "timeout_seconds": 180,
    "max_concurrency": 3,
    "translate_enabled": True,
}


async def get_setting(session: AsyncSession, key: str, default: Any = None) -> Any:
    row = await session.get(Setting, key)
    if row is None:
        return default
    return row.value


async def set_setting(session: AsyncSession, key: str, value: Any) -> None:
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    await session.flush()


def mask_api_key(key: str | None) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 10:
        return "*" * len(key)
    return f"{key[:6]}{'*' * 8}{key[-4:]}"


async def get_llm_config(session: AsyncSession) -> dict[str, Any]:
    """Return the effective LLM config, with environment variables as override."""
    stored = await get_setting(session, LLM_KEY, {}) or {}
    config = {**DEFAULT_LLM, **stored}
    env = get_settings()
    if env.llm_base_url:
        config["base_url"] = env.llm_base_url
    if env.llm_model:
        config["model"] = env.llm_model
    if env.llm_api_key:
        config["api_key"] = env.llm_api_key
    return config


def bound_int(
    raw: Any,
    *,
    default: int,
    low: int,
    high: int,
    zero_as_default: bool = False,
) -> int:
    """把配置值收敛到 [low, high];非法值回退 default(历史 0 = 不限按默认值处理)。"""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if zero_as_default and value <= 0:
        return max(low, min(high, default))
    return max(low, min(high, value))


async def get_general_config(session: AsyncSession) -> dict[str, Any]:
    stored = await get_setting(session, GENERAL_KEY, {}) or {}
    env = get_settings()
    config = {
        "fetch_lookback_hours": env.fetch_lookback_hours,
        "fetch_max_concurrency": env.fetch_max_concurrency,
        "enrich_batch_size": env.enrich_batch_size,
        "enrich_max_items": env.enrich_max_items,
        **stored,
    }
    config["fetch_lookback_hours"] = bound_int(
        config.get("fetch_lookback_hours"),
        default=FALLBACK_LOOKBACK_HOURS,
        low=1,
        high=LOOKBACK_HOURS_MAX,
    )
    config["enrich_max_items"] = bound_int(
        config.get("enrich_max_items"),
        default=ENRICH_MAX_ITEMS_DEFAULT,
        low=1,
        high=ENRICH_MAX_ITEMS_LIMIT,
        zero_as_default=True,
    )
    return config
