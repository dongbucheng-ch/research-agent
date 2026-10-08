from app.services.fetch_service import (
    CollectionSpec,
    _expand_keywords_with_translation,
    _in_scope,
    _is_hot_channel,
    _keywords_for,
    collect_meta,
    spec_from_params,
)


def test_spec_from_params_splits_include_and_exclude():
    spec = spec_from_params(
        {
            "name": "多模态",
            "keywords": ["multimodal", "vlm"],
            "exclude_keywords": ["webinar"],
            "source_ids": [3, 1],
            "lookback_hours": 48,
            "min_score": 80,
        }
    )
    assert spec.name == "多模态"
    assert spec.include_words == ["multimodal", "vlm"]
    assert [k["word"] for k in spec.keywords if k["kind"] == "exclude"] == ["webinar"]
    assert spec.source_ids == [3, 1]
    assert spec.lookback_hours == 48
    assert spec.min_score == 80


def test_spec_from_params_dedupes_and_strips_words():
    spec = spec_from_params({"keywords": [" agent ", "agent", "", "LLM", "agent"]})
    assert spec.include_words == ["agent", "LLM"]


def test_spec_from_params_defaults_without_keywords():
    spec = spec_from_params({})
    assert spec.include_words == []
    assert spec.name == "临时采集"
    assert spec.lookback_hours == 24
    assert spec.min_score == 75
    assert spec.source_ids == []


def test_spec_from_params_clamps_lookback_and_min_score():
    """回看窗口最长 48 小时,入库门槛最低 75 分(含历史配置)。"""
    spec = spec_from_params(
        {"keywords": ["agent"], "lookback_hours": 720, "min_score": 60}
    )
    assert spec.lookback_hours == 48
    assert spec.min_score == 75
    spec = spec_from_params({"keywords": ["agent"], "lookback_hours": 0, "min_score": 120})
    assert spec.lookback_hours == 1
    assert spec.min_score == 100
    spec = spec_from_params({"keywords": ["agent"], "lookback_hours": "bad", "min_score": None})
    assert spec.lookback_hours == 24
    assert spec.min_score == 75


def test_spec_from_params_keeps_valid_score_weights():
    spec = spec_from_params({"keywords": ["agent"], "score_weights": {"relevance": 0.5}})
    assert spec.extra == {"score_weights": {"relevance": 0.5}}
    assert spec_from_params({"keywords": ["agent"], "score_weights": "bad"}).extra == {}


def test_spec_scopes_and_github_keywords():
    spec = spec_from_params(
        {
            "keywords": ["生物科技"],
            "scopes": ["github", "info", "bad"],
            "github_keywords": ["biotech-agent"],
            "github_mode": "strict",
            "backfill": "off",
        }
    )
    assert spec.scopes == ("info", "github")
    assert spec.include_words == ["生物科技"]
    assert spec.github_include_words == ["biotech-agent"]
    assert spec.github_mode == "strict"
    assert spec.backfill == "off"
    # 未配置 GitHub 专属词时沿用主关键词
    assert spec_from_params({"keywords": ["agent"]}).github_include_words == ["agent"]
    # 非法 scope 会被过滤;全非法时回退为全选
    assert spec_from_params({"keywords": ["agent"], "scopes": ["bad"]}).scopes == ("info", "github")


class _FakeSource:
    def __init__(self, channel: str, config: dict | None = None) -> None:
        self.channel = channel
        self.config = config or {}
        self.collector_kind = "search"


def test_scope_filter_and_github_channel_rules():
    rss = _FakeSource("rss")
    github = _FakeSource("github")
    trending = _FakeSource("github_trending")

    assert _in_scope(rss, ("info", "github")) is True
    assert _in_scope(github, ("info",)) is False
    assert _in_scope(github, ("github",)) is True

    spec = spec_from_params({"keywords": ["生物科技"], "github_keywords": ["biotech-agent"]})
    github_entries = _keywords_for(spec, github)
    assert [entry["word"] for entry in github_entries] == ["biotech-agent"]
    assert [entry["word"] for entry in _keywords_for(spec, rss)] == ["生物科技"]
    # 未配置专属词时,GitHub 源使用主关键词
    plain = spec_from_params({"keywords": ["生物科技"]})
    assert [entry["word"] for entry in _keywords_for(plain, github)] == ["生物科技"]

    assert _is_hot_channel(spec, trending) is True
    strict = spec_from_params({"keywords": ["x"], "github_mode": "strict"})
    assert _is_hot_channel(strict, trending) is False


class FakeTranslateLLM:
    model = "fake-translate"

    def __init__(self, reply: dict) -> None:
        self.reply = reply
        self.calls = 0

    async def chat_json(self, prompt: str, **_kwargs):
        self.calls += 1
        return self.reply


async def test_expand_keywords_adds_translated_aliases_in_same_group():
    llm = FakeTranslateLLM(
        {"translations": [{"word": "生物科技", "english": ["biotech", "biotechnology"]}]}
    )
    spec = spec_from_params({"keywords": ["生物科技"], "exclude_keywords": ["ETF"]})
    logs: list[str] = []
    await _expand_keywords_with_translation(spec, llm, logs.append)

    assert spec.include_words == ["生物科技", "biotech", "biotechnology"]
    assert [k for k in spec.keywords if k["kind"] == "exclude"] == [
        {"word": "ETF", "kind": "exclude", "weight": 1.0}
    ]
    # 原词不带 group(缺省即自身),译名显式挂到原词组下,打分时不互相稀释
    assert spec.keywords[0] == {"word": "生物科技", "kind": "include", "weight": 1.0}
    assert {k["group"] for k in spec.keywords if k.get("group")} == {"生物科技"}
    assert spec.extra["keyword_translations"] == {"生物科技": ["biotech", "biotechnology"]}
    assert any("关键词翻译" in line for line in logs)


async def test_expand_keywords_skips_english_only_and_missing_llm():
    spec = spec_from_params({"keywords": ["agent", "vlm"]})
    llm = FakeTranslateLLM({"translations": []})
    await _expand_keywords_with_translation(spec, llm, lambda _m: None)
    assert spec.include_words == ["agent", "vlm"]
    assert llm.calls == 0
    assert spec.extra == {}

    spec2 = spec_from_params({"keywords": ["生物科技"]})
    logs: list[str] = []
    await _expand_keywords_with_translation(spec2, None, logs.append)
    assert spec2.include_words == ["生物科技"]
    assert any("未配置" in line for line in logs)


def test_collect_meta_main_round_keeps_typed_keywords() -> None:
    spec = CollectionSpec(
        name="RAG",
        keywords=[
            {"word": "RAG", "kind": "include"},
            {"word": "retrieval augmented generation", "kind": "include", "origin": "translate"},
        ],
        source_ids=[],
    )
    meta = collect_meta(spec)
    assert meta == {
        "collect_name": "RAG",
        "collect_keywords": ["RAG", "retrieval augmented generation"],
        "origin": "main",
    }


def test_collect_meta_backfill_round_keeps_original_and_marks_expanded() -> None:
    spec = CollectionSpec(
        name="RAG·补量",
        keywords=[{"word": "biotech", "kind": "include", "origin": "expanded"}],
        source_ids=[],
        backfill="off",
        extra={"origin": "backfill", "origin_name": "RAG", "expanded_from": ["RAG"]},
    )
    meta = collect_meta(spec)
    assert meta["collect_name"] == "RAG"
    assert meta["collect_keywords"] == ["RAG"]
    assert meta["expanded_keywords"] == ["biotech"]
    assert meta["origin"] == "backfill"
