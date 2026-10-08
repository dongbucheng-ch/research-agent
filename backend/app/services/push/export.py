"""Export provider: delivery handled by the caller (download / copy to clipboard)."""

from __future__ import annotations

from typing import Any

from app.services.push.base import PushProvider, PushResult


class ExportPushProvider(PushProvider):
    kind = "export"
    label = "导出/下载"

    async def send(self, *, digest: dict[str, Any], config: dict[str, Any]) -> PushResult:
        title = str(digest.get("title") or "digest")
        return PushResult(ok=True, response=f"已生成导出内容: {title}")
