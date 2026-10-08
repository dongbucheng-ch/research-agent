"""Generic webhook delivery: POST JSON to a configured URL (works with most IM bots)."""

from __future__ import annotations

from typing import Any

import httpx

from app.services.push.base import PushProvider, PushResult


class WebhookPushProvider(PushProvider):
    kind = "webhook"
    label = "通用 Webhook"

    async def send(self, *, digest: dict[str, Any], config: dict[str, Any]) -> PushResult:
        url = str(config.get("url") or "").strip()
        if not url:
            return PushResult(ok=False, error="webhook url 未配置")
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            **(config.get("headers") or {}),
        }
        token = str(config.get("token") or "").strip()
        if token:
            headers.setdefault("Authorization", f"Bearer {token}")
        payload = {
            "title": digest.get("title") or "",
            "lead": digest.get("lead") or "",
            "content": digest.get("content_md") or "",
            "highlights": digest.get("highlights") or [],
        }
        # 模板占位符可引用产出物全量字段(含 $tags/$source/$author,另有 $id/$content_md)。
        fields = {
            "id": digest.get("id") or "",
            **payload,
            "content_md": payload["content"],
            "tags": list(digest.get("tags") or []),
            "source": digest.get("source") or "",
            "author": digest.get("author") or "",
        }
        template = config.get("payload_template")
        if isinstance(template, dict) and template:
            payload = {key: self._render(value, fields) for key, value in template.items()}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            return PushResult(ok=False, error=f"请求失败: {exc}")
        if resp.status_code >= 400:
            return PushResult(ok=False, error=f"HTTP {resp.status_code}: {resp.text[:300]}")
        return PushResult(ok=True, response=resp.text[:1000])

    @staticmethod
    def _render(value: Any, payload: dict[str, Any]) -> Any:
        if isinstance(value, str) and value.startswith("$"):
            return payload.get(value[1:], "")
        if isinstance(value, dict):
            return {k: WebhookPushProvider._render(v, payload) for k, v in value.items()}
        if isinstance(value, list):
            return [WebhookPushProvider._render(v, payload) for v in value]
        return value
