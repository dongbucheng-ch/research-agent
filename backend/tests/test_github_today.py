"""GitHub 今日取数纯函数(不联网)。"""

from app.services.github_today import _merge, _trending_candidate, match_keywords, pick_trending

TRENDING = [
    {
        "full_name": "a/agent-os",
        "url": "https://github.com/a/agent-os",
        "description": "Agent runtime in Rust",
        "language": "Rust",
        "stars_total": 2100,
        "stars_today": 120,
    },
    {
        "full_name": "b/llm-trainer",
        "url": "https://github.com/b/llm-trainer",
        "description": "LLM training toolkit",
        "language": "Python",
        "stars_total": 800,
        "stars_today": 460,
    },
    {
        "full_name": "c/vision",
        "url": "https://github.com/c/vision",
        "description": "Vision models",
        "language": "Python",
        "stars_total": 300,
        "stars_today": 30,
    },
]


def test_match_keywords_checks_name_description_language():
    assert match_keywords(TRENDING[0], ["agent", "rust"]) == ["agent", "rust"]
    assert match_keywords(TRENDING[2], ["agent"]) == []


def test_pick_trending_filters_then_sorts_by_today_stars():
    picked = pick_trending(TRENDING, ["llm"], limit=5)
    assert [repo["full_name"] for repo in picked] == ["b/llm-trainer"]
    assert picked[0]["hot"] == "今日 +460 ★"

    picked = pick_trending(TRENDING, [], limit=2)
    assert [repo["full_name"] for repo in picked] == ["b/llm-trainer", "a/agent-os"]


def test_merge_dedupes_and_keeps_priority_order():
    first = _trending_candidate(TRENDING[0])
    second = _trending_candidate(TRENDING[1])
    duplicate = dict(second, source="search")
    third = _trending_candidate(TRENDING[2])
    merged = _merge([[first, second], [duplicate, third]], limit=5)
    assert [repo["full_name"] for repo in merged] == [
        "a/agent-os",
        "b/llm-trainer",
        "c/vision",
    ]
    assert len(_merge([[first], [second]], limit=1)) == 1
