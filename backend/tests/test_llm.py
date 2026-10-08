"""LLM client: base URL normalisation and non-JSON upstream responses."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.services.llm import LLMClient, LLMError, normalize_base_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://api.openai.com", "https://api.openai.com/v1"),
        ("https://api.openai.com/", "https://api.openai.com/v1"),
        ("  https://api.openai.com/v1  ", "https://api.openai.com/v1"),
        ("https://api.example.com/v1/chat/completions", "https://api.example.com/v1"),
        ("https://api-aitest.sribd.cn", "https://api-aitest.sribd.cn/v1"),
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000/v1"),
        ("https://gateway.internal/openai", "https://gateway.internal/openai"),
        ("", ""),
    ],
)
def test_normalize_base_url(raw: str, expected: str):
    assert normalize_base_url(raw) == expected


class _HtmlHandler(BaseHTTPRequestHandler):
    """Mimics a gateway that answers unknown paths with an SPA page (HTTP 200)."""

    def do_POST(self):  # noqa: N802 - http.server API
        body = b"<!doctype html><html><body>SPA</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # noqa: D102 - silence test server
        pass


@pytest.fixture
def html_endpoint(monkeypatch):
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HtmlHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()


async def test_chat_reports_non_json_body_as_llm_error(html_endpoint: str):
    client = LLMClient(base_url=html_endpoint, api_key="k", model="m", timeout=5)
    with pytest.raises(LLMError) as excinfo:
        await client.chat([{"role": "user", "content": "hi"}])
    message = str(excinfo.value)
    assert "非 JSON" in message
    assert "doctype" in message
