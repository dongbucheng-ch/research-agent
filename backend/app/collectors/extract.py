"""Best-effort main-text extraction from a web page.

优先用 trafilatura(Apache-2.0,见 THIRD_PARTY_NOTICES.md)做正文抽取,
不可用或抽取为空时回退到 BeautifulSoup 启发式(去 script/style/nav,取 article/main/body)。
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.pipeline.text import strip_html, truncate

_DROP_TAGS = ("script", "style", "noscript", "nav", "footer", "header", "aside", "form")


def _trafilatura_text(html: str, url: str | None) -> str:
    try:
        import trafilatura
    except ImportError:  # 依赖缺失时静默回退
        return ""
    try:
        extracted = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
        )
    except Exception:  # noqa: BLE001 - 抽取器内部异常不应中断采集
        return ""
    return (extracted or "").strip()


def _soup_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    node = soup.find("article") or soup.find("main") or soup.body or soup
    return strip_html(str(node))


def extract_main_text(html: str, *, limit: int = 8000, url: str | None = None) -> str:
    if not html:
        return ""
    text = _trafilatura_text(html, url) or _soup_text(html)
    return truncate(text, limit)
