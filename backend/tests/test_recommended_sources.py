"""推荐信源库质量约束:JSON 合法、key 唯一、渠道注册、类别齐全、URL 非空。"""

import json
from collections import Counter
from pathlib import Path

from app.collectors import route_of
from app.models import Source
from app.schemas.config import RecommendedSource

CATALOG = Path(__file__).resolve().parents[1] / "resources" / "recommended_sources.json"
VALID_CATEGORIES = {
    "paper",
    "lab",
    "blog",
    "news",
    "cn",
    "bio",
    "community",
    "social",
    "engineering",
}


def _items() -> list[RecommendedSource]:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    return [RecommendedSource(**row) for row in data["sources"]]


def test_catalog_keys_unique_and_urls_present() -> None:
    items = _items()
    assert len(items) >= 50
    keys = [item.key for item in items]
    assert len(keys) == len(set(keys))
    assert all(item.url.startswith("http") for item in items)
    assert all(item.tier in {"S", "A", "B", "C"} for item in items)


def test_catalog_channels_are_registered() -> None:
    for item in _items():
        probe = Source(
            name=item.name,
            channel=item.channel,
            collector_kind=item.collector_kind,
            url=item.url,
            config=item.config,
            tier=item.tier,
        )
        assert route_of(probe) is not None, f"未注册的渠道: {item.channel} ({item.key})"


def test_catalog_categories_cover_core_groups() -> None:
    counts = Counter(item.category for item in _items())
    assert set(counts) <= VALID_CATEGORIES
    for required in ("paper", "lab", "cn", "bio"):
        assert counts[required] >= 2, f"类别 {required} 信源过少: {counts[required]}"
