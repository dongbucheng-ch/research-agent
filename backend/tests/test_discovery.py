"""信源发现器:URL 归一化、OPML/HTML 解析、去重等纯函数(不联网)。"""

from app.services.discovery import (
    FeedCandidate,
    dedupe_candidates,
    extract_from_html,
    normalize_url,
    parse_opml,
    urls_from_text,
)

OPML = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>feeds</title></head>
  <body>
    <outline text="机器之心" type="rss" xmlUrl="https://example.com/machine-heart/feed"/>
    <outline text="无链接分组">
      <outline title="ArXiv CS.AI" type="rss" xmlUrl="https://rss.arxiv.org/rss/cs.AI"/>
    </outline>
    <outline text="没有 feed" type="folder"/>
  </body>
</opml>"""


def test_normalize_url() -> None:
    assert normalize_url("HTTPS://WWW.Example.com/Feed/") == "example.com/feed"
    assert normalize_url("http://example.com") == "example.com"


def test_parse_opml_extracts_feeds() -> None:
    feeds = parse_opml(OPML)
    assert [feed.url for feed in feeds] == [
        "https://example.com/machine-heart/feed",
        "https://rss.arxiv.org/rss/cs.AI",
    ]
    assert feeds[0].name == "机器之心"
    assert feeds[1].name == "ArXiv CS.AI"


def test_parse_opml_invalid_xml() -> None:
    assert parse_opml("<not-closed") == []


def test_urls_from_text_filters_feed_hints() -> None:
    text = "see https://a.com/rss and https://b.com/about and https://c.com/feed.xml"
    assert [feed.url for feed in urls_from_text(text)] == [
        "https://a.com/rss",
        "https://c.com/feed.xml",
    ]


def test_extract_from_html_alternate_and_anchor() -> None:
    html = """
    <html><head>
      <link rel="alternate" type="application/rss+xml" href="/feed.xml"/>
      <link rel="stylesheet" href="/style.css"/>
    </head><body>
      <a href="https://other.com/blog/atom">Atom</a>
      <a href="/about">About</a>
    </body></html>
    """
    feeds = extract_from_html(html, "https://site.com/blog/")
    assert [feed.url for feed in feeds] == [
        "https://site.com/feed.xml",
        "https://other.com/blog/atom",
    ]
    assert feeds[1].name == "Atom"


def test_dedupe_candidates_normalizes_and_limits() -> None:
    candidates = [
        FeedCandidate(name="a", url="https://example.com/feed/"),
        FeedCandidate(name="dup", url="https://www.example.com/feed"),
        FeedCandidate(name="bad", url="ftp://example.com/feed"),
        FeedCandidate(name="b", url="https://b.com/rss"),
        FeedCandidate(name="c", url="https://c.com/rss"),
    ]
    out = dedupe_candidates(candidates, limit=2)
    assert [feed.url for feed in out] == ["https://example.com/feed/", "https://b.com/rss"]
    assert out[0].name == "a"


def test_dedupe_candidates_name_fallback() -> None:
    out = dedupe_candidates([FeedCandidate(name="  ", url="https://x.com/feed")])
    assert out[0].name == "https://x.com/feed"
