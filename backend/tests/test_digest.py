"""日报排序、GitHub 选择与渲染(纯函数,不联网)。"""

from datetime import UTC, datetime, timedelta

from app.services.digest_service import (
    BLURB_MAX,
    BLURB_MIN,
    GLOBAL_WEIGHTS,
    SUMMARY_MAX,
    SUMMARY_MIN,
    TOPIC_WEIGHTS,
    _backfill_items,
    _char_count,
    _clamp_text,
    _fallback_payload,
    _fit_lengths,
    _length_targets,
    _link_label,
    _rank_candidates,
    _render_markdown,
    _select_github,
    batch_window,
    compute_shortfall,
    next_batch,
)

BRIEFS = [
    {
        "id": 11,
        "title": "小米开源 MiMo-V2.6 系列模型",
        "original_title": "MiMo-V2.6: A Family of Multimodal Models",
        "summary": "小米发布 Pro 和 Flash 两个多模态模型,Pro 在综合智能指数得分 46。",
        "url": "https://example.com/mimo",
    },
    {
        "id": 22,
        "title": "Grok 4.7 发布,主打编码能力",
        "original_title": "Grok 4.7 launch",
        "summary": "SpaceXAI 发布 Grok 4.7,官方称价格为 Claude 的三分之一。",
        "url": "https://example.com/grok",
    },
]

GITHUB = [
    {
        "full_name": "openai/agents-sdk",
        "url": "https://github.com/openai/agents-sdk",
        "description": "Agent toolkit",
        "language": "Python",
        "stars_total": 12400,
        "stars_today": 321,
        "stars_per_day": None,
        "source": "trending",
        "hot": "今日 +321 ★",
    },
    {
        "full_name": "example/vision-agent",
        "url": "https://github.com/example/vision-agent",
        "description": "Vision agent",
        "language": "TypeScript",
        "stars_total": 860,
        "stars_today": 0,
        "stars_per_day": 42.5,
        "source": "search",
        "hot": "日均 +42.5 ★",
    },
]


def test_render_markdown_maps_source_ids_to_links():
    payload = {
        "title": "AI 研讯",
        "lead": "两条核心动态。",
        "highlights": ["MiMo 开源", "Grok 4.7 发布"],
        "items": [
            {"title": "小米开源 MiMo-V2.6", "summary": "多模态模型开源。", "source_ids": [11]},
            {"title": "Grok 4.7 发布", "summary": "主打编码。", "source_ids": [22, 11]},
        ],
    }
    markdown, used = _render_markdown(payload, BRIEFS, GITHUB[:1])
    assert "# AI 研讯" in markdown
    assert "> 两条核心动态。" in markdown
    assert "## 今日资讯" in markdown
    assert "### 1. 小米开源 MiMo-V2.6" in markdown
    assert "多模态模型开源。" in markdown
    assert "- [MiMo-V2.6: A Family of Multimodal Models](https://example.com/mimo)" in markdown
    assert "### 2. Grok 4.7 发布" in markdown
    assert "- [Grok 4.7 launch](https://example.com/grok)" in markdown
    assert markdown.count("- [MiMo-V2.6: A Family of Multimodal Models]") == 2
    assert "## GitHub 今日推荐" in markdown
    assert "### 1. openai/agents-sdk" in markdown
    assert "标签：Python · ★12.4k · 今日 +321" in markdown
    assert "Agent toolkit" in markdown
    assert "- [openai/agents-sdk](https://github.com/openai/agents-sdk)" in markdown
    assert "**今日要点**" not in markdown
    assert {brief["id"] for brief in used} == {11, 22}


def test_link_label_escapes_brackets_and_falls_back():
    assert _link_label({"original_title": "A [test] title"}) == "A \\[test\\] title"
    assert _link_label({"title": "  多  空格  "}) == "多 空格"
    assert _link_label({}) == "原文链接"


def test_render_markdown_skips_unknown_source_ids_and_notes_empty_github():
    payload = {
        "title": "t",
        "lead": "",
        "highlights": [],
        "items": [{"title": "unknown", "summary": "", "source_ids": [999]}],
    }
    markdown, used = _render_markdown(payload, BRIEFS)
    assert used == []
    assert "(本期无可用条目)" in markdown
    assert "(本期未取到 GitHub 数据)" in markdown


def test_fallback_payload_uses_top_briefs_and_github():
    now = datetime(2026, 9, 29, tzinfo=UTC)
    payload = _fallback_payload(BRIEFS, limit=1, now=now, github=GITHUB, github_limit=1)
    assert payload["items"][0]["source_ids"] == [11]
    assert payload["title"].startswith("研讯日报 · 09-29")
    assert payload["github"][0]["full_name"] == "openai/agents-sdk"
    assert "1 条高分资讯" in payload["lead"]


