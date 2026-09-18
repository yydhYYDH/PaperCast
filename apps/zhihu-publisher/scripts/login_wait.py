#!/usr/bin/env python3
"""有头浏览器人工登录知乎 —— 真正等待你登录完成（轮询 z_c0），而不是靠跳转猜测。

上游 zhihu-mcp/login.py 用「访问 /signin 被重定向」判断已登录，风控跳转会被误判，
因此这里独立实现：打开窗口 -> 你在窗口里扫码/密码登录（含人机验证）-> 检测到 z_c0
才保存 cookies。

用法（必须在能看到桌面窗口的终端里跑，沙箱内看不到 X/Wayland socket）：

    WS="$(cd "$(dirname "$0")/../../.." && pwd)"
    cd "$WS/reference/upstream/zhihu-mcp"
    HOME="$WS/var/home/zhihu-home" \
    PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}" \
    COOKIES_PATH="$WS/var/secrets/zhihu/cookies.json" \
    LOGIN_TIMEOUT=900 \
    "$WS/var/toolchains/zhihu-mcp-venv/bin/python" "$WS/apps/zhihu-publisher/scripts/login_wait.py"

路径来自环境变量或脚本位置，不写死工作区绝对路径。
"""
import os
import sys
import time
from pathlib import Path

# 脚本现在住 apps/zhihu-publisher/scripts/，故 parents[3] = 工作区根
WS = Path(os.environ.get("PAPERCAST_WS") or Path(__file__).resolve().parents[3])
REPO = Path(os.environ.get("ZHIHU_MCP_REPO") or WS / "reference" / "upstream" / "zhihu-mcp")
TIMEOUT = int(os.environ.get("LOGIN_TIMEOUT", "900"))
POLL = 3

sys.path.insert(0, str(REPO))
os.chdir(REPO)

from browser.manager import create_browser  # noqa: E402
from zhihu.cookies import save_cookies  # noqa: E402

SIGNIN = "https://www.zhihu.com/signin"
ME = "https://www.zhihu.com/api/v4/me"


def zc0(context) -> str:
    for c in context.cookies():
        if c.get("name") == "z_c0" and c.get("value"):
            return c["value"]
    return ""


with create_browser(headless=False) as (browser, context, page):
    page.goto(SIGNIN, wait_until="domcontentloaded")
    print("WINDOW_READY 请在弹出的窗口里登录知乎（扫码或账号密码，如出现人机验证请在窗口里完成）", flush=True)
    print(f"WAITING 最长 {TIMEOUT}s", flush=True)

    started = time.time()
    warned_unhuman = False
    last_note = 0
    while time.time() - started < TIMEOUT:
        if not zc0(context):
            try:
                url = page.url
            except Exception:
                print("WINDOW_CLOSED 窗口被关闭，未检测到登录", flush=True)
                raise SystemExit(3)
            if "unhuman" in url and not warned_unhuman:
                print("RISK_CONTROL 知乎要求人机验证，请在窗口里完成验证后继续登录", flush=True)
                warned_unhuman = True
            elapsed = int(time.time() - started)
            if elapsed and elapsed % 30 == 0 and elapsed != last_note:
                last_note = elapsed
                print(f"...still waiting ({elapsed}s) url={url[:80]}", flush=True)
            time.sleep(POLL)
            continue

        cookies = context.cookies()
        save_cookies(cookies)
        print(f"LOGIN_OK 已保存 {len(cookies)} 个 cookie（含 z_c0）", flush=True)
        try:
            page.goto(ME, wait_until="domcontentloaded")
            txt = page.inner_text("body")[:400]
            print("ME " + txt.replace("\n", " ")[:300], flush=True)
        except Exception as exc:
            print(f"ME_CHECK_FAILED {exc}", flush=True)
        raise SystemExit(0)

    print("LOGIN_TIMEOUT 超时未检测到登录", flush=True)
    raise SystemExit(2)
