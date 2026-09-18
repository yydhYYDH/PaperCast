#!/usr/bin/env bash
# 有头浏览器人工登录知乎：桌面会弹出 Chromium 窗口，扫码/密码登录（含风控验证）后
# cookies 自动落盘到 var/secrets/zhihu/cookies.json（凭证进 secrets，规范见 docs/conventions.md §5）。
#
# 在**你自己的终端**里跑（沙箱内的 agent 看不到 X/Wayland socket）：
#   ./apps/zhihu-publisher/scripts/login-headed.sh
set -euo pipefail

WS="$(cd "$(dirname "$0")/../../.." && pwd)"
REPO="${ZHIHU_MCP_REPO:-$WS/reference/upstream/zhihu-mcp}"
PY="${ZHIHU_PY:-$WS/var/toolchains/zhihu-mcp-venv/bin/python}"
COOKIES="${COOKIES_PATH:-$WS/var/secrets/zhihu/cookies.json}"
export HOME="${ZHIHU_HOME:-$WS/var/home/zhihu-home}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
export COOKIES_PATH="$COOKIES"
export LOGIN_TIMEOUT="${LOGIN_TIMEOUT:-300}"

mkdir -p "$(dirname "$COOKIES")" "$HOME"
[ -x "$PY" ] || { echo "缺少 python: $PY（先按 apps/zhihu-publisher/docs/zhihu-official-notes.md 建 venv）" >&2; exit 1; }

echo "仓库: $REPO"
echo "cookies 将写入: $COOKIES"
echo "窗口弹出后请用知乎 App 扫码（或直接账号登录），最多等 ${LOGIN_TIMEOUT}s"
cd "$REPO"
exec "$PY" login.py --no-headless
