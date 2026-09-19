"""app/modules/video.py 的工具链推导：按工作区约定推导，不写死任何绝对路径。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules import video


@pytest.fixture
def no_path_lookup(monkeypatch):
    """把 PATH 查找换成「什么也找不到」，让推导结果只可能来自 workspace_root()。"""
    monkeypatch.setattr(video, "shutil", SimpleNamespace(which=lambda name: None))
    for env in ("PAPERCAST_FFMPEG", "PAPERCAST_FFPROBE", "PAPERCAST_TTS_PYTHON"):
        monkeypatch.delenv(env, raising=False)
    return monkeypatch


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/sh\n", encoding="utf-8")
    p.chmod(0o755)
    return p


def test_tools_return_empty_when_nothing_is_installed(no_path_lookup, tmp_path, monkeypatch):
    monkeypatch.setattr(video, "workspace_root", lambda: tmp_path)
    assert video.tool_ffmpeg() == ""
    assert video.tool_ffprobe() == ""


def test_tools_prefer_workspace_toolchain(no_path_lookup, tmp_path, monkeypatch):
    monkeypatch.setattr(video, "workspace_root", lambda: tmp_path)
    ffmpeg = _touch(tmp_path / "var/toolchains/p2b/bin/ffmpeg")
    assert video.tool_ffmpeg() == str(ffmpeg)
    assert video.tool_ffprobe() == ""          # ffprobe 没装就是空串，不瞎返回


def test_tools_fall_back_to_path_lookup(tmp_path, monkeypatch):
    """工作区里没有工具链时退回 PATH 查找 —— 但仍然要求「探到的文件真实存在」。"""
    monkeypatch.setattr(video, "workspace_root", lambda: tmp_path)
    monkeypatch.delenv("PAPERCAST_FFMPEG", raising=False)
    found = _touch(tmp_path / "usr-local-ffmpeg")
    monkeypatch.setattr(video, "shutil", SimpleNamespace(which=lambda name: str(found)))
    assert video.tool_ffmpeg() == str(found)
    # 探到不存在的路径 → 不返回假路径
    monkeypatch.setattr(video, "shutil", SimpleNamespace(which=lambda name: "/usr/local/bin/" + name))
    assert video.tool_ffmpeg() == ""


@pytest.mark.parametrize("env_name,func", [
    ("PAPERCAST_FFMPEG", "tool_ffmpeg"),
    ("PAPERCAST_FFPROBE", "tool_ffprobe"),
    ("PAPERCAST_TTS_PYTHON", "tool_tts_python"),
])
def test_env_override_wins(monkeypatch, env_name, func):
    monkeypatch.setenv(env_name, "/opt/custom/tool")
    assert getattr(video, func)() == "/opt/custom/tool"


def test_tts_python_prefers_bili_venv_then_sys_executable(no_path_lookup, tmp_path, monkeypatch):
    monkeypatch.setattr(video, "workspace_root", lambda: tmp_path)
    import sys

    # 三种候选都没装时退回当前解释器（保证「能跑」而不是空串）
    assert video.tool_tts_python() == sys.executable
    _touch(tmp_path / "var/toolchains/bili-venv/bin/python3")
    assert video.tool_tts_python() == str(tmp_path / "var/toolchains/bili-venv/bin/python3")


def test_derived_tool_paths_live_under_workspace_root(no_path_lookup, tmp_path, monkeypatch):
    """推导出来的路径必须挂在 workspace_root() 下 —— 这就是「不写死绝对路径」的可执行断言。"""
    monkeypatch.setattr(video, "workspace_root", lambda: tmp_path)
    _touch(tmp_path / "var/toolchains/p2b/bin/ffmpeg")
    _touch(tmp_path / "var/toolchains/p2b/bin/ffprobe")
    for path in (video.tool_ffmpeg(), video.tool_ffprobe()):
        assert path.startswith(str(tmp_path))
        assert str(tmp_path) in path
        assert "/home/" not in path


def test_workspace_root_from_data_dir_env(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / "apps").mkdir(parents=True)
    (ws / "var/runs").mkdir(parents=True)
    monkeypatch.setenv("PAPERCAST_DATA_DIR", str(ws / "var/runs"))
    assert video.workspace_root() == ws.resolve()


def test_workspace_root_falls_back_to_two_levels_up(tmp_path, monkeypatch):
    # PAPERCAST_DATA_DIR 指向一个没有 apps/ 的目录时，退回「上两级」
    odd = tmp_path / "somewhere" / "else" / "runs"
    odd.mkdir(parents=True)
    monkeypatch.setenv("PAPERCAST_DATA_DIR", str(odd))
    assert video.workspace_root() == odd.parent.parent


def test_workspace_root_derives_from_file_location(monkeypatch):
    """没有 env 时按 __file__ 上溯：video.py = <ws>/apps/papercast-server/app/modules/video.py。"""
    monkeypatch.delenv("PAPERCAST_DATA_DIR", raising=False)
    expected = Path(video.__file__).resolve().parents[4]
    assert video.workspace_root() == expected
    assert (expected / "apps/papercast-server").is_dir()
