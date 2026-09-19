"""B1：后端重启后卡在闸门上的 run 必须明确中断，闸门放行必须报错而不是「204 假成功」。

实测背景（run_9105dc770228 / docs/11-verification-6-stages.md §8-B1）：
前 5 段 done，publish 卡 waiting；重启后端后再 POST 闸门仍返回 204，但没有任何协程被唤醒，
run 永久停在 waiting、产物停在「素材包已落盘、无回执」。

根因两条，这里各钉一条：
① pipeline._tasks / _gate_events 只在内存里，重启即丢；resolve_gate 对「没人等的闸门」照样置
   gate.resolved 并返回成功 → 现在没有等待中的协程就必须返回错误（见 app/pipeline.py）；
② load_all() 只降级 running / queued，漏了 waiting（停在闸门上的 run 正是 waiting）→ 现在
   waiting 也标成终态 failed 并写清「服务重启导致中断 + 产物保留在 run 目录」（app/store.py）。

不联网、不起服务、不碰真实 var/runs（全部走 tmp_path）。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.config import Settings
from app.models import LogLine
from app.pipeline import Pipeline, StageContext
from app.store import INTERRUPTED_CHECK_LABEL, INTERRUPTED_TEXT, RunStore


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "runs", tmp_path / "uploads")


@pytest.fixture
def pipeline(store, tmp_path):
    # Settings 只被 Pipeline 交给 LLMClient 存着（不会发请求），显式指向 tmp 免得误用真实目录
    s = Settings(data_dir=tmp_path / "runs", upload_dir=tmp_path / "uploads")
    return Pipeline(store, s)


def _gate_resolved_on_disk(store, run_id, stage_id="understand"):
    """run.json 里的 gate.resolved（写盘走 exclude_none，未放行时这个键根本不存在 → None）。"""
    raw = json.loads((store.dir(run_id) / "run.json").read_text(encoding="utf-8"))
    return next(s for s in raw["stages"] if s["id"] == stage_id)["gate"].get("resolved")


# --------------------------------------------------------------------------- #
# ① resolve_gate：没有协程在等 → 明确报错（不许 204 假成功）
# --------------------------------------------------------------------------- #

def test_resolve_gate_rejects_run_without_active_task(store, pipeline, make_run, park_at_gate):
    """重启后的典型状态：run.json 说 waiting，内存里没有任何任务 → 必须拒绝，且不改状态。"""
    run = make_run()
    stage = park_at_gate(run)
    store.add(run)

    ok, msg = pipeline.resolve_gate(run.id, "understand", "continue")

    assert ok is False, "没有活跃协程时放行闸门必须失败，否则就是 B1 的假成功"
    assert "重启" in msg and "重新发起" in msg, msg
    assert "不存在" not in msg, "这条错误对应 409（状态不允许），不该被 main.py 映射成 404"
    assert stage.gate.resolved is None
    assert _gate_resolved_on_disk(store, run.id) is None, "被拒绝的放行不许落盘"
    assert run.status == "waiting"


def test_resolve_gate_rejects_when_task_alive_but_nobody_waits(store, pipeline, make_run, park_at_gate):
    """任务活着、但这个阶段没人在等（阶段已推进 / 是别的阶段的旧闸门）→ 同样拒绝。"""
    run = make_run()
    park_at_gate(run)
    store.add(run)

    async def scenario():
        async def idle():
            await asyncio.sleep(30)

        task = asyncio.create_task(idle())
        pipeline._tasks[run.id] = task  # 只在这里白盒注入「本进程里该 run 还有活跃协程」
        try:
            return pipeline.resolve_gate(run.id, "understand", "continue")
        finally:
            task.cancel()

    ok, msg = asyncio.run(scenario())
    assert ok is False
    assert "没有等待中的执行协程" in msg, msg
    assert "重启" not in msg, "有活跃任务时不要误报成「重启中断」"


def test_resolve_gate_still_rejects_unknown_run_and_unknown_gate(store, pipeline, make_run):
    assert pipeline.resolve_gate("run_nope", "understand", "continue") == (False, "run 不存在")
    run = make_run()  # 没有任何闸门
    store.add(run)
    ok, msg = pipeline.resolve_gate(run.id, "understand", "continue")
    assert ok is False and msg == "该阶段没有待放行的闸门"


def test_resolve_gate_wakes_a_waiting_coroutine(store, pipeline, make_run):
    """正向对照：**真的**有协程在等时，放行依然成功、协程被唤醒、选项是人选的那个。"""
    run = make_run()
    stage = next(s for s in run.stages if s.id == "understand")
    store.add(run)

    async def scenario():
        ctx = StageContext(pipeline, run, stage, {})
        task = asyncio.create_task(
            ctx.gate(
                "digest",
                "确认论文理解层",
                "测试用闸门",
                [("continue", "确认并继续", None), ("revise", "补充要点后重跑", None)],
                default="revise",
            )
        )
        for _ in range(500):  # 等协程进入 wait_gate
            if pipeline.is_gate_alive(run.id, "understand"):
                break
            await asyncio.sleep(0.01)
        assert pipeline.is_gate_alive(run.id, "understand"), "协程没进 wait_gate"

        ok, msg = pipeline.resolve_gate(run.id, "understand", "continue")
        assert ok is True, msg
        assert msg == "ok"
        chosen = await asyncio.wait_for(task, timeout=5)
        assert chosen == "continue", "必须是人选的 continue，而不是安全默认值 revise"
        assert stage.gate.resolved == "continue"
        assert run.status == "running"
        assert not pipeline.is_gate_alive(run.id, "understand"), "唤醒后不该留下「有人在等」的假状态"

    asyncio.run(scenario())


def test_resolve_gate_rejects_repeat_and_illegal_option(store, pipeline, make_run, park_at_gate):
    run = make_run()
    park_at_gate(run)
    store.add(run)
    ok, msg = pipeline.resolve_gate(run.id, "understand", "whatever")
    assert ok is False and "非法选项" in msg
    assert pipeline.resolve_gate(run.id, "understand", "continue")[0] is False  # 仍无协程在等


# --------------------------------------------------------------------------- #
# ② load_all：启动扫描把僵尸 run 标成中断态（含落盘与 stage 说明）
# --------------------------------------------------------------------------- #

def test_load_all_marks_gate_waiting_run_interrupted(store, make_run, park_at_gate):
    run = make_run()
    stage = park_at_gate(run)
    stage.logs.append(LogLine(ts=1, level="warn", text="⏸ 等待人工闸门：确认论文理解层"))
    store.add(run)

    store._runs.clear()
    store.load_all()

    reloaded = store.get(run.id)
    assert reloaded.status == "failed", "重启后不可能还有活跃任务，不许继续显示 waiting"
    assert reloaded.error["code"] == "INTERRUPTED"
    assert "产物保留在 run 目录" in reloaded.error["message"]

    st = next(s for s in reloaded.stages if s.id == "understand")
    assert st.status == "failed"
    assert st.endedAt, "中断阶段要封尾时间"
    assert any("服务重启导致中断" in line.text for line in st.logs)
    assert any(line.level == "err" for line in st.logs if "服务重启导致中断" in line.text)
    check = next(c for c in st.checks if c.label == INTERRUPTED_CHECK_LABEL)
    assert check.state == "fail"
    assert "产物保留在该 run 目录" in check.detail
    # 后面没跑的阶段保持 pending（前端据此知道它们根本没开始），状态枚举不外扩
    assert next(s for s in reloaded.stages if s.id == "article").status == "pending"
    assert reloaded.status in ("queued", "running", "waiting", "done", "failed")

    # 落盘：不用等下一次启动才生效
    raw = json.loads((store.dir(run.id) / "run.json").read_text(encoding="utf-8"))
    assert raw["status"] == "failed" and raw["error"]["code"] == "INTERRUPTED"
    raw_understand = next(s for s in raw["stages"] if s["id"] == "understand")
    assert raw_understand["status"] == "failed"
    assert any(c["label"] == INTERRUPTED_CHECK_LABEL for c in raw_understand["checks"])

    # 幂等：再启动一次不会把同一句话叠两遍
    store._runs.clear()
    store.load_all()
    again = next(s for s in store.get(run.id).stages if s.id == "understand")
    assert sum(1 for c in again.checks if c.label == INTERRUPTED_CHECK_LABEL) == 1
    assert sum(1 for line in again.logs if line.text == INTERRUPTED_TEXT) == 1


def test_load_all_still_downgrades_running_run(store, make_run):
    run = make_run()
    run.status = "running"
    run.stages[0].status = "running"
    store.add(run)
    store._runs.clear()
    store.load_all()
    reloaded = store.get(run.id)
    assert reloaded.status == "failed" and reloaded.error["code"] == "INTERRUPTED"
    assert reloaded.stages[0].status == "failed"
    assert any(c.label == INTERRUPTED_CHECK_LABEL for c in reloaded.stages[0].checks)


@pytest.mark.parametrize("status", ["done", "failed"])
def test_load_all_leaves_terminal_runs_alone(store, make_run, status):
    run = make_run()
    run.status = status
    run.error = {"code": "KEEP_ME", "message": "已有错误"} if status == "failed" else None
    store.add(run)
    store._runs.clear()
    store.load_all()
    reloaded = store.get(run.id)
    assert reloaded.status == status
    if status == "failed":
        assert reloaded.error["code"] == "KEEP_ME", "已有错误不该被重启扫描覆盖"
    else:
        assert reloaded.error is None
    assert not any(c.label == INTERRUPTED_CHECK_LABEL for st in reloaded.stages for c in (st.checks or []))
