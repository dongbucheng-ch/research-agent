"""定时采集:下次运行时间 / 参数映射 / 时间解析(纯函数,不联网)。"""

import types
from datetime import UTC, datetime, timedelta

from app.services import schedules
from app.services.schedules import (
    fetch_params,
    interval_minutes,
    next_run_at,
    parse_dt,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def test_next_run_at_uses_last_run_plus_interval() -> None:
    schedule = {
        "enabled": True,
        "interval_minutes": 60,
        "last_run_at": (NOW - timedelta(minutes=30)).isoformat(),
    }
    assert next_run_at(schedule, now=NOW) == NOW + timedelta(minutes=30)


def test_next_run_at_defaults_to_now_plus_interval_when_never_run() -> None:
    schedule = {"enabled": True, "interval_minutes": 120}
    assert next_run_at(schedule, now=NOW) == NOW + timedelta(minutes=120)


def test_next_run_at_disabled_returns_stored_or_none() -> None:
    assert next_run_at({"enabled": False}, now=NOW) is None
    stored = (NOW - timedelta(hours=1)).isoformat()
    assert next_run_at({"enabled": False, "next_run_at": stored}, now=NOW) == parse_dt(stored)


def test_interval_clamped_to_bounds() -> None:
    assert interval_minutes({"interval_minutes": 1}) == 5
    assert interval_minutes({"interval_minutes": 999999}) == 10080
    assert interval_minutes({}) == 360


def test_fetch_params_whitelists_fields() -> None:
    params = fetch_params(
        {
            "name": "生物科技日报素材",
            "keywords": ["生物科技"],
            "scopes": ["info"],
            "interval_minutes": 60,
            "enabled": True,
            "next_run_at": "2030-01-01T00:00:00+00:00",
            "id": "abcd",
        }
    )
    assert params["name"] == "生物科技日报素材"
    assert params["keywords"] == ["生物科技"]
    assert "interval_minutes" not in params
    assert "next_run_at" not in params


def test_parse_dt_accepts_z_suffix() -> None:
    assert parse_dt("2026-09-30T12:00:00Z") == NOW
    assert parse_dt("not-a-date") is None
    assert parse_dt(None) is None


class _FakeRow:
    def __init__(self, value):
        self.value = value


class _FakeSession:
    """最小会话桩:只服务 settings 读写,用于验证 tick 的提交与写回。"""

    def __init__(self, value):
        self.row = _FakeRow(value)
        self.commits = 0
        self.flushes = 0

    async def get(self, _model, _key):
        return self.row

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1


class _FakeScope:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_exc):
        return False


class _FakeExecutor:
    def __init__(self, *, busy: bool = False):
        self.busy = busy
        self.calls: list[tuple[str, dict]] = []

    async def submit(self, _session, kind, params):
        if self.busy:
            raise RuntimeError("已有同类任务在运行中: abc")
        self.calls.append((kind, params))
        return types.SimpleNamespace(id="job-123")


async def test_tick_submits_due_schedule_and_commits(monkeypatch) -> None:
    stored = {
        "schedules": [
            {
                "id": "s1",
                "name": "探针",
                "keywords": ["k"],
                "enabled": True,
                "interval_minutes": 60,
                "next_run_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            }
        ]
    }
    session = _FakeSession(stored)
    monkeypatch.setattr(schedules, "session_scope", lambda: _FakeScope(session))
    executor = _FakeExecutor()

    triggered = await schedules.CollectionScheduler(executor).tick()

    assert triggered == ["s1"]
    assert executor.calls[0][0] == "fetch"
    assert executor.calls[0][1]["name"] == "探针"
    # 关键回归点:session_scope 不自动提交,不 commit 会导致 next_run_at 不推进、反复触发
    assert session.commits == 1
    item = session.row.value["schedules"][0]
    assert item["last_job_id"] == "job-123"
    assert parse_dt(item["next_run_at"]) - parse_dt(item["last_run_at"]) == timedelta(minutes=60)


async def test_tick_skips_when_same_kind_running(monkeypatch) -> None:
    stored = {
        "schedules": [
            {
                "id": "s2",
                "name": "探针2",
                "keywords": ["k"],
                "enabled": True,
                "interval_minutes": 30,
                "next_run_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
            }
        ]
    }
    session = _FakeSession(stored)
    monkeypatch.setattr(schedules, "session_scope", lambda: _FakeScope(session))
    executor = _FakeExecutor(busy=True)

    triggered = await schedules.CollectionScheduler(executor).tick()

    assert triggered == []
    item = session.row.value["schedules"][0]
    assert item.get("last_job_id") is None
    assert item["last_skip"]["reason"].startswith("已有同类任务在运行中")
    assert session.commits == 1
