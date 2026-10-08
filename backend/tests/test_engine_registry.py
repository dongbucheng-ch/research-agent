"""三引擎注册表 + 采集器纯函数(不联网)。"""

from datetime import UTC, datetime

from app.collectors import (
    CHANNEL_ROUTES,
    ENGINES,
    PRESETS,
    collector_for,
    engine_of,
    object_type_of,
    route_of,
)
from app.collectors.bing_news import (
    bing_query,
    decode_bing_link,
    interval_days,
    publisher_of,
)
from app.collectors.bing_news import (
    entry_to_item as bing_entry_to_item,
)
from app.collectors.github_search import (
    github_search_query,
    is_searchable,
    model_to_item,
    repo_to_item,
)
from app.collectors.google_news import entry_to_item, keywords_to_query, time_operator
from app.collectors.hackernews import matches_keywords, story_to_item


class FakeSource:
    def __init__(self, channel: str, config: dict | None = None) -> None:
        self.channel = channel
        self.config = config or {}
        self.name = channel


def test_only_three_engines():
    assert ENGINES == ("rss", "news", "github")
    assert set(PRESETS) == set(ENGINES)


def test_every_route_has_a_collector():
    for channel, route in CHANNEL_ROUTES.items():
        engine, preset = route
        assert engine in ENGINES, channel
        assert preset in PRESETS[engine], channel
        assert collector_for(FakeSource(channel)) is not None, channel


def test_legacy_channels_map_to_engines():
    assert route_of(FakeSource("arxiv")) == ("news", "arxiv")
    assert route_of(FakeSource("github_trending")) == ("github", "trending")
    assert route_of(FakeSource("rss")) == ("rss", "feed")
    assert route_of(FakeSource("bing_news")) == ("news", "bing_news")
    assert route_of(FakeSource("nope")) is None
    assert collector_for(FakeSource("nope")) is None


def test_config_can_override_route():
    source = FakeSource("rss", {"engine": "github", "preset": "repo"})
    assert route_of(source) == ("github", "repo")
    assert engine_of(source) == "github"
    # 只给 engine 时用该引擎的默认 preset
    assert route_of(FakeSource("rss", {"engine": "news"})) == ("news", "google_news")


def test_object_type_follows_preset_and_can_override():
    assert object_type_of(FakeSource("arxiv")) == "paper"
    assert object_type_of(FakeSource("google_news")) == "news"
    assert object_type_of(FakeSource("bing_news")) == "news"
    assert object_type_of(FakeSource("hackernews")) == "community"
    assert object_type_of(FakeSource("github")) == "repo"
    assert object_type_of(FakeSource("skill")) == "skill"
    assert object_type_of(FakeSource("model")) == "model"
    assert object_type_of(FakeSource("rss", {"object_type": "paper"})) == "paper"


def test_google_news_query_building():
    assert keywords_to_query(["agent", "具身智能", " "]) == '"agent" OR "具身智能"'
    assert keywords_to_query(['a"b']) == '"a b"'
    assert time_operator(24) == "when:24h"
    assert time_operator(240, now=datetime(2026, 9, 30, 12, tzinfo=UTC)) == "after:2026-09-20"


def test_google_news_entry_mapping_skips_incomplete():
    good = {
        "title": "标题",
        "link": "https://news.example/a",
        "published_parsed": (2026, 9, 30, 3, 0, 0, 0, 0, 0),
        "source": {"title": "某媒体"},
    }
    item = entry_to_item(good)
    assert item is not None
    assert item.published_at == datetime(2026, 9, 30, 3, 0, tzinfo=UTC)
    assert item.author == "某媒体"
    assert entry_to_item({"title": "无链接"}) is None
    assert entry_to_item({**good, "published_parsed": None, "published": "bad"}) is None


def test_github_search_query_parts():
    query = github_search_query(
        keywords=["embodied agent", "vlm"],
        topic="claude-skills",
        min_stars=50,
        pushed_after=datetime(2026, 6, 1, tzinfo=UTC),
    )
    assert '"embodied agent" OR vlm in:name,description,topics' in query
    assert "readme" not in query
    assert "topic:claude-skills" in query
    assert "stars:>=50" in query
    assert "pushed:>=2026-06-01" in query
    assert github_search_query(keywords=[]) == ""
    # 中文词会让 GitHub 返回跑偏结果:不进检索式;只剩中文时干脆不查
    assert (
        github_search_query(keywords=["生物科技", "biotech"])
        == "biotech in:name,description,topics"
    )
    assert github_search_query(keywords=["生物科技"], min_stars=10) == ""
    assert is_searchable("biotech") and not is_searchable("生物科技")


