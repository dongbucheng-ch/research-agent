"""Bing News 检索采集器(免鉴权,engine=`news`,preset=`bing_news`)。

自研:直接调用公开的 Bing News RSS 检索端点
`https://www.bing.com/news/search?q=<关键词>&format=RSS`。作为 Google News 的
备用检索入口(实测国内网络下 news.google.com 常连不通,而 Bing 可稳定返回中文结果)。

踩过的坑,写在这里避免回归:

- 请求里**不能带 `mkt=` 参数**,否则端点会 302 回 Bing 首页(HTML 而不是 RSS);
  语言用 `setlang=zh-hans` 控制即可。
- 时间窗用 `qft=interval="N"`(N 为天数,向上取整,不传则 Bing 按默认相关度给结果)。
- `<link>` 是 `apiclick.aspx?...&url=<百分号编码真实地址>` 跳转链接,**必须解出真实
  URL**,否则所有条目都会以 bing.com 域参与 canonical 去重,别人的新闻会被误判为重复。
- 条目没有 `guid`,用解码后的真实 URL 当 `external_id`;缺标题/链接/时间则跳过。
"""

from __future__ import annotations

import logging
import math
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

import feedparser

from app.collectors.base import (
    BaseCollector,
    CollectContext,
    RawItem,
    get_with_retries,
    make_client,
)
from app.collectors.feedutil import entry_text, parse_entry_date
from app.pipeline.text import truncate

if TYPE_CHECKING:
    from app.models import Source

logger = logging.getLogger(__name__)

MAX_QUERY_KEYWORDS = 12

MAX_INTERVAL_DAYS = 30


def bing_query(keywords: list[str], limit: int = MAX_QUERY_KEYWORDS) -> str:
    """关键词拼成 Bing 检索表达式。

    注意**不能加引号**:实测 `q="生物科技"` 会返回 0 条的合法 RSS(短语检索在新闻索引
    里命中不到),而裸词 `q=生物科技` 有 9 条。词间用 OR 连接。
    """
    words = [str(word).strip().replace('"', " ") for word in keywords if str(word).strip()]
    return " OR ".join(" ".join(word.split()) for word in words[:limit])


_MSN_SUFFIX_RE = re.compile(r"\s+on\s+MSN$", re.IGNORECASE)


def decode_bing_link(link: str) -> str:
    """把 Bing `apiclick.aspx` 跳转链接解成真实原文地址;非跳转链接原样返回。"""
    raw = str(link or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if "bing.com" not in parts.netloc.lower():
        return raw
    for chunk in parts.query.split("&"):
        key, _, value = chunk.partition("=")
        if key.lower() != "url" or not value:
            continue
        # 只做一次 unquote:原文地址里的 %25xx 要保留下来给下游请求。
        target = unquote(value).strip()
        if target.lower().startswith(("http://", "https://")):
            return target
    return raw


def interval_days(lookback_hours: int) -> int:
    """Bing 的 `qft=interval` 只支持天粒度,向上取整并夹在 1..30。"""
    return max(1, min(MAX_INTERVAL_DAYS, math.ceil(max(1, int(lookback_hours)) / 24)))


def publisher_of(entry: Any) -> str | None:
    """发布来源,取 `News:Source`;剥掉 MSN 聚合后缀。"""
    name = entry.get("news_source")
    if isinstance(name, dict):
        name = name.get("title")
    text = str(name or "").strip()
    if not text:
        return None
    return _MSN_SUFFIX_RE.sub("", text).strip() or None


def entry_to_item(entry: Any) -> RawItem | None:
    """把一条 Bing News 条目映射为 RawItem;缺标题/链接/时间则跳过。"""
    title = " ".join(str(entry.get("title") or "").split())
    link = decode_bing_link(str(entry.get("link") or ""))
    published = parse_entry_date(entry)
    if not title or not link or published is None:
        return None
    publisher = publisher_of(entry)
    return RawItem(
        url=link,
        title=truncate(title, 500),
        published_at=published,
        author=publisher,
        raw_text=entry_text(entry),
        external_id=link,
        extra={"publisher": publisher, "bing_link": str(entry.get("link") or "")},
    )


class BingNewsCollector(BaseCollector):
    channel = "bing_news"
    base_url = "https://www.bing.com/news/search"

    async def collect(self, source: Source, ctx: CollectContext) -> list[RawItem]:
        config = source.config if isinstance(source.config, dict) else {}
        query = str(config.get("query") or "").strip() or bing_query(ctx.keywords)
        if not query:
            return []
        interval = config.get("interval_days")
        days = (
            int(interval)
            if isinstance(interval, (int, float))
            else interval_days(ctx.lookback_hours)
        )
        params = {
            "q": query,
            "format": "RSS",
            "setlang": str(config.get("setlang") or "zh-hans"),
            "qft": f'interval="{max(1, min(MAX_INTERVAL_DAYS, days))}"',
        }
        async with make_client(ctx.timeout) as client:
            response = await get_with_retries(client, self.base_url, params=params)

        feed = feedparser.parse(response.content)
        if feed.bozo and not feed.entries:
            return []
        if not feed.entries:
            logger.info("Bing News 无结果: q=%s", query)
        items: list[RawItem] = []
        for entry in feed.entries[: max(1, min(ctx.max_items, 50))]:
            item = entry_to_item(entry)
            if item is not None:
                items.append(item)
        return items
