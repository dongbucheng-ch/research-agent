"""HF Daily Papers 采集器:字段映射与注册表(不联网)。"""

from datetime import UTC, datetime

from app.collectors import CHANNEL_ROUTES, collector_for, object_type_of, route_of
from app.collectors.hf_papers import daily_paper_to_item

SAMPLE = {
    "paper": {
        "id": "2610.08963",
        "title": "On KL-Regularized Policy Optimization",
        "summary": "We propose KLPO, a framework that anchors the KL regularizer at the sampler.",
        "authors": [{"name": "Yifan Zhang"}],
        "upvotes": 42,
        "publishedAt": "2026-10-06T00:00:00.000Z",
        "githubRepo": "https://github.com/example/klpo",
    },
    "publishedAt": "2026-10-06T00:00:00.000Z",
    "numComments": 7,
}


class FakeSource:
    def __init__(self, channel: str, config: dict | None = None) -> None:
        self.channel = channel
        self.config = config or {}
        self.name = channel


def test_daily_paper_mapping() -> None:
    item = daily_paper_to_item(SAMPLE)
    assert item is not None
    assert item.url == "https://huggingface.co/papers/2610.08963"
    assert item.title == "On KL-Regularized Policy Optimization"
    assert item.published_at == datetime(2026, 10, 6, tzinfo=UTC)
    assert item.author == "Yifan Zhang"
    assert item.content_type_hint == "paper"
    assert item.metrics["upvotes"] == 42
    assert item.metrics["comments"] == 7
    assert item.extra["github_repo"] == "https://github.com/example/klpo"


def test_daily_paper_mapping_skips_incomplete() -> None:
    assert daily_paper_to_item({}) is None
    assert daily_paper_to_item({"paper": {"id": "", "title": "x"}}) is None
    assert daily_paper_to_item({"paper": {"id": "2610.1", "title": "  "}}) is None
    assert daily_paper_to_item("not-a-dict") is None


def test_route_and_object_type() -> None:
    assert CHANNEL_ROUTES["hf_papers"] == ("news", "hf_papers")
    assert route_of(FakeSource("hf_papers")) == ("news", "hf_papers")
    assert collector_for(FakeSource("hf_papers")) is not None
    assert object_type_of(FakeSource("hf_papers")) == "paper"
