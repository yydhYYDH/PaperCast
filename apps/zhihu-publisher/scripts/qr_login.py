#!/usr/bin/env python3
"""无头抓取知乎登录二维码并在同一浏览器会话里等待扫码成功。

需要 zhihu-mcp 的依赖（fastmcp/playwright/loguru）。约定用法：

    WS="$(cd "$(dirname "$0")/../../.." && pwd)"
    cd "$WS/reference/upstream/zhihu-mcp"
    HOME="$WS/var/home/zhihu-home" \
    PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}" \
    "$WS/var/toolchains/zhihu-mcp-venv/bin/python" "$WS/apps/zhihu-publisher/scripts/qr_login.py"

成功后将 cookies 写入 <repo>/cookies/cookies.json。
路径全部来自环境变量或脚本自身位置，不写死工作区绝对路径。
"""
import base64
import os
import shutil
import sys
from pathlib import Path

WS = Path(os.environ.get("PAPERCAST_WS") or Path(__file__).resolve().parents[3])
REPO = Path(os.environ.get("ZHIHU_MCP_REPO") or WS / "reference" / "upstream" / "zhihu-mcp")
OUT = Path(os.environ.get("QR_OUT") or WS / "var" / "artifacts" / "zhihu" / "qr-login.png")
TIMEOUT = int(os.environ.get("QR_TIMEOUT", "300"))

sys.path.insert(0, str(REPO))
os.chdir(REPO)
OUT.parent.mkdir(parents=True, exist_ok=True)

from browser.manager import create_browser  # noqa: E402
from zhihu.actions import LoginAction  # noqa: E402

with create_browser(headless=True) as (browser, context, page):
    action = LoginAction(page, context)
    result = action.fetch_qrcode()
    if result.get("is_logged_in"):
        print("ALREADY_LOGGED_IN", flush=True)
        raise SystemExit(0)

    b64 = result.get("qrcode_base64") or ""
    if b64:
        OUT.write_bytes(base64.b64decode(b64))
        print(f"QR_SAVED element -> {OUT}", flush=True)
    else:
        fallback = REPO / "cookies" / "login_qrcode.png"
        page.screenshot(path=str(OUT))
        if fallback.is_file():
            shutil.copyfile(fallback, OUT)
        print(f"QR_SAVED page -> {OUT}", flush=True)

    ok = action.wait_for_login(TIMEOUT)
    print("LOGIN_OK" if ok else "LOGIN_TIMEOUT", flush=True)
