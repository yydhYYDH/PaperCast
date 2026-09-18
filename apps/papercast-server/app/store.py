"""运行状态存储：内存 + run.json 落盘（单进程足够，重启可恢复）。"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Optional

from .models import PaperRun

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


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
        """启动时恢复。running 的 run 一律降级为 failed —— 进程已经丢了，不能假装还在跑。"""
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
                if run.status in ("running", "queued"):
                    run.status = "failed"
                    run.error = {"code": "INTERRUPTED", "message": "后端进程重启，该运行已中止"}
                    for st in run.stages:
                        if st.status in ("running", "waiting"):
                            st.status = "failed"
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
        """把 /artifacts/<run>/<rel> 解析成真实路径，挡掉路径穿越与内部文件。"""
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
