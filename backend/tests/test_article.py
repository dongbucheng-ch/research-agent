"""完整文章流水线的纯函数(不联网)。"""

from app.services.article_service import (
    _assemble,
    _filter_items_result,
    _parse_refs,
    _ref_sources,
    _strip_reference_block,
    _validate_sections,
)

KEPT = [
    {
        "id": 11,
        "ref": 1,
        "title": "小米开源 MiMo-V2.6",
        "summary": "多模态模型开源。",
        "url": "https://example.com/mimo",
        "channel": "rss",
        "published_at": "2026-09-29T08:00:00+00:00",
    },
    {
        "id": 22,
        "ref": 2,
        "title": "Grok 4.7 发布",
        "summary": "主打编码能力。",
        "url": "https://example.com/grok",
        "channel": "hackernews",
        "published_at": "2026-09-28T08:00:00+00:00",
    },
]


def test_parse_refs_ignores_markdown_links():
    text = "事实 A [1],事实 B [2],引用 [10],链接 [原文](https://example.com)。"
    assert _parse_refs(text) == [1, 2, 10]
    assert _parse_refs("无引用") == []
    assert _parse_refs("[1](https://example.com) 不是引用编号") == []


def test_filter_items_result_validates_and_caps():
    payload = {"kept": [22, 999, "11", 11, "x"]}
    assert _filter_items_result(payload, KEPT, max_sources=10) == [22, 11]
    assert _filter_items_result(payload, KEPT, max_sources=1) == [22]
    assert _filter_items_result({}, KEPT, max_sources=5) == []


def test_validate_sections_drops_sections_without_valid_sources():
    outline = {
        "sections": [
            {"heading": "背景", "points": ["p1"], "source_ids": [11]},
            {"heading": "无引用", "points": [], "source_ids": []},
            {"heading": "编造", "points": [], "source_ids": [999]},
            {"heading": "技术", "points": ["p2"], "source_ids": [22, 22, 11]},
        ]
    }
    sections = _validate_sections(outline, KEPT)
    assert [section["heading"] for section in sections] == ["背景", "技术"]
    assert sections[1]["source_ids"] == [22, 11]


def test_validate_sections_falls_back_to_single_core_section():
    sections = _validate_sections({"sections": [{"heading": "x", "source_ids": []}]}, KEPT)
    assert len(sections) == 1
    assert sections[0]["heading"] == "核心进展"
    assert sections[0]["source_ids"] == [11, 22]


def test_ref_sources_and_assemble_render_links():
    sources = _ref_sources(KEPT, [1, 2])
    assert "[1] 小米开源 MiMo-V2.6 —— 多模态模型开源。(https://example.com/mimo)" in sources

    content = _assemble("标题", "导读", "## 背景\n\n模型开源 [1]。", [1], KEPT)
    assert content.startswith("# 标题")
    assert "> 导读" in content
    assert "## 参考来源" in content
    assert "1. [小米开源 MiMo-V2.6](https://example.com/mimo) · rss · 2026-09-29" in content


def test_strip_reference_block_removes_llm_appended_references():
    body = "## 背景\n\n正文 [1]。\n\n## 参考来源\n\n1. 编造的来源"
    assert _strip_reference_block(body) == "## 背景\n\n正文 [1]。"
