"""PaperCast 后端：FastAPI 应用（实现前端 papercast 已声明的 /api/runs 契约）。"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .config import settings
from .models import CreateRunRequest, GateRequest, PaperRun, SourceInput, new_run
from .pipeline import Pipeline
from .store import RunStore

VERSION = "0.1.0"
STARTED_AT = time.time()

store = RunStore(settings.data_dir, settings.upload_dir)
pipeline = Pipeline(store, settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.load_all()
    yield


app = FastAPI(title="PaperCast API", version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def fail(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    """统一错误格式：{ error: { code, message, details } }"""
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details}})


# --------------------------------------------------------------------------- #
# 契约：/api/runs
# --------------------------------------------------------------------------- #

@app.post("/api/runs")
async def create_run(req: CreateRunRequest) -> PaperRun:
    src = req.source
    if src.kind in ("pdf", "latex"):
        if store.upload_path(src.value) is None and not Path(src.value).expanduser().exists():
            raise HTTPException(status_code=400, detail=f"上传不存在或已过期：{src.value}")
    if src.kind == "arxiv" and not src.value.strip():
        raise HTTPException(status_code=400, detail="arXiv 标识为空")

    title = (src.title or "").strip()
    if not title:
        up = store.upload_meta(src.value) if src.kind in ("pdf", "latex") else {}
        title = up.get("filename") or (f"arXiv {src.value}" if src.kind == "arxiv" else "未命名论文")

    run = new_run(src, req.config or __import__("app.models", fromlist=["RunConfig"]).RunConfig(), title)
    store.add(run)
    pipeline.start(run, {})
    return run


@app.get("/api/runs")
async def list_runs() -> list[PaperRun]:
    return store.list()


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> PaperRun:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run 不存在")
    return run


@app.post("/api/runs/{run_id}/cancel", status_code=204)
async def cancel_run(run_id: str) -> JSONResponse:
    if store.get(run_id) is None:
        raise HTTPException(status_code=404, detail="run 不存在")
    pipeline.cancel(run_id)
    return JSONResponse(status_code=204, content=None)


@app.post("/api/runs/{run_id}/stages/{stage_id}/gate", status_code=204)
async def resolve_gate(run_id: str, stage_id: str, req: GateRequest) -> JSONResponse:
    ok, msg = pipeline.resolve_gate(run_id, stage_id, req.optionId, req.note)
    if not ok:
        status = 404 if "不存在" in msg else 409
        return fail(status, "GATE_REJECTED", msg)
    return JSONResponse(status_code=204, content=None)


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run 不存在")

    async def gen():
        q = pipeline.bus.subscribe(run_id)
        try:
            yield f"data: {json.dumps({'type': 'snapshot', 'run': run.model_dump(exclude_none=True)}, ensure_ascii=False)}\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:
            pipeline.bus.unsubscribe(run_id, q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# --------------------------------------------------------------------------- #
# 上传 / 产物 / 环境
# --------------------------------------------------------------------------- #

@app.post("/api/uploads")
async def upload(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    limit = settings.max_upload_mb * 1024 * 1024
    if len(data) > limit:
        return fail(400, "UPLOAD_TOO_LARGE", f"文件超过 {settings.max_upload_mb} MB")
    if not data:
        return fail(400, "UPLOAD_EMPTY", "空文件")
    return store.store_upload(file.filename or "upload.bin", data)


@app.get("/artifacts/{run_id}/{rel:path}")
async def artifact(run_id: str, rel: str) -> FileResponse:
    if store.get(run_id) is None:
        raise HTTPException(status_code=404, detail="run 不存在")
    target = store.resolve_artifact(run_id, rel)
    if target is None:
        raise HTTPException(status_code=404, detail="产物不存在")
    media = {
        ".md": "text/markdown; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".png": "image/png",
        ".jpg": "image/jpeg",
    }.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(target, media_type=media)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": VERSION, "uptimeSec": round(time.time() - STARTED_AT, 1)}


@app.get("/api/env")
async def api_env() -> dict:
    """引擎与环境状态：全部真实探测，不写死。"""
    from .config import find_cjk_font, has_cjk_glyphs

    latex = shutil.which("pdflatex") or shutil.which("xelatex") or shutil.which("latexmk") or ""
    gpu = _gpu_state()
    mcp: dict[str, Any] = {"base": settings.xhs_mcp_base, "reachable": False, "loggedIn": False, "account": ""}
    try:
        async with httpx.AsyncClient(timeout=6.0, trust_env=False) as cx:
            h = await cx.get(f"{settings.xhs_mcp_base}/health")
            mcp["reachable"] = h.status_code == 200
            if mcp["reachable"]:
                r = await cx.get(f"{settings.xhs_mcp_base}/api/v1/login/status")
                d = (r.json() or {}).get("data") or {}
                mcp["loggedIn"] = bool(d.get("is_logged_in"))
                mcp["account"] = d.get("username") or ""
    except Exception as e:
        mcp["error"] = f"{type(e).__name__}: {e}"

    return {
        "intake": {
            "engine": settings.intake_engine,
            "gpu": gpu["usable"],
            "gpuDetail": gpu["detail"],
            "mineru": bool(shutil.which("mineru")),
            "ocr": bool(shutil.which("tesseract")),
        },
        "latex": {"engine": latex or None, "mode": "compile" if latex else "source-only"},
        "llm": {
            "configured": bool(settings.llm_api_key),
            "baseUrl": settings.llm_base_url,
            "model": settings.llm_model,
        },
        "cards": {
            "enabled": settings.cards_enabled,
            "chrome": settings.chrome or None,
            "cjkFont": settings.cjk_font or find_cjk_font() or None,
            "cjkFontUsable": has_cjk_glyphs(settings.cjk_font or find_cjk_font()),
        },
        "publish": {"xiaohongshu": mcp},
        "dataDir": str(settings.data_dir),
        "runs": len(store.list()),
    }


_GPU_CACHE: dict[str, Any] = {}


def _gpu_state() -> dict:
    """nvidia-smi 存在 ≠ GPU 可用（本机就是被系统禁掉的）。真实探测一次并缓存。"""
    if _GPU_CACHE:
        return _GPU_CACHE
    smi = shutil.which("nvidia-smi")
    if not smi:
        _GPU_CACHE.update(usable=False, detail="未安装 nvidia-smi")
        return _GPU_CACHE
    try:
        p = subprocess.run([smi, "-L"], capture_output=True, text=True, timeout=8)
        if p.returncode == 0 and "GPU" in p.stdout:
            _GPU_CACHE.update(usable=True, detail=p.stdout.strip().splitlines()[0][:120])
        else:
            _GPU_CACHE.update(usable=False, detail=(p.stderr or p.stdout).strip()[:160] or "nvidia-smi 返回非 0")
    except Exception as e:
        _GPU_CACHE.update(usable=False, detail=f"{type(e).__name__}: {e}")
    return _GPU_CACHE


@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return fail(exc.status_code, f"HTTP_{exc.status_code}", str(exc.detail))


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    return fail(500, type(exc).__name__, str(exc)[:400])
