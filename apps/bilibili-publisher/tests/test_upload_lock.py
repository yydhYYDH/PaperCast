"""B 站通道的上传锁回归测试（不联网、不真投稿）。

背景（2026-09-19 真实故障）：biliup 的账号级上传互斥锁写在
「dirs::data_local_dir()/biliup/locks/」，而 dirs 在 Linux 上取
「绝对路径的 $XDG_DATA_HOME」，否则「$HOME/.local/share」。
服务原先只把 HOME 换给了 login 的 pty，投稿子进程继承真实 HOME；
家目录只读（只读挂载 / 沙箱）时投稿整单失败：

    RuntimeError: Failed to create upload lock: Read-only file system (os error 30)
      at crates/biliup-cli/src/uploader.rs:459

素材包已经落盘，所以现象是「素材包仍在本地，但就是投不出去」。

这些测试用一个「只复刻锁路径推导」的假 biliup 覆盖两件事：
1. 投稿子进程的 HOME / XDG_DATA_HOME 必须落在工作区里，锁不再碰真实家目录；
2. 锁目录写不了 / 拿不到锁时，服务给的是能行动的错误码，而不是一句 Rust 的 EROFS。

跑法：cd apps/bilibili-publisher && ../papercast-server/.venv/bin/python -m pytest -q
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_DIR = Path(__file__).resolve().parents[1]
STUB_SRC = Path(__file__).resolve().parent / "fake_biliup.py"

TESTED_ENV = ("PAPERCAST_WS", "BILIBILI_BILIUP", "BILIBILI_HOME", "BILIBILI_DATA_HOME",
              "BILIBILI_EXPORT_ROOT", "BILIBILI_LOG_ROOT", "BILIBILI_LOGIN_DIR",
              "BILIBILI_COOKIES", "STUB_MODE", "STUB_STATE")


@pytest.fixture()
def fake_biliup(tmp_path: Path) -> Path:
    stub = tmp_path / "fake-biliup"
    stub.write_text(STUB_SRC.read_text(encoding="utf-8"), encoding="utf-8")
    stub.chmod(0o755)
    return stub


def load_module(ws: Path, biliup: Path, **env: str):
    """按给定环境变量重新加载服务模块（常量在 import 期就算好了）。"""
    for key in TESTED_ENV:
        os.environ.pop(key, None)
    os.environ.update({
        "PAPERCAST_WS": str(ws),
        "BILIBILI_BILIUP": str(biliup),
        "BILIBILI_EXPORT_ROOT": str(ws / "var" / "artifacts" / "bilibili" / "export"),
        "BILIBILI_LOG_ROOT": str(ws / "var" / "logs"),
        "BILIBILI_LOGIN_DIR": str(ws / "var" / "artifacts" / "bilibili" / "login"),
        "BILIBILI_COOKIES": str(ws / "var" / "secrets" / "bilibili" / "cookies.json"),
        **env,
    })
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    module = importlib.import_module("app.main")
    return importlib.reload(module)


def publish_body(ws: Path) -> dict:
    video = ws / "var" / "video.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"not a real video")
    return {"title": "测试标题", "desc": "测试简介", "tags": ["a", "b"],
            "video": str(video), "run_id": "run_lock_test", "confirmed": True}


def logged_in(module):
    async def _state():
        return {"is_logged_in": True, "username": "tester", "detail": "stubbed",
                "cookie_count": 3, "has_sessdata": True, "biliup": module.BILIUP,
                "biliup_available": True, "cookie_file": "raw", "cookies_path": "x", "tid": 231}
    return _state


def test_child_env_pins_home_and_xdg_into_workspace(tmp_path: Path, fake_biliup: Path):
    ws = tmp_path / "ws"
    m = load_module(ws, fake_biliup)
    env = m._biliup_env()
    home = ws / "var" / "home"
    assert env["HOME"] == str(home)
    assert env["XDG_DATA_HOME"] == str(home / ".local" / "share")
    assert env["XDG_CACHE_HOME"] == str(home / ".cache")
    assert env["XDG_CONFIG_HOME"] == str(home / ".config")
    # 锁目录必须与上游 dirs::data_local_dir()/biliup/locks 对齐
    assert m.lock_dir() == home / ".local" / "share" / "biliup" / "locks"


def test_publish_puts_upload_lock_inside_workspace(tmp_path: Path, fake_biliup: Path):
    ws = tmp_path / "ws"
    state = tmp_path / "state.json"
    m = load_module(ws, fake_biliup, STUB_STATE=str(state))
    m._account_state = logged_in(m)
    resp = TestClient(m.app).post("/api/v1/publish", json=publish_body(ws))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["bvid"] == "BV1Stub00001"

    record = json.loads(state.read_text(encoding="utf-8"))
    assert record["HOME"] == str(ws / "var" / "home")
    # cwd 也要固定：biliup 的 tracing 日志（download.log）是相对 cwd 写的
    assert record["cwd"] == str(ws / "var" / "logs")
    assert record["XDG_DATA_HOME"] == str(ws / "var" / "home" / ".local" / "share")
    lock = ws / "var" / "home" / ".local" / "share" / "biliup" / "locks" / "biliup_upload_123456.lock"
    assert Path(record["lock_path"]) == lock
    assert lock.is_file()          # 假 biliup 真写出来了 —— 也就是说不再碰只读家目录


def test_lock_creation_failure_is_reported_as_locked_not_logged_out(tmp_path: Path, fake_biliup: Path):
    ws = tmp_path / "ws"
    m = load_module(ws, fake_biliup, STUB_MODE="lock_fail")
    m._account_state = logged_in(m)
    resp = TestClient(m.app).post("/api/v1/publish", json=publish_body(ws))
    assert resp.status_code == 409
    err = resp.json()["error"]
    assert err["code"] == "UPLOAD_LOCKED"
    assert "Failed to create upload lock" in err["message"]
    assert str(m.lock_dir()) in err["message"]        # 报错里要给出锁目录，人才好动手


def test_stale_lock_message_also_maps_to_locked(tmp_path: Path, fake_biliup: Path):
    ws = tmp_path / "ws"
    m = load_module(ws, fake_biliup, STUB_MODE="stale_lock")
    m._account_state = logged_in(m)
    resp = TestClient(m.app).post("/api/v1/publish", json=publish_body(ws))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "UPLOAD_LOCKED"


def test_unwritable_lock_dir_fails_before_spawning_biliup(tmp_path: Path, fake_biliup: Path):
    ws = tmp_path / "ws"
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    state = tmp_path / "state.json"
    m = load_module(ws, fake_biliup, BILIBILI_DATA_HOME=str(ro / "data"), STUB_STATE=str(state))
    m._account_state = logged_in(m)
    resp = TestClient(m.app).post("/api/v1/publish", json=publish_body(ws))
    assert resp.status_code == 500
    err = resp.json()["error"]
    assert err["code"] == "UPLOAD_LOCK_UNWRITABLE"
    assert "不可写" in err["message"]
    assert not state.exists()          # biliup 根本没被启动，省得只拿到一句 EROFS


def test_health_exposes_lock_dir_writability(tmp_path: Path, fake_biliup: Path):
    ws = tmp_path / "ws"
    m = load_module(ws, fake_biliup)
    data = TestClient(m.app).get("/health").json()
    assert data["locks"] == str(m.lock_dir())
    assert data["locks_error"] == ""

    ro = tmp_path / "ro2"
    ro.mkdir()
    ro.chmod(0o555)
    m = load_module(ws, fake_biliup, BILIBILI_DATA_HOME=str(ro / "data"))
    data = TestClient(m.app).get("/health").json()
    assert data["locks_error"]          # 不可写要能被 /health 看见


def test_locks_endpoint_lists_and_clears(tmp_path: Path, fake_biliup: Path):
    ws = tmp_path / "ws"
    state = tmp_path / "state.json"
    m = load_module(ws, fake_biliup, STUB_STATE=str(state))
    m._account_state = logged_in(m)
    client = TestClient(m.app)
    assert client.post("/api/v1/publish", json=publish_body(ws)).status_code == 200
    listed = client.get("/api/v1/locks").json()["data"]
    assert [item["name"] for item in listed["locks"]] == ["biliup_upload_123456.lock"]
    assert client.delete("/api/v1/locks").json()["data"]["removed"] == ["biliup_upload_123456.lock"]
    assert client.get("/api/v1/locks").json()["data"]["locks"] == []
