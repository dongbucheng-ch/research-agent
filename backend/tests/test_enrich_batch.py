"""批量富化:索引映射、缺项单条重试、整批失败降级、分块与进度回调。"""

import asyncio

from app.pipeline.enrich import EnrichInput, enrich_many
from app.services.llm import LLMError

KEYWORDS = [{"word": "agent", "kind": "include", "weight": 1.0}]


def _item(index: int, hint: str | None = None) -> EnrichInput:
    return EnrichInput(
        title=f"Title {index}",
        text=f"Body {index} about agents",
        url=f"https://example.com/{index}",
        channel="rss",
        content_type_hint=hint,
    )


def _row(index: int, *, content_type: str = "tech", summary: str | None = None) -> dict:
    return {
        "index": index,
        "lang": "en",
        "translated_title": f"标题 {index}",
        "summary": summary or f"摘要 {index}",
        "content_type": content_type,
        "relevance": 80,
        "heat": 70,
        "tags": ["agent"],
        "entities": [],
        "card": {
            "what": "w",
            "why": "y",
            "how": "h",
            "keywords": ["agent"],
        },
        "keywords": ["agent"],
    }


class FakeClient:
    """batch 提示包含「## 条目列表」,借此区分批量与单条调用。"""

    model = "fake-model"

    def __init__(self, *, batch=None, single=None, batch_error=None, single_error=None):
        self.batch = batch
        self.single = single
        self.batch_error = batch_error
        self.single_error = single_error
        self.calls: list[str] = []

    async def chat_json(self, prompt: str, *, system=None, temperature: float = 0.2):
        is_batch = "## 条目列表" in prompt
        self.calls.append("batch" if is_batch else "single")
        if is_batch:
            if self.batch_error is not None:
                raise self.batch_error
            return {"items": self.batch or []}
        if self.single_error is not None:
            raise self.single_error
        if self.single is not None:
            return self.single
        return _row(99)


def test_enrich_many_maps_by_index_and_applies_hints() -> None:
    client = FakeClient(batch=[_row(2), _row(1, content_type="tech")])
    outcome = asyncio.run(
        enrich_many(
            client,
            [_item(1, hint="paper"), _item(2)],
            topic_name="Agent",
            keywords=KEYWORDS,
        )
    )
    assert [r.summary for r in outcome.results] == ["摘要 1", "摘要 2"]
    # 第 1 条带了 paper 提示且 LLM 判为 tech → 被纠正为 paper;第 2 条保持 tech
    assert [r.content_type for r in outcome.results] == ["paper", "tech"]
    assert outcome.fallback_items == 0
    assert client.calls == ["batch"]


def test_enrich_many_retries_missing_items_individually() -> None:
    client = FakeClient(batch=[_row(1)], single=_row(99, summary="单条补跑"))
    outcome = asyncio.run(
        enrich_many(client, [_item(1), _item(2)], topic_name="Agent", keywords=KEYWORDS)
    )
    assert outcome.results[0].summary == "摘要 1"
    assert outcome.results[1].summary == "单条补跑"
    assert outcome.fallback_items == 0
    assert client.calls == ["batch", "single"]


def test_enrich_many_batch_failure_retries_singly_then_falls_back() -> None:
    client = FakeClient(batch_error=LLMError("bad json"), single=_row(99, summary="单条补跑"))
    outcome = asyncio.run(
        enrich_many(client, [_item(1), _item(2)], topic_name="Agent", keywords=KEYWORDS)
    )
    assert outcome.batch_failures == 1
    assert outcome.fallback_items == 0
    assert [r.summary for r in outcome.results] == ["单条补跑", "单条补跑"]
    assert client.calls == ["batch", "single", "single"]


def test_enrich_many_single_retry_failure_falls_back_for_chunk() -> None:
    client = FakeClient(batch_error=LLMError("down"), single_error=LLMError("down"))
    outcome = asyncio.run(
        enrich_many(client, [_item(1), _item(2)], topic_name="Agent", keywords=KEYWORDS)
    )
    assert outcome.batch_failures == 1
    assert outcome.fallback_items == 2
    assert all(r.summary for r in outcome.results)  # 降级也有摘要(截断正文)
    # 批量失败后只探测一次单条,失败即整块降级(不逐条打网络)
    assert client.calls == ["batch", "single"]


def test_enrich_many_chunks_and_reports_progress() -> None:
    client = FakeClient(batch=[_row(1), _row(2)])
    seen: list[int] = []
    outcome = asyncio.run(
        enrich_many(
            client,
            [_item(1), _item(2), _item(3)],
            topic_name="Agent",
            keywords=KEYWORDS,
            batch_size=2,
            on_progress=seen.append,
        )
    )
    assert client.calls == ["batch", "batch"]
    assert sorted(seen) == [2, 3]
    assert len(outcome.results) == 3