def test_repo_and_model_mapping():
    repo = {
        "id": 1,
        "full_name": "owner/repo",
        "html_url": "https://github.com/owner/repo",
        "description": "desc",
        "language": "Python",
        "stargazers_count": 1200,
        "forks_count": 30,
        "topics": ["agents"],
        "pushed_at": "2026-09-29T10:00:00Z",
        "license": {"spdx_id": "MIT"},
        "owner": {"login": "owner"},
    }
    item = repo_to_item(repo, "repo")
    assert item is not None
    assert item.content_type_hint == "repo"
    assert item.metrics["stars"] == 1200
    assert item.published_at == datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    assert "Stars: 1200" in (item.raw_text or "")
    assert repo_to_item({"id": 2}, "repo") is None

    model = {
        "id": "meta/agent-model",
        "downloads": 5000,
        "likes": 42,
        "tags": ["text-generation"],
        "createdAt": "2026-09-01T00:00:00.000Z",
    }
    model_item = model_to_item(model)
    assert model_item is not None
    assert model_item.url == "https://huggingface.co/meta/agent-model"
    assert model_item.content_type_hint == "model"
    assert model_item.metrics["downloads"] == 5000


def test_hackernews_keyword_filter_and_mapping():
    assert matches_keywords({"title": "LLM agents"}, ["agent"])
    assert not matches_keywords({"title": "rust gui"}, ["agent"])
    assert matches_keywords({"title": "anything"}, [])

    item = story_to_item(
        {
            "id": 42,
            "title": "Show HN: agents",
            "score": 120,
            "descendants": 18,
            "time": 1790737332,
            "by": "someone",
        }
    )
    assert item is not None
    assert item.content_type_hint == "community"
    assert item.metrics == {"score": 120, "comments": 18}
    assert item.url == "https://news.ycombinator.com/item?id=42"


def test_bing_news_query_stays_unquoted():
    # 实测带引号会让 Bing 返回 0 条的合法 RSS,所以这里必须是不加引号的裸词
    assert bing_query(["生物科技"]) == "生物科技"
    assert bing_query([" 合成生物 ", "基因编辑", " "]) == "合成生物 OR 基因编辑"
    assert bing_query(['a"b']) == "a b"
    assert bing_query([]) == ""


def test_bing_news_link_decode_and_interval():
    apiclick = (
        "http://www.bing.com/news/apiclick.aspx?ref=FexRss&aid=&tid=abc"
        "&url=https%3a%2f%2ffinance.eastmoney.com%2fa%2f202609303887519888.html&c=1&mkt=en-us"
    )
    assert decode_bing_link(apiclick) == "https://finance.eastmoney.com/a/202609303887519888.html"
    # 原文地址自身带百分号编码时只 unquote 一次,保留内层编码
    nested = (
        "http://www.bing.com/news/apiclick.aspx?url="
        "https%3a%2f%2fwww.msn.cn%2fzh-cn%2fmoney%2fai%25E7%2594%259F%25E5%2591%25BD.html"
    )
    assert decode_bing_link(nested) == "https://www.msn.cn/zh-cn/money/ai%E7%94%9F%E5%91%BD.html"
    # 非跳转链接与缺参数链接原样返回
    assert decode_bing_link("https://example.com/a") == "https://example.com/a"
    assert decode_bing_link("http://www.bing.com/news/apiclick.aspx?tid=1").startswith(
        "http://www.bing.com/"
    )
    assert decode_bing_link("") == ""

    assert interval_days(1) == 1
    assert interval_days(24) == 1
    assert interval_days(48) == 2
    assert interval_days(168) == 7
    assert interval_days(9999) == 30


def test_bing_news_entry_mapping_skips_incomplete():
    entry = {
        "title": "  美股生物科技板块盘初涨跌不一 ",
        "link": (
            "http://www.bing.com/news/apiclick.aspx?tid=abc"
            "&url=https%3a%2f%2fnews.ifeng.com%2fc%2f8wp3r9MQT1j&c=1"
        ),
        "published_parsed": (2026, 9, 29, 14, 36, 0, 0, 0, 0),
        "summary": "<p>每经AI快讯,9月29日…</p>",
        "news_source": "凤凰网资讯频道",
    }
    item = bing_entry_to_item(entry)
    assert item is not None
    assert item.url == "https://news.ifeng.com/c/8wp3r9MQT1j"
    assert item.title == "美股生物科技板块盘初涨跌不一"
    assert item.published_at == datetime(2026, 9, 29, 14, 36, tzinfo=UTC)
    assert item.author == "凤凰网资讯频道"
    assert item.raw_text == "每经AI快讯,9月29日…"
    assert item.external_id == item.url
    assert bing_entry_to_item({"title": "无链接"}) is None
    assert bing_entry_to_item({**entry, "published_parsed": None, "published": "bad"}) is None


def test_bing_news_publisher_strips_msn():
    assert publisher_of({"news_source": "金融界财经 on MSN"}) == "金融界财经"
    assert publisher_of({"news_source": "凤凰网资讯频道"}) == "凤凰网资讯频道"
    assert publisher_of({}) is None
