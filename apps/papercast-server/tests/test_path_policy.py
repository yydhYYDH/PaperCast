"""路径规范守护：app/ 与 scripts/ 的 Python 源码里不许出现写死的绝对路径字面量。

工作区规矩（docs/conventions.md §3.1、AGENTS.md §2）：路径必须由自身文件位置或环境变量推导，
不能写死 /home/yydh/hack。这里用 AST 扫**字符串字面量**（注释不算），
既覆盖 video.py 的工具链推导，也守住以后新写的模块。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = [SERVER_ROOT / "app", SERVER_ROOT / "scripts"]

#: 只盯「本机用户主目录 / 本工作区」这类写死的绝对路径。
#: HTTP 路由（/api/...）、URL 路径片段（/artifacts/）是接口常量，不在守护范围内。
HARDCODED = re.compile(r"^/(?:home|Users|Volumes|root)/|^/home$")


def _python_files() -> list[Path]:
    files: list[Path] = []
    for d in SOURCE_DIRS:
        if d.is_dir():
            files.extend(sorted(p for p in d.rglob("*.py") if "__pycache__" not in p.parts))
    return files


def _string_literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # 只看像绝对路径的字面量（含分隔符），避免把普通文案里的 "/" 也卷进来
            if node.value.startswith("/") and "/" in node.value[1:]:
                out.append((node.lineno, node.value))
    return out


def test_source_files_are_discoverable():
    files = _python_files()
    assert files, "没扫到任何 .py —— 目录结构变了，这条守护会静默失效"
    assert any(p.name == "video.py" for p in files)


def test_detector_actually_catches_a_hardcoded_workspace_path():
    """守护自己也要有用例：否则规则写错时会「全绿但什么也没查」。"""
    assert HARDCODED.search("/home/yydh/hack/var/toolchains/bili-venv/bin/python")
    assert HARDCODED.search("/Users/someone/ws/apps")
    assert not HARDCODED.search("/api/v1/publish")      # 接口常量不算
    assert not HARDCODED.search("/artifacts/")          # URL 片段不算
    assert not HARDCODED.search("/usr/local/bin/ffmpeg")


def test_no_hardcoded_workspace_path_in_source():
    offenders: list[str] = []
    for f in _python_files():
        for lineno, literal in _string_literals(f):
            if HARDCODED.search(literal):
                offenders.append(f"{f.relative_to(SERVER_ROOT)}:{lineno} -> {literal!r}")
    assert not offenders, "发现写死的绝对路径字面量（应由文件位置/环境变量推导）：" + "; ".join(offenders)


@pytest.mark.parametrize("func_name", ["tool_ffmpeg", "tool_ffprobe", "tool_tts_python"])
def test_tool_path_functions_use_derivation_not_literals(func_name):
    from app.modules import video

    src = Path(video.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func_name)
    literals = [n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("/")]
    assert literals == [], f"{func_name} 里出现绝对路径字面量：{literals}"
    # 必须走 workspace_root() / env
    called = {n.attr if isinstance(n, ast.Attribute) else getattr(n, "id", "") for n in ast.walk(fn)}
    assert "workspace_root" in called or "get" in called
