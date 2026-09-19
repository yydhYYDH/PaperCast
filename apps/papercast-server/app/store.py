"""运行状态存储：内存 + run.json 落盘（单进程足够，重启可恢复）。"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Optional

from .models import LogLine, PaperRun, Stage, StageCheck, now_ts

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

#: 进程重启后**不可能**再有活跃任务的 run / stage 状态。
#: 执行任务（asyncio.Task）只活在内存里，重启即消失 —— 盘上写着 running/queued/waiting 的一律是僵尸。
INTERRUPTED_RUN_STATUSES = ("queued", "running", "waiting")
INTERRUPTED_STAGE_STATUSES = ("running", "waiting")

#: 写进 stage.logs / stage.checks 的话（前端原样展示，必须说清「为什么停」和「产物还在不在」）
INTERRUPTED_TEXT = (
    "服务重启导致中断：执行任务只在后端内存里，重启后没有任何协程会继续推进本次运行。"
    "已落盘的产物保留在该 run 目录（run.json 里登记的 artifacts 与磁盘文件都不会删除）；"
    "要继续请重新发起一次运行。"
)
INTERRUPTED_CHECK_LABEL = "服务重启中断"


def _upsert_check(stage: Stage, label: str, state: str, detail: str) -> None:
    """与 StageContext.check 同样的「同 label 覆盖」语义，避免反复重启叠一堆同名 check。"""
    checks = list(stage.checks or [])
    checks = [c for c in checks if c.label != label]
    checks.append(StageCheck(label=label, state=state, detail=detail))  # type: ignore[arg-type]
    stage.checks = checks


def mark_interrupted(run: PaperRun) -> bool:
    """把「重启前没跑完」的 run 标成明确终态，并写清原因与产物去向。返回是否真的改过。

    B1 修复（2026-09-19）：原来 load_all 只降级 running / queued，漏了 waiting —— 停在人工闸门上的
    run（stage.status == "waiting"）重启后照旧显示「等待人工确认」，而服务端根本没有协程在等它；
    此时前端放行闸门会被 204 假成功接走，run 永久卡在 waiting、产物停在「素材包已落盘、无回执」
    （实测 run_9105dc770228）。run.status 只复用前端契约里最接近的 failed，**不新增枚举值**。
    """
    if run.status not in INTERRUPTED_RUN_STATUSES:
        return False
    run.status = "failed"  # RunStatus 只有 queued/running/waiting/done/failed，复用 failed + 文字说明
    run.error = {"code": "INTERRUPTED", "message": "后端进程重启，该运行已中止（产物保留在 run 目录）"}
    hit = [st for st in run.stages if st.status in INTERRUPTED_STAGE_STATUSES]
    if not hit:
        # 理论上不会发生（run 卡住时总有一个 running/waiting 的阶段），兜底也要留下说明
        nxt = next((st for st in run.stages if st.status == "pending"), None)
        hit = [nxt] if nxt is not None else []
    for st in hit:
        if st.status in INTERRUPTED_STAGE_STATUSES:
            st.status = "failed"
            st.endedAt = st.endedAt or now_ts()
        st.logs.append(LogLine(ts=now_ts(), level="err", text=INTERRUPTED_TEXT))
        _upsert_check(st, INTERRUPTED_CHECK_LABEL, "fail", INTERRUPTED_TEXT)
    return True


class RunStore:
    def __init__(self, root: Path, upload_root: Path) -> None:
        self.root = Path(root)
        self.upload_root = Path(upload_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self._runs: dict[str, PaperRun] = {}
        self._lock = threading.RLock()

    # ---------- 生命周期 ----------

    def load_all(self) -> None:
        """启动时恢复。**执行任务只在内存里，重启后不可能还有活跃的 run** ——
        queued / running / waiting 一律按 mark_interrupted 降级为终态 failed，并把说明与产物去向
        写进该阶段的 logs/checks，然后**落盘**（否则盘上那份 run.json 还是 waiting，每次启动都要重铺一遍）。
        """
        with self._lock:
            self._runs.clear()
            for d in sorted(self.root.iterdir() if self.root.is_dir() else []):
                f = d / "run.json"
                if not f.is_file():
                    continue
                try:
                    run = PaperRun.model_validate_json(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if mark_interrupted(run):
                    # 落盘失败（目录被删/只读）不能拖垮启动：内存里已经是对的终态了
                    try:
                        self.save(run)
                    except OSError:
                        pass
                self._runs[run.id] = run

    # ---------- 读写 ----------

    def get(self, run_id: str) -> Optional[PaperRun]:
        with self._lock:
            return self._runs.get(run_id)

    def list(self) -> list[PaperRun]:
        with self._lock:
            return sorted(self._runs.values(), key=lambda r: r.createdAt, reverse=True)

    def add(self, run: PaperRun) -> None:
        with self._lock:
            self._runs[run.id] = run
        self.save(run)

    def save(self, run: PaperRun) -> None:
        """原子写：先写临时文件再 rename，避免半截 JSON。"""
        d = self.dir(run.id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "run.json.tmp"
        tmp.write_text(run.model_dump_json(exclude_none=True), encoding="utf-8")
        os.replace(tmp, d / "run.json")

    # ---------- 目录 ----------

    def dir(self, run_id: str) -> Path:
        return self.root / run_id

    def stage_dir(self, run_id: str, stage_id: str) -> Path:
        p = self.dir(run_id) / stage_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    #: 运行目录里的内部记账文件，不对 /artifacts 暴露
    DENY_ARTIFACTS = {"run.json", "run.json.tmp", "error.log"}

    def resolve_artifact(self, run_id: str, rel: str) -> Optional[Path]:
        """把 /artifacts/<run>/<rel> 解析成真实路径，挡掉路径穿越与内部文件。

        run_id 也要洗：HTTP 路由靠 store.get() 的前置 404 兜着，但 load_all 只读目录里的
        run.json、不校验「文件里的 id == 目录名」，一份 id 为 "../" 的 run.json 就能把 base
        指到运行目录之外（2026-09-19 补的纵深防御）。
        """
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id or ""):
            return None
        base = self.dir(run_id).resolve()
        target = (base / rel).resolve()
        if not str(target).startswith(str(base) + os.sep) and target != base:
            return None
        if not target.is_file():
            return None
        if target.name in self.DENY_ARTIFACTS:
            return None
        return target

    # ---------- 上传 ----------

    def store_upload(self, filename: str, data: bytes) -> dict:
        import hashlib
        import uuid

        safe = SAFE_NAME.sub("_", Path(filename).name) or "upload.bin"
        up_id = "up_" + uuid.uuid4().hex[:12]
        d = self.upload_root / up_id
        d.mkdir(parents=True, exist_ok=True)
        (d / safe).write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        meta = {"uploadId": up_id, "filename": safe, "bytes": len(data), "sha256": sha}
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return meta

    def upload_path(self, upload_id: str) -> Optional[Path]:
        d = self.upload_root / upload_id
        if not d.is_dir():
            return None
        for f in d.iterdir():
            if f.is_file() and f.name != "meta.json":
                return f
        return None

    def upload_meta(self, upload_id: str) -> dict:
        f = self.upload_root / upload_id / "meta.json"
        if f.is_file():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}
