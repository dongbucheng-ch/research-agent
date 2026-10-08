"""采集流水线硬约束:回看窗口 ≤48h、入库门槛 ≥75、候选/富化上限 ≤500。"""

import pytest
from pydantic import ValidationError

from app.schemas.config import GeneralSettingsIn
from app.schemas.content import FetchTriggerIn
from app.schemas.schedule import ScheduleIn, ScheduleUpdate
from app.services.app_settings import get_general_config


def test_fetch_trigger_defaults_and_bounds() -> None:
    payload = FetchTriggerIn(keywords=["agent"])
    assert payload.lookback_hours == 24
    assert payload.min_score == 75
    assert FetchTriggerIn(keywords=["agent"], lookback_hours=48, min_score=75).min_score == 75
    with pytest.raises(ValidationError):
        FetchTriggerIn(keywords=["agent"], lookback_hours=49)
    with pytest.raises(ValidationError):
        FetchTriggerIn(keywords=["agent"], min_score=74)


def test_schedule_schema_bounds() -> None:
    schedule = ScheduleIn(name="每日采集", keywords=["agent"])
    assert schedule.lookback_hours == 24
    assert schedule.min_score == 75
    with pytest.raises(ValidationError):
        ScheduleIn(name="每日采集", keywords=["agent"], lookback_hours=72)
    with pytest.raises(ValidationError):
        ScheduleIn(name="每日采集", keywords=["agent"], min_score=60)
    assert ScheduleUpdate(lookback_hours=48, min_score=100).min_score == 100
    with pytest.raises(ValidationError):
        ScheduleUpdate(lookback_hours=100)
    with pytest.raises(ValidationError):
        ScheduleUpdate(min_score=0)


def test_general_settings_enrich_limit_bounds() -> None:
    assert GeneralSettingsIn(fetch_lookback_hours=48).fetch_lookback_hours == 48
    assert GeneralSettingsIn(enrich_max_items=1).enrich_max_items == 1
    assert GeneralSettingsIn(enrich_max_items=500).enrich_max_items == 500
    with pytest.raises(ValidationError):
        GeneralSettingsIn(enrich_max_items=0)
    with pytest.raises(ValidationError):
        GeneralSettingsIn(enrich_max_items=501)
    with pytest.raises(ValidationError):
        GeneralSettingsIn(fetch_lookback_hours=49)


class _FakeRow:
    def __init__(self, value) -> None:
        self.value = value


class _FakeSession:
    """最小会话桩:只服务 settings 读取,用于验证存量配置的收敛。"""

    def __init__(self, value) -> None:
        self.row = _FakeRow(value)

    async def get(self, _model, _key):
        return self.row


async def test_general_config_clamps_legacy_values() -> None:
    session = _FakeSession({"fetch_lookback_hours": 720, "enrich_max_items": 0})
    config = await get_general_config(session)  # type: ignore[arg-type]
    assert config["fetch_lookback_hours"] == 48
    assert config["enrich_max_items"] == 100  # 历史「0 = 不限」按默认 100 处理

    session = _FakeSession({"enrich_max_items": 2000})
    config = await get_general_config(session)  # type: ignore[arg-type]
    assert config["enrich_max_items"] == 500
