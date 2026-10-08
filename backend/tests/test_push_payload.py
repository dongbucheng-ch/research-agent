"""推送 payload:标签按素材汇总、override 优先级与兜底。"""

from __future__ import annotations

from app.services.push.payload import compose_payload, normalize_tags, rank_tags


def test_rank_tags_by_frequency_then_first_seen():
    assert rank_tags([["b", "a"], ["b", "c"], ["b"]]) == ["b", "a", "c"]


def test_rank_tags_skips_blank_and_respects_limit():
    assert rank_tags([[" ", "x", "y"], ["x", "z"]], limit=2) == ["x", "y"]
    assert rank_tags([]) == []


def test_normalize_tags_dedupes_trims_and_caps():
    long_tag = "长" * 70
    assert normalize_tags([" a ", "a", "", long_tag, "b"], limit=3) == ["a", "长" * 64, "b"]
    assert normalize_tags(None) == []


def test_compose_payload_defaults_from_target_and_channel():
    payload = compose_payload(
        target_id=21,
        title="研讯日报",
        lead="lead",
        content_md="# md",
        highlights=["h1"],
        material_tags=["大模型", "大模型", "开源"],
        channel_config={"source": "研讯平台", "author": "编辑部"},
    )
    assert payload["id"] == 21
    assert payload["title"] == "研讯日报"
    assert payload["tags"] == ["大模型", "开源"]
    assert payload["source"] == "研讯平台"
    assert payload["author"] == "编辑部"
    assert payload["highlights"] == ["h1"]


def test_compose_payload_overrides_win_and_empty_falls_back():
    payload = compose_payload(
        target_id=21,
        title="研讯日报",
        lead=None,
        content_md=None,
        highlights=None,
        material_tags=["素材标签"],
        overrides={"title": "自定义标题", "source": " ", "author": "", "tags": ["A", "B"]},
        channel_config={"source": "研讯平台", "author": "编辑部"},
    )
    assert payload["title"] == "自定义标题"
    assert payload["source"] == "研讯平台"
    assert payload["author"] == "编辑部"
    assert payload["tags"] == ["A", "B"]
    assert payload["highlights"] == []
    assert payload["lead"] == ""


def test_compose_payload_empty_tag_override_uses_material_tags():
    payload = compose_payload(
        target_id=1,
        title="t",
        lead="",
        content_md="",
        highlights=[],
        material_tags=["素材"],
        overrides={"tags": []},
    )
    assert payload["tags"] == ["素材"]
    assert payload["source"] == ""
