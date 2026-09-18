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
        self, gate_id: str, label: str, detail: str, options: list[tuple[str, str, Optional[str]]]
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
        self.log("ok", f"闸门放行：{label} → {chosen}")
        return chosen or (options[0][0] if options else "continue")

    @property
    def cancelled(self) -> bool:
        return self.runner.is_cancelled(self.run.id)

    def gate_note(self) -> str:
        return (self.stage.gate.note if self.stage.gate and self.stage.gate.note else "") or ""


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
        self._cancelled: set[str] = set()

    # ---------- 闸门 ----------

    async def wait_gate(self, run_id: str, stage_id: str) -> None:
        ev = self._gate_events.setdefault(f"{run_id}:{stage_id}", asyncio.Event())
        await ev.wait()
        self._gate_events.pop(f"{run_id}:{stage_id}", None)

    def resolve_gate(self, run_id: str, stage_id: str, option_id: str, note: Optional[str] = None) -> tuple[bool, str]:
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
            from .modules.publish import run_publish
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