def test_select_github_validates_llm_choice_and_fills_rest():
    payload = {"github": [{"full_name": "evil/repo", "blurb": "x"}]}
    selected = _select_github(payload, GITHUB, limit=2)
    assert [entry["full_name"] for entry in selected] == [
        "openai/agents-sdk",
        "example/vision-agent",
    ]

    payload = {"github": [{"full_name": "example/vision-agent", "blurb": "视觉智能体走红"}]}
    selected = _select_github(payload, GITHUB, limit=2)
    assert selected[0]["full_name"] == "example/vision-agent"
    assert selected[0]["blurb"] == "视觉智能体走红"
    assert selected[1]["full_name"] == "openai/agents-sdk"


class FakeScore:
    def __init__(self, relevance: float, heat: float, freshness: float) -> None:
        self.relevance = relevance
        self.heat = heat
        self.freshness = freshness
        self.total = max(relevance, heat, freshness)


class FakeContent:
    def __init__(self, translated_title: str = "", summary: str = "") -> None:
        self.translated_title = translated_title
        self.summary = summary


class FakeItem:
    def __init__(
        self,
        item_id: int,
        title: str,
        *,
        relevance: float = 0,
        heat: float = 0,
        freshness: float = 0,
        summary: str = "",
        tags: list[str] | None = None,
    ) -> None:
        self.id = item_id
        self.title = title
        self.tags = tags or []
        self.score = FakeScore(relevance, heat, freshness)
        self.content = FakeContent(summary=summary)


def test_global_ranking_ignores_relevance():
    hot = FakeItem(1, "热点新闻", heat=95, freshness=90)
    relevant = FakeItem(2, "相关但很冷", relevance=100, heat=40, freshness=50)
    ranked = _rank_candidates([relevant, hot], scope="global", keywords=[])
    assert [item.id for item, _ in ranked] == [1, 2]
    assert ranked[0][1] == round(0.6 * 95 + 0.4 * 90, 2)


def test_topic_ranking_filters_off_topic_and_boosts_keyword_hits():
    on_topic = FakeItem(1, "具身智能机器人大模型发布", heat=50, freshness=80)
    off_topic = FakeItem(2, "无关内容", relevance=10, heat=99, freshness=99)
    ranked = _rank_candidates([off_topic, on_topic], scope="topic", keywords=["具身智能", "机器人"])
    assert [item.id for item, _ in ranked] == [1]
    assert ranked[0][1] == round(
        TOPIC_WEIGHTS["relevance"] * 100
        + TOPIC_WEIGHTS["heat"] * 50
        + TOPIC_WEIGHTS["freshness"] * 80,
        2,
    )


def test_weights_are_the_confirmed_values():
    assert GLOBAL_WEIGHTS == {"heat": 0.6, "freshness": 0.4}
    assert TOPIC_WEIGHTS == {"relevance": 0.5, "heat": 0.3, "freshness": 0.2}


class FakeLengthLLM:
    """只回长度补写结果的假客户端。"""

    model = "fake"

    def __init__(self, reply: dict) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    async def chat_json(self, prompt: str, **_kwargs):
        self.prompts.append(prompt)
        return self.reply


def test_char_count_ignores_whitespace_noise():
    assert _char_count(" 生物科技\n涨超 6% ") == _char_count("生物科技涨超6%")


def test_clamp_text_prefers_sentence_boundary():
    text = "甲" * 250 + "。" + "乙" * 100
    clamped = _clamp_text(text, 300)
    assert clamped.endswith("。")
    assert _char_count(clamped) == 251

    hard = _clamp_text("字" * 600, 120)
    assert _char_count(hard) == 120  # 119 字 + 省略号
    assert hard.endswith("…")
    assert _clamp_text("短文本", 100) == "短文本"


def test_length_targets_flag_only_out_of_range():
    payload = {
        "items": [
            {"title": "达标", "summary": "中" * 300, "source_ids": [11]},
            {"title": "太短", "summary": "中" * 40, "source_ids": [22]},
        ],
        "github": [
            {"full_name": "a/b", "blurb": "中" * 150},
            {"full_name": "c/d", "blurb": "短"},
        ],
    }
    targets = _length_targets(payload, BRIEFS)
    assert [t["kind"] for t in targets] == ["item", "github"]
    assert targets[0]["key"] == "1"
    assert targets[0]["refs"][0]["title"].startswith("Grok 4.7")
    assert targets[1]["key"] == "c/d"
    assert (targets[0]["min"], targets[0]["max"]) == (SUMMARY_MIN, SUMMARY_MAX)
    assert (targets[1]["min"], targets[1]["max"]) == (BLURB_MIN, BLURB_MAX)


