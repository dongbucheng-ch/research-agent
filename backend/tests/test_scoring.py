from datetime import UTC, datetime, timedelta

from app.pipeline.scoring import (
    combine_scores,
    excluded_by_keywords,
    freshness_score,
    keyword_relevance,
    metric_heat_score,
)

KEYWORDS = [
    {"word": "agent", "kind": "include", "weight": 1.0},
    {"word": "llm", "kind": "include", "weight": 1.0},
    {"word": "crypto", "kind": "exclude", "weight": 1.0},
]


def test_keyword_relevance_counts_weighted_hits():
    score, hits = keyword_relevance("New LLM agent framework released", KEYWORDS)
    assert score > 0
    assert "agent" in hits and "llm" in hits
    assert keyword_relevance("cooking recipes for beginners", KEYWORDS)[0] == 0.0


def test_excluded_by_keywords():
    assert excluded_by_keywords("crypto agent tokens", KEYWORDS) == "crypto"
    assert excluded_by_keywords("agent memory talk", KEYWORDS) is None


def test_freshness_decay():
    now = datetime(2026, 9, 29, tzinfo=UTC)
    fresh = freshness_score(now - timedelta(hours=1), "tech", now)
    old = freshness_score(now - timedelta(hours=96), "tech", now)
    assert fresh > old
    assert 0 <= old < 40
    assert freshness_score(None, "tech", now) == 40.0


def test_metric_heat_github_repo():
    hot = metric_heat_score({"stars_total": 50000, "stars_today": 900})
    cold = metric_heat_score({"stars_total": 50, "stars_today": 1})
    assert hot is not None and cold is not None
    assert hot > cold > 0
    assert metric_heat_score({}) is None


def test_combine_scores_uses_metric_heat_when_available():
    result = combine_scores(
        keyword_rel=80,
        llm_rel=90,
        llm_heat=50,
        metric_heat=100,
        freshness=100,
        keyword_hits=["agent"],
    )
    assert result.heat == 100
    assert result.relevance == 0.6 * 80 + 0.4 * 90
    expected_total = 0.45 * result.relevance + 0.35 * 100 + 0.20 * 100
    assert abs(result.total - round(expected_total, 2)) < 0.01


def test_keyword_relevance_groups_translated_aliases():
    # 中文词 + 其英文译名归一组:命中中文仍应得满分,不被译名稀释
    keywords = [
        {"word": "生物科技", "kind": "include", "weight": 1.0, "group": "生物科技"},
        {"word": "biotech", "kind": "include", "weight": 1.0, "group": "生物科技"},
        {"word": "biotechnology", "kind": "include", "weight": 1.0, "group": "生物科技"},
    ]
    score, hits = keyword_relevance("金斯瑞生物科技涨超6%", keywords)
    assert score == 100.0
    assert hits == ["生物科技"]
    score_en, hits_en = keyword_relevance("Biotech startup raised $50M", keywords)
    assert score_en == 100.0
    assert hits_en == ["biotech"]


def test_keyword_relevance_group_missing_falls_back_to_word():
    keywords = [
        {"word": "agent", "kind": "include", "weight": 1.0},
        {"word": "embodied", "kind": "include", "weight": 1.0},
    ]
    score, hits = keyword_relevance("agent framework", keywords)
    assert score == 50.0
    assert hits == ["agent"]
