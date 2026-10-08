"""关键词辐射:输出校验与缓存行为。"""

from __future__ import annotations

from app.services.keyword_expand import clear_expand_cache, expand_keywords, parse_expanded


class FakeLLM:
    model = "fake-expand"

    def __init__(self, reply: object) -> None:
        self.reply = reply
        self.calls = 0

    async def chat_json(self, prompt: str, **_kwargs):
        self.calls += 1
        return self.reply


def test_parse_expanded_filters_and_caps():
    data = {"keywords": ["robot learning", "robot learning", "  ", "sim2real", "biotech"]}
    assert parse_expanded(data, ["biotech"]) == ["robot learning", "sim2real"]
    assert parse_expanded({"keywords": [f"w{i}" for i in range(10)]}, []) == [
        "w0",
        "w1",
        "w2",
        "w3",
        "w4",
        "w5",
    ]
    assert parse_expanded("bad", []) == []


async def test_expand_keywords_requires_enough_terms_and_caches():
    clear_expand_cache()
    llm = FakeLLM({"keywords": ["a", "b", "c", "d", "e"]})
    words = await expand_keywords(llm, topic="具身智能", keywords=["embodied ai"])
    assert words == ["a", "b", "c", "d", "e"]
    assert llm.calls == 1

    # 同一模型 + 主题 + 词表命中缓存,不再调用 LLM
    again = await expand_keywords(llm, topic="具身智能", keywords=["embodied ai"])
    assert again == words
    assert llm.calls == 1


async def test_expand_keywords_skips_when_llm_missing_or_terms_too_few():
    clear_expand_cache()
    assert await expand_keywords(None, topic="t", keywords=["a"]) == []

    llm = FakeLLM({"keywords": ["a", "b"]})
    logs: list[str] = []
    assert await expand_keywords(llm, topic="t", keywords=["x"], log=logs.append) == []
    assert any("结果不足" in line for line in logs)
