"""StageTracker 单元测试:阶段耗时、早退标记与节流上报。"""

from __future__ import annotations

from app.services.stage_tracker import StageTracker


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += seconds


def test_plan_keeps_order_and_pending_state():
    tracker = StageTracker(plan=("setup", "collect", "store"))
    stages = tracker.stages()
    assert [stage["key"] for stage in stages] == ["setup", "collect", "store"]
    assert [stage["label"] for stage in stages] == ["配置", "采集", "入库"]
    assert {stage["status"] for stage in stages} == {"pending"}


def test_start_finish_records_seconds_and_message():
    clock = FakeClock()
    tracker = StageTracker(plan=("collect",), clock=clock)
    tracker.start("collect", "并发抓取 11 个信源")
    clock.tick(2.5)
    tracker.finish("collect", "抓取 132 条", fetched=132)

    stage = tracker.stages()[0]
    assert stage["status"] == "success"
    assert stage["seconds"] == 2.5
    assert stage["message"] == "抓取 132 条"
    assert stage["counters"] == {"fetched": 132}
    assert tracker.snapshot()["stage_index"] == 1
    assert tracker.snapshot()["stage_total"] == 1


def test_skip_rest_only_touches_pending_stages():
    clock = FakeClock()
    tracker = StageTracker(plan=("setup", "collect", "store"), clock=clock)
    tracker.start("setup")
    clock.tick(0.5)
    tracker.finish("setup")
    tracker.start("collect")
    tracker.fail("collect", "抓取异常")
    tracker.skip_rest("未执行")

    statuses = {stage["key"]: stage["status"] for stage in tracker.stages()}
    assert statuses == {"setup": "success", "collect": "error", "store": "skipped"}


def test_updates_are_throttled_but_stage_changes_force_emit():
    clock = FakeClock()
    emitted: list[dict] = []
    tracker = StageTracker(plan=("enrich", "store"), clock=clock, on_update=emitted.append)

    tracker.start("enrich", "开始富化")
    assert len(emitted) == 1

    tracker.update("富化 1/10")
    tracker.update("富化 2/10")
    assert len(emitted) == 1

    clock.tick(1.2)
    tracker.update("富化 3/10")
    assert len(emitted) == 2

    tracker.start("store", "写入素材库")
    assert len(emitted) == 3
    assert emitted[-1]["stage"] == "store"


def test_add_source_and_attach_merge_into_result():
    tracker = StageTracker(plan=("collect",))
    tracker.start("collect")
    tracker.add_source({"source_id": 7, "name": "arXiv", "fetched": 50})
    tracker.finish("collect")

    result = tracker.attach({"new_items": 3})
    assert result["new_items"] == 3
    assert result["stages"][0]["key"] == "collect"
    assert result["sources_detail"] == [{"source_id": 7, "name": "arXiv", "fetched": 50}]
    assert result["elapsed_seconds"] >= 0


def test_note_updates_only_live_message():
    clock = FakeClock()
    emitted: list[dict] = []
    tracker = StageTracker(plan=("collect",), clock=clock, on_update=emitted.append)
    tracker.start("collect")
    tracker.update("抓取中")
    clock.tick(1.5)
    tracker.note("[arXiv·paper] 抓取 50 条 (1.20s)")

    assert emitted[-1]["last_log"] == "[arXiv·paper] 抓取 50 条 (1.20s)"
    assert emitted[-1]["message"] == "抓取中"
    assert tracker.stages()[0]["message"] == "抓取中"
