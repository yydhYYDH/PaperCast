"""B2：204 响应不许有响应体。

实测背景（docs/11-verification-6-stages.md §8-B2）：每次放行人工闸门，客户端拿到 204，
服务端却留下一条 ASGI ERROR：

    RuntimeError: Response content longer than Content-Length
    （app/main.py → starlette/responses.py → uvicorn/protocols/http/httptools_impl.py:548）

根因：app/main.py 用 JSONResponse(status_code=204, content=None)。JSONResponse 会把 None 渲染成
b"null"，而 204 的 Content-Length 是 0，uvicorn 于是抛运行时异常。这个假异常会盖住真异常
（排查 B1 时就被它盖住），所以两个 204 路由（cancel / gate）都必须返回**有空 body** 的 Response。

这里覆盖两层：① 两个路由的响应对象真的没有 body；② 闸门在「重启后没人等」时走的是 409 + detail，
而不是 204。不联网、不起服务、不改真实 var/runs。
"""

from __future__ import annotations

import asyncio
import importlib
import json

import pytest

from app.config import Settings
from app.models import GateRequest
from app.pipeline import Pipeline
from app.store import RunStore


@pytest.fixture
def main_mod():
    """导入 app/main.py。

    模块级会 new 一个 RunStore(settings.data_dir)（只是 mkdir 已存在的目录，不写数据），
    下面每个用例都把 main 的 store / pipeline 换成 tmp 里的替身，绝不读写真实 var/runs。
    """
    return importlib.import_module("app.main")


@pytest.fixture
def real_stack(tmp_path):
    store = RunStore(tmp_path / "runs", tmp_path / "uploads")
    pipeline = Pipeline(store, Settings(data_dir=tmp_path / "runs", upload_dir=tmp_path / "uploads"))
    return store, pipeline


def test_gate_success_response_is_204_without_body(main_mod, monkeypatch, make_run):
    run = make_run()

    class StubStore:
        def get(self, run_id):
            return run if run_id == run.id else None

    class StubPipeline:
        def resolve_gate(self, *a, **k):
            return True, "ok"

    monkeypatch.setattr(main_mod, "store", StubStore())
    monkeypatch.setattr(main_mod, "pipeline", StubPipeline())

    resp = asyncio.run(main_mod.resolve_gate(run.id, "understand", GateRequest(optionId="continue")))

    assert resp.status_code == 204
    assert resp.body == b"", (
        "204 必须没有响应体：JSONResponse(content=None) 会渲染成 b'null'，"
        "uvicorn 随即抛 RuntimeError: Response content longer than Content-Length"
    )


def test_cancel_response_is_204_without_body(main_mod, monkeypatch, make_run):
    run = make_run()

    class StubStore:
        def get(self, run_id):
            return run if run_id == run.id else None

    class StubPipeline:
        cancelled = []

        def cancel(self, run_id):
            self.cancelled.append(run_id)
            return True

    stub = StubPipeline()
    monkeypatch.setattr(main_mod, "store", StubStore())
    monkeypatch.setattr(main_mod, "pipeline", stub)

    resp = asyncio.run(main_mod.cancel_run(run.id))

    assert resp.status_code == 204
    assert resp.body == b""
    assert stub.cancelled == [run.id]


def test_gate_on_restarted_run_answers_409_with_readable_detail(main_mod, monkeypatch, real_stack, make_run, park_at_gate):
    """B1① 的 HTTP 面：重启后（内存里没有任务）放行闸门必须 4xx + 可读 detail，而不是 204。"""
    store, pipeline = real_stack
    run = make_run()
    park_at_gate(run)
    store.add(run)
    monkeypatch.setattr(main_mod, "store", store)
    monkeypatch.setattr(main_mod, "pipeline", pipeline)

    resp = asyncio.run(main_mod.resolve_gate(run.id, "understand", GateRequest(optionId="continue")))

    assert resp.status_code == 409, "假成功（204）等于把用户晾在 waiting 上"
    payload = json.loads(resp.body)
    assert payload["error"]["code"] == "GATE_REJECTED"
    assert "重启" in payload["error"]["message"]
    assert "重新发起" in payload["error"]["message"]
    assert store.get(run.id).stages[1].gate.resolved is None


def test_gate_for_unknown_run_is_404(main_mod, monkeypatch, real_stack):
    store, pipeline = real_stack
    monkeypatch.setattr(main_mod, "store", store)
    monkeypatch.setattr(main_mod, "pipeline", pipeline)
    resp = asyncio.run(main_mod.resolve_gate("run_nope", "understand", GateRequest(optionId="continue")))
    assert resp.status_code == 404
    assert json.loads(resp.body)["error"]["code"] == "GATE_REJECTED"


def test_main_py_has_no_jsonresponse_204_left():
    """源码级回归："JSONResponse(status_code=204, content=None)" 这种写法不许回来。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert "JSONResponse(status_code=204" not in src
    assert src.count("Response(status_code=204)") == 2, "两个 204 路由（cancel / gate）都要用空 body 的 Response"