async def test_fit_lengths_repairs_via_llm_and_clamps_overflow():
    payload = {
        "items": [{"title": "太短", "summary": "中" * 40, "source_ids": [11]}],
        "github": [{"full_name": "c/d", "blurb": "短"}],
    }
    llm = FakeLengthLLM(
        {
            "items": [{"key": "0", "text": "讯" * 320}],
            "github": [{"key": "c/d", "text": "仓" * 260}],
        }
    )
    logs: list[str] = []
    fitted = await _fit_lengths(payload, BRIEFS, llm=llm, log=logs.append)

    assert _char_count(fitted["items"][0]["summary"]) == 320
    assert _char_count(fitted["github"][0]["blurb"]) == BLURB_MAX  # 超长被截断
    assert "正文长度整形" in logs[-1]
    assert "补写 2 条" in logs[-1]


async def test_fit_lengths_without_llm_clamps_and_logs_short():
    payload = {
        "items": [{"title": "短", "summary": "中" * 30, "source_ids": [11]}],
        "github": [{"full_name": "a/b", "blurb": "仓" * 400}],
    }
    logs: list[str] = []
    fitted = await _fit_lengths(payload, BRIEFS, llm=None, log=logs.append)
    assert fitted["items"][0]["summary"] == "中" * 30  # 无 LLM 无法补写,只提示
    assert _char_count(fitted["github"][0]["blurb"]) <= BLURB_MAX
    assert "仍有" in logs[-1]


async def test_fit_lengths_noop_when_all_in_range():
    payload = {
        "items": [{"title": "达标", "summary": "中" * 300, "source_ids": [11]}],
        "github": [{"full_name": "a/b", "blurb": "仓" * 120}],
    }
    logs: list[str] = []
    fitted = await _fit_lengths(payload, BRIEFS, llm=None, log=logs.append)
    assert fitted == payload
    assert logs == []


def test_backfill_items_fills_to_limit_with_unused_briefs():
    payload = {
        "items": [{"title": "已有", "summary": "中" * 300, "source_ids": [11]}],
    }
    logs: list[str] = []
    added = _backfill_items(payload, BRIEFS, 2, log=logs.append)
    assert added == 1
    assert [item["source_ids"] for item in payload["items"]] == [[11], [22]]
    assert payload["items"][1]["auto"] is True
    assert "补齐 1 条 → 共 2 条" in logs[-1]


def test_backfill_items_respects_available_material_and_drops_invalid():
    payload = {
        "items": [
            {"title": "无 source_ids", "summary": "x"},
            {"title": "已有", "summary": "中" * 300, "source_ids": [22]},
        ],
    }
    logs: list[str] = []
    added = _backfill_items(payload, BRIEFS, 10, log=logs.append)
    # briefs 只有 2 条,且 22 已使用 → 只能再补 1 条;无效条目被丢弃
    assert added == 1
    assert [item["source_ids"] for item in payload["items"] if item.get("source_ids")] == [
        [22],
        [11],
    ]
    assert "丢弃 1 条" in logs[-1]


def test_backfill_items_truncates_when_llm_writes_too_many():
    payload = {
        "items": [
            {"title": "t", "summary": "中" * 300, "source_ids": [11]},
            {"title": "t", "summary": "中" * 300, "source_ids": [22]},
            {"title": "t", "summary": "中" * 300, "source_ids": [33]},
        ],
    }
    logs: list[str] = []
    _backfill_items(payload, BRIEFS, 2, log=logs.append)
    assert len(payload["items"]) == 2


def test_compute_shortfall_reports_news_and_github_gaps():
    assert compute_shortfall(news_items=10, limit=10, github_items=5) == {}
    assert compute_shortfall(news_items=6, limit=10, github_items=2) == {
        "news": {"expected": 10, "actual": 6},
        "github": {"expected": 3, "actual": 2},
    }


class _FakeCountSession:
    def __init__(self, count: int) -> None:
        self.count = count

    async def scalar(self, _stmt):
        return self.count


def test_batch_window_covers_local_day() -> None:
    now = datetime(2026, 10, 8, 1, 30, tzinfo=UTC)
    start, end = batch_window(now)
    assert end - start == timedelta(days=1)
    assert start == now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    assert start.date().isoformat() == now.astimezone().date().isoformat()


async def test_next_batch_counts_same_day_plus_one() -> None:
    now = datetime(2026, 10, 8, 1, 30, tzinfo=UTC)
    local_date = now.astimezone().date().isoformat()
    assert await next_batch(_FakeCountSession(0), now) == {"date": local_date, "index": 1}
    assert await next_batch(_FakeCountSession(2), now) == {"date": local_date, "index": 3}
