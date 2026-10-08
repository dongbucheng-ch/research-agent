"""中文关键词 → 英文检索词(纯逻辑 + 假 LLM,不联网)。"""

import pytest

from app.services.keyword_translate import (
    alias_keyword_entries,
    clear_translation_cache,
    has_cjk,
    needs_translation,
    parse_translations,
    translate_keywords,
)
from app.services.llm import LLMError


class FakeLLM:
    model = "fake-model"

    def __init__(self, reply=None, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.prompts: list[str] = []

    async def chat_json(self, prompt: str, **_kwargs):
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.reply


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_translation_cache()
    yield
    clear_translation_cache()


def test_has_cjk_and_needs_translation():
    assert has_cjk("生物科技")
    assert not has_cjk("biotech")
    assert needs_translation(["生物科技", "agent"])
    assert not needs_translation(["biotech", "agent-2"])


def test_parse_translations_filters_and_caps():
    data = {
        "translations": [
            {
                "word": "生物科技",
                "english": ["biotech", "Biotechnology", "生物医学", "", "a b c d e"],
            },
            {"word": "不存在的词", "english": ["nope"]},
            {"word": "gene editing", "english": ["gene editing", "crispr"]},
        ]
    }
    mapping = parse_translations(data, ["生物科技", "gene editing"])
    assert mapping["生物科技"] == ["biotech", "biotechnology"]
    assert mapping["gene editing"] == ["crispr"]


def test_alias_keyword_entries_share_group():
    entries = alias_keyword_entries({"生物科技": ["biotech"]})
    assert entries == [{"word": "biotech", "kind": "include", "weight": 1.0, "group": "生物科技"}]


async def test_translate_keywords_caches_and_skips_english_only():
    llm = FakeLLM({"translations": [{"word": "生物科技", "english": ["biotech"]}]})
    assert await translate_keywords(llm, ["agent", "llm"]) == {}
    assert llm.prompts == []

    mapping = await translate_keywords(llm, ["生物科技"])
    assert mapping == {"生物科技": ["biotech"]}
    assert len(llm.prompts) == 1

    # 同一模型 + 同一批词:命中进程内缓存,不再调用 LLM
    assert await translate_keywords(llm, ["生物科技"]) == {"生物科技": ["biotech"]}
    assert len(llm.prompts) == 1


async def test_translate_keywords_degrades_without_llm_or_on_error():
    assert await translate_keywords(None, ["生物科技"]) == {}

    llm = FakeLLM(error=LLMError("boom"))
    logs: list[str] = []
    assert await translate_keywords(llm, ["生物科技"], log=logs.append) == {}
    assert any("关键词翻译失败" in line for line in logs)

    empty = FakeLLM({"translations": []})
    logs.clear()
    assert await translate_keywords(empty, ["生物科技"], log=logs.append) == {}
    assert logs and "无可用结果" in logs[-1]
