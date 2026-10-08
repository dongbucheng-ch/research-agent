"""Webhook 推送:payload_template 占位符渲染(打桩 httpx,不联网)。"""

from __future__ import annotations

from typing import Any

from app.services.push.webhook import WebhookPushProvider


class _FakeResponse:
    status_code = 200
    text = '{"ok":true}'


class _FakeClient:
    captured: dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(
        self, url: str, *, json: dict[str, Any], headers: dict[str, str]
    ) -> _FakeResponse:
        _FakeClient.captured = {"url": url, "json": json, "headers": headers}
        return _FakeResponse()


def _digest() -> dict[str, Any]:
    return {
        "id": 21,
        "title": "科技与产业研讯日报（2026-10-08）：OpenAI 发布 GPT-6",
        "lead": "今日导语",
        "content_md": "# 正文",
        "highlights": ["h1"],
        "tags": ["AI", "大模型"],
        "source": "sribd_forum_ai",
        "author": "研讯编辑部",
    }


async def test_template_renders_tags_source_and_author(monkeypatch):
    monkeypatch.setattr("app.services.push.webhook.httpx.AsyncClient", _FakeClient)
    config = {
        "url": "https://club.example/api/integrations/ai-news",
        "token": "test-token",
        "payload_template": {
            "sourceId": "$title",
            "source": "$source",
            "title": "$title",
            "summary": "$lead",
            "content": "$content",
            "tags": "$tags",
        },
    }

    result = await WebhookPushProvider().send(digest=_digest(), config=config)

    assert result.ok
    assert _FakeClient.captured["json"] == {
        "sourceId": "科技与产业研讯日报（2026-10-08）：OpenAI 发布 GPT-6",
        "source": "sribd_forum_ai",
        "title": "科技与产业研讯日报（2026-10-08）：OpenAI 发布 GPT-6",
        "summary": "今日导语",
        "content": "# 正文",
        "tags": ["AI", "大模型"],
    }
    assert _FakeClient.captured["headers"]["Authorization"] == "Bearer test-token"


async def test_template_keeps_literals_and_renders_missing_fields_empty(monkeypatch):
    monkeypatch.setattr("app.services.push.webhook.httpx.AsyncClient", _FakeClient)
    digest = {"title": "t", "content_md": "c"}
    config = {
        "url": "https://club.example/hook",
        "payload_template": {"title": "$title", "source": "research-agent", "tags": ["AI"]},
    }

    result = await WebhookPushProvider().send(digest=digest, config=config)

    assert result.ok
    assert _FakeClient.captured["json"] == {
        "title": "t",
        "source": "research-agent",
        "tags": ["AI"],
    }


async def test_without_template_keeps_default_payload(monkeypatch):
    monkeypatch.setattr("app.services.push.webhook.httpx.AsyncClient", _FakeClient)
    digest = {
        "title": "t",
        "lead": "l",
        "content_md": "c",
        "highlights": [1],
        "tags": ["x"],
    }

    result = await WebhookPushProvider().send(digest=digest, config={"url": "https://x.test"})

    assert result.ok
    assert _FakeClient.captured["json"] == {
        "title": "t",
        "lead": "l",
        "content": "c",
        "highlights": [1],
    }
