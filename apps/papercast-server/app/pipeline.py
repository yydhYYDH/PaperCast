"""流水线编排：阶段推进、日志、闸门、取消、SSE 事件。"""

from __future__ import annotations

import asyncio
import traceback
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .config import Settings
from .llm import LLMClient
from .models import (
    Artifact,
    GateOption,
    LogLine,
    PaperRun,
    Stage,
    StageCheck,
    StageGate,
    now_ts,
)
from .store import RunStore


class EventBus:
    """单进程事件总线：每个 run 一组订阅队列，SSE 从这里取事件。"""

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subs.setdefault(run_id, []).append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(run_id)
        if subs and q in subs:
            subs.remove(q)

    def publish(self, run_id: str, event: dict) -> None:
        for q in list(self._subs.get(run_id, [])):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


class StageContext:
    """模块拿到的一切：目录、日志、产物、闸门。三模块共用这一个接口。"""

    def __init__(self, runner: "Pipeline", run: PaperRun, stage: Stage, shared: dict) -> None:
        self.runner = runner
        self.run = run
        self.stage = stage
        self.shared = shared
        self.store = runner.store
        self.settings = runner.settings
        self.llm = runner.llm
        self.work: Path = runner.store.stage_dir(run.id, stage.id)

    # ---- 日志 / 进度 ----

    def log(self, level: str, text: str) -> None:
        line = LogLine(ts=now_ts(), level=level, text=text)  # type: ignore[arg-type]
        self.stage.logs.append(line)
        self.store.save(self.run)
        self.runner.bus.publish(self.run.id, {"type": "log", "stageId": self.stage.id, "line": line.model_dump()})

    def progress(self, value: float) -> None:
        self.stage.progress = max(0.0, min(1.0, float(value)))
        self.store.save(self.run)
        self.runner.bus.publish(
            self.run.id,
            {"type": "stage", "stageId": self.stage.id, "status": self.stage.status, "progress": self.stage.progress},
        )

    # ---- 产物 ----

    def artifact(
        self,
        kind: str,
        label: str,
        rel: str,
        *,
        preview: bool = True,
        meta: Optional[dict[str, Any]] = None,
    ) -> Optional[Artifact]:
        """登记一个产物。rel 是相对阶段目录的路径。文件不存在就直接跳过（不登记假产物）。"""
        f = self.work / rel
        if not f.is_file():
            self.log("warn", f"产物缺失，未登记：{self.stage.id}/{rel}")
            return None
        art = Artifact(
            id=f"{self.stage.id}-{len(self.stage.artifacts) + 1}",
            stageId=self.stage.id,  # type: ignore[arg-type]
            kind=kind,  # type: ignore[arg-type]
            label=label,
            path=f".papercast/runs/{self.run.id}/{self.stage.id}/{rel}",
            url=f"/artifacts/{self.run.id}/{self.stage.id}/{rel}" if preview else None,
            bytes=f.stat().st_size,
            meta=meta,
        )
        self.stage.artifacts = [a for a in self.stage.artifacts if a.path != art.path] + [art]
        self.store.save(self.run)
        self.runner.bus.publish(self.run.id, {"type": "artifact", "stageId": self.stage.id, "artifact": art.model_dump()})
        return art

    def check(self, label: str, state: str, detail: str) -> None:
        if self.stage.checks is None:
            self.stage.checks = []
        self.stage.checks = [c for c in self.stage.checks if c.label != label]
        self.stage.checks.append(StageCheck(label=label, state=state, detail=detail))  # type: ignore[arg-type]
        self.store.save(self.run)

    # ---- 闸门 ----

    async def gate(
        self,
        gate_id: str,
        label: str,
        detail: str,
        options: list[tuple[str, str, Optional[str]]],
        default: Optional[str] = None,
    ) -> str:
        gate = StageGate(
            id=gate_id,
            label=label,
            detail=detail,
            options=[GateOption(id=o[0], label=o[1], hint=o[2]) for o in options],
            askedAt=now_ts(),
        )
        self.stage.gate = gate
        self.stage.status = "waiting"
        self.stage.progress = 1.0
        self.run.status = "waiting"
        self.store.save(self.run)
        self.log("warn", f"⏸ 等待人工闸门：{label}")
        self.runner.bus.publish(self.run.id, {"type": "gate", "stageId": self.stage.id, "gate": gate.model_dump()})
        await self.runner.wait_gate(self.run.id, self.stage.id)
        if self.cancelled:
            raise _Cancelled()
        chosen = self.stage.gate.resolved if self.stage.gate else None
        self.run.status = "running"
        self.stage.status = "running"
        self.store.save(self.run)
        if not chosen:
            chosen = pick_gate_choice(options, default)
            self.log("warn", f"闸门没拿到人工选择，按默认值放行：{label} → {chosen}（有副作用的闸门必须声明安全默认值）")
        self.log("ok", f"闸门放行：{label} → {chosen}")
        return chosen

    @property
    def cancelled(self) -> bool:
        return self.runner.is_cancelled(self.run.id)

    def gate_note(self) -> str:
        return (self.stage.gate.note if self.stage.gate and self.stage.gate.note else "") or ""


