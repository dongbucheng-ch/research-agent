"""LLM token 统计:累计与阶段差值(不联网)。"""

from app.services.llm import LLMUsage, usage_delta


def test_usage_add_accumulates() -> None:
    usage = LLMUsage()
    usage.add({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120})
    usage.add({"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60})
    assert usage.calls == 2
    assert usage.as_dict() == {
        "calls": 2,
        "prompt_tokens": 150,
        "completion_tokens": 30,
        "total_tokens": 180,
    }


def test_usage_add_tolerates_missing_fields() -> None:
    usage = LLMUsage()
    usage.add(None)
    usage.add({"prompt_tokens": 7})
    assert usage.calls == 2
    assert usage.total_tokens == 0
    assert usage.prompt_tokens == 7


def test_usage_delta() -> None:
    before = {"calls": 1, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    after = {"calls": 4, "prompt_tokens": 90, "completion_tokens": 40, "total_tokens": 130}
    assert usage_delta(before, after) == {
        "calls": 3,
        "prompt_tokens": 80,
        "completion_tokens": 35,
        "total_tokens": 115,
    }
