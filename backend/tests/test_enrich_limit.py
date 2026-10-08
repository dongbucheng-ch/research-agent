"""富化条数上限:预排序与 Top-N 拆分(不联网)。"""

from datetime import UTC, datetime

from app.services.fetch_service import enrich_rank_key, split_enrich_indexes

OLD = datetime(2026, 1, 1, tzinfo=UTC)
NEW = datetime(2026, 10, 1, tzinfo=UTC)


def test_rank_prefers_keyword_hits_then_tier_then_freshness() -> None:
    many_hits = enrich_rank_key("B", 3, OLD)
    few_hits = enrich_rank_key("S", 1, NEW)
    same_hits_top_tier = enrich_rank_key("S", 2, OLD)
    same_hits_low_tier = enrich_rank_key("C", 2, OLD)
    fresh = enrich_rank_key("B", 2, NEW)
    stale = enrich_rank_key("B", 2, OLD)
    assert many_hits < few_hits  # 命中多压过信源等级
    assert same_hits_top_tier < same_hits_low_tier  # 同级命中:高等级优先
    assert fresh < stale  # 同级同级命中:新发布优先


def test_split_returns_all_when_within_limit() -> None:
    keys = [enrich_rank_key("B", 1, NEW)] * 3
    llm, plain = split_enrich_indexes(keys, 5)
    assert llm == [0, 1, 2]
    assert plain == []


def test_split_zero_limit_means_unlimited() -> None:
    keys = [enrich_rank_key("B", 1, NEW)] * 3
    llm, plain = split_enrich_indexes(keys, 0)
    assert llm == [0, 1, 2]
    assert plain == []


def test_split_limits_to_top_ranked() -> None:
    keys = [
        enrich_rank_key("B", 0, OLD),  # 0:最差
        enrich_rank_key("A", 5, NEW),  # 1:最好
        enrich_rank_key("B", 2, NEW),  # 2:中间
        enrich_rank_key("A", 5, OLD),  # 3:次好
    ]
    llm, plain = split_enrich_indexes(keys, 2)
    assert llm == [1, 3]
    assert plain == [2, 0]  # 降级组同样按 rank 排序(确定性输出)