def pick_gate_choice(
    options: list[tuple[str, str, Optional[str]]], default: Optional[str] = None
) -> str:
    """人工没给出选择时的取值 —— 这里必须 **fail-closed**。

    原来直接退到 options[0][0]，而发布闸门的 options[0] 正是「确认发布」，
    等于把「闸门异常 / 没等到选择」变成「默认真投递」，方向是反的（2026-09-19 修）。
    现在：调用方声明的安全默认值 > 第一个选项；一个选项都没有时退到 skip
    （"不做那件事"），而不是 continue。真正有副作用的那一步还必须在调用方
    再走一道白名单校验，见 app/modules/publish.py 的 _is_confirmed。
    """
    if default:
        return default
    ids = [o[0] for o in options]
    return ids[0] if ids else "skip"


class _Cancelled(Exception):
    pass


class Pipeline:
    def __init__(self, store: RunStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings
        self.llm = LLMClient(settings)
        self.bus = EventBus()
        self._tasks: dict[str, asyncio.Task] = {}
        self._gate_events: dict[str, asyncio.Event] = {}
        # 真的有协程挂在 wait_gate 上的闸门（key = "<run_id>:<stage_id>"）。
        # 只看 _gate_events 不够：cancel() 会顺手 setdefault 造一个事件出来，那是「解开」不是「有人在等」。
        self._gate_waiters: set[str] = set()
        self._cancelled: set[str] = set()

    # ---------- 闸门 ----------

    async def wait_gate(self, run_id: str, stage_id: str) -> None:
        """挂住当前协程等闸门放行。**进了这里才算「真有人在等」** —— resolve_gate 靠它判断闸门是不是活的。

        finally 里清理：被 cancel 时（进程结束 / 人工取消）不能留下一个「看着在等、其实没人」的假状态。
        """
        key = f"{run_id}:{stage_id}"
        ev = self._gate_events.setdefault(key, asyncio.Event())
        self._gate_waiters.add(key)
        try:
            await ev.wait()
        finally:
            self._gate_waiters.discard(key)
            self._gate_events.pop(key, None)

    def has_live_task(self, run_id: str) -> bool:
        """本进程里这个 run 还有活跃的执行协程吗？（服务重启后必然没有：task 只在内存里）"""
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    def is_gate_alive(self, run_id: str, stage_id: str) -> bool:
        """有协程正挂在这个闸门上等放行吗？"""
        return f"{run_id}:{stage_id}" in self._gate_waiters

    #: 闸门没有活跃协程时的答复（前端直接展示，必须说清「该怎么办」）
    GATE_INTERRUPTED_MSG = (
        "本次运行已随服务重启中断，请重新发起："
        "服务重启会丢掉内存里的执行任务，没有任何协程还会继续推进这个 run"
        "（已落盘的产物保留在该 run 目录，不会被删除）"
    )
    GATE_NO_WAITER_MSG = "该闸门当前没有等待中的执行协程（阶段可能已推进），拒绝放行以免造成假成功"

    def resolve_gate(self, run_id: str, stage_id: str, option_id: str, note: Optional[str] = None) -> tuple[bool, str]:
        """放行闸门。**只有真的把等待中的协程唤醒，才算成功。**

        B1 修复（2026-09-19）：原来这里只改 run.json 里的 gate.resolved，不检查是否有人等 ——
        后端重启后，停在闸门上的 run 会显示「等待人工确认」，但内存里的执行任务早就没了；
        此时放行会返回 204「成功」，而 run 永久卡在 waiting（实测 run_9105dc770228 就是这样死的，
        产物停在「素材包已落盘、无回执」）。现在检查不到等待中的协程就明确报错。
        """
        run = self.store.get(run_id)
        if run is None:
            return False, "run 不存在"
        stage = next((s for s in run.stages if s.id == stage_id), None)
        if stage is None or stage.gate is None:
            return False, "该阶段没有待放行的闸门"
        if stage.gate.resolved:
            return False, f"闸门已放行（{stage.gate.resolved}）"
        valid = {o.id for o in stage.gate.options}
        if option_id not in valid:
            return False, f"非法选项 {option_id}，可选 {sorted(valid)}"

        # ---- 闸门必须是「活的」：没有协程在等 → 拒绝，绝不给 204 假成功 ----
        if not self.is_gate_alive(run_id, stage_id):
            if not self.has_live_task(run_id):
                return False, self.GATE_INTERRUPTED_MSG
            return False, f"{self.GATE_NO_WAITER_MSG}（run.status={run.status}，{stage.id}.status={stage.status}）"

        stage.gate.resolved = option_id
        stage.gate.note = note
        self.store.save(run)
        self._gate_events.setdefault(f"{run_id}:{stage_id}", asyncio.Event()).set()
        return True, "ok"

    # ---------- 取消 ----------

    def is_cancelled(self, run_id: str) -> bool:
        return run_id in self._cancelled

    def cancel(self, run_id: str) -> bool:
        run = self.store.get(run_id)
        if run is None:
            return False
        self._cancelled.add(run_id)
        # 卡在闸门上时先解开闸门，让协程继续跑并撞上取消检查
        for stage in run.stages:
            if stage.status == "waiting":
                self._gate_events.setdefault(f"{run_id}:{stage.id}", asyncio.Event()).set()
        task = self._tasks.get(run_id)
        if task and not task.done():
            task.cancel()
        return True

    # ---------- 执行 ----------

    def start(self, run: PaperRun, shared: Optional[dict] = None) -> None:
        self._cancelled.discard(run.id)
        self._tasks[run.id] = asyncio.create_task(self._execute(run, shared or {}))

    async def _execute(self, run: PaperRun, shared: dict) -> None:
        """阶段编排。任何异常都必须变成可见的失败状态 —— 不允许静默死在 queued。"""
        try:
            await self._execute_inner(run, shared)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # 编排层自己的 bug，也要如实反映到 run 上
            run.status = "failed"
            run.error = {"code": type(e).__name__, "message": str(e)[:300]}
            for st in run.stages:
                if st.status in ("running", "pending"):
                    st.status = "failed"
                    st.logs.append(LogLine(ts=now_ts(), level="err", text=f"编排异常：{type(e).__name__}: {e}"))
                    break
            self.store.save(run)
            self._publish_run(run)
            self._trace(run, e)

    async def _execute_inner(self, run: PaperRun, shared: dict) -> None:
        try:
            from .modules.generate import run_article, run_understand
            from .modules.intake import run_intake
            from .modules.poster_stage import run_poster
            from .modules.publish import run_publish
            from .modules.video import run_video
        except Exception as e:
            run.status = "failed"
            run.error = {"code": "MODULE_IMPORT_FAILED", "message": f"{type(e).__name__}: {e}"}
            for st in run.stages:
                if st.status == "pending":
                    st.status = "failed"
                    st.logs.append(LogLine(ts=now_ts(), level="err", text=f"模块加载失败：{e}"))
            self.store.save(run)
            self._publish_run(run)
            return

        plan: list[tuple[str, Callable[[StageContext], Awaitable[None]]]] = [
            ("intake", run_intake),
            ("understand", run_understand),
            ("article", run_article),
            ("poster", run_poster),
            ("video", run_video),
            ("publish", run_publish),
        ]
        run.status = "running"
        self.store.save(run)
        self._publish_run(run)

        for stage_id, fn in plan:
            stage = next((s for s in run.stages if s.id == stage_id), None)
            if stage is None or stage.status == "skipped":
                continue
            if self.is_cancelled(run.id):
                stage.status = "failed"
                run.status = "failed"
                run.error = {"code": "CANCELLED", "message": "运行被人工取消"}
                self.store.save(run)
                self._publish_run(run)
                return

            stage.status = "running"
            stage.startedAt = now_ts()
            stage.progress = 0.02
            stage.logs = []
            stage.artifacts = []
            stage.checks = None
            self.store.save(run)
            self._publish_run(run)
            ctx = StageContext(self, run, stage, shared)

            try:
                await fn(ctx)
                if stage.status not in ("waiting",):
                    stage.status = "done"
                    stage.progress = 1.0
                stage.endedAt = now_ts()
                self.store.save(run)
                self._publish_run(run)
            except asyncio.CancelledError:
                stage.status = "failed"
                stage.endedAt = now_ts()
                if not any(l.text.startswith("已取消") for l in stage.logs):
                    stage.logs.append(LogLine(ts=now_ts(), level="err", text="已取消：进程被中止"))
                run.status = "failed"
                run.error = {"code": "CANCELLED", "message": "运行被人工取消"}
                self.store.save(run)
                self._publish_run(run)
                raise
            except _Cancelled:
                stage.status = "failed"
                stage.endedAt = now_ts()
                stage.logs.append(LogLine(ts=now_ts(), level="err", text="已取消：闸门期间被中止"))
                run.status = "failed"
                run.error = {"code": "CANCELLED", "message": "运行被人工取消"}
                self.store.save(run)
                self._publish_run(run)
                return
            except Exception as e:
                code = getattr(e, "code", type(e).__name__)
                message = getattr(e, "message", str(e))
                stage.status = "failed"
                stage.endedAt = now_ts()
                stage.logs.append(LogLine(ts=now_ts(), level="err", text=f"{stage.label} 失败：{message}"))
                run.status = "failed"
                run.error = {"code": str(code), "message": str(message)}
                self.store.save(run)
                self.bus.publish(run.id, {"type": "error", "stageId": stage.id, "error": run.error})
                self._publish_run(run)
                self._trace(run, e)
                return

        run.status = "done"
        self.store.save(run)
        self.bus.publish(run.id, {"type": "done", "status": "done"})
        self._publish_run(run)
        self._tasks.pop(run.id, None)

    def _trace(self, run: PaperRun, e: Exception) -> None:
        d = self.store.dir(run.id)
        try:
            (d / "error.log").write_text(
                "".join(traceback.format_exception(type(e), e, e.__traceback__)), encoding="utf-8"
            )
        except OSError:
            pass

    def _publish_run(self, run: PaperRun) -> None:
        self.bus.publish(run.id, {"type": "snapshot", "run": run.model_dump(exclude_none=True)})
