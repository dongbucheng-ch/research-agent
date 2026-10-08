"""采集 HTTP 助手:重试与异常文案(纯 fake,不联网)。"""

import httpx
import pytest

from app.collectors.base import describe_error, get_with_retries


def _request() -> httpx.Request:
    return httpx.Request("GET", "https://example.com/feed")


class FakeClient:
    """按脚本返回响应或抛异常;脚本项为 Exception 时抛出。"""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.calls = 0

    async def get(
        self, url: str, params: dict | None = None, headers: dict | None = None
    ) -> httpx.Response:
        self.calls += 1
        action = self._script.pop(0)
        if isinstance(action, Exception):
            raise action
        return httpx.Response(action, request=_request())


def test_describe_error_keeps_type_name_for_empty_message():
    assert describe_error(httpx.ConnectError("")) == "ConnectError"
    assert describe_error(httpx.ConnectError("SSL: EOF")) == "ConnectError: SSL: EOF"
    assert describe_error(ValueError("bad")) == "ValueError: bad"


async def test_get_with_retries_retries_transport_errors():
    client = FakeClient([httpx.ConnectError(""), httpx.ReadTimeout("slow"), 200])
    response = await get_with_retries(
        client, "https://example.com/feed", attempts=3, backoff_seconds=0
    )
    assert response.status_code == 200
    assert client.calls == 3


async def test_get_with_retries_gives_up_and_raises_last_error():
    client = FakeClient([httpx.ConnectError(""), httpx.ConnectError("")])
    with pytest.raises(httpx.ConnectError):
        await get_with_retries(client, "https://example.com/feed", attempts=2, backoff_seconds=0)
    assert client.calls == 2


async def test_get_with_retries_does_not_retry_http_status():
    client = FakeClient([404, 200])
    with pytest.raises(httpx.HTTPStatusError):
        await get_with_retries(client, "https://example.com/feed", attempts=3, backoff_seconds=0)
    assert client.calls == 1
