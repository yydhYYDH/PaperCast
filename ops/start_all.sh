#!/usr/bin/env bash
# 启动 PaperCast 的三个服务（后端 / 前端 / 小红书 MCP）。
#
# 用 setsid + nohup 把进程从当前终端会话脱钩：能活过终端和 agent 会话，
# 但**开机不会自启** —— 真正的持久化要用 root 装 systemd 单元（见 apps/papercast-server/docs/05-deployment.md）。
#
# 用法（在仓库任意位置都可执行，路径由脚本自身位置推导）：
#   ./ops/start_all.sh            # 三个都起
#   ./ops/start_all.sh backend    # 只起某一个：backend | frontend | mcp
#   ./ops/stop_all.sh
#
# 路径约定见 docs/conventions.md：代码在 apps/，工具在 ops/，运行态在 var/。
set -uo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
APPS="$WS/apps"
LOGS="$WS/var/logs"
PIDS="$WS/var/pids"
mkdir -p "$LOGS" "$PIDS"

port_busy() { ss -ltn 2>/dev/null | grep -q "127.0.0.1:$1 "; }

detach() {  # detach <名字> <端口> <命令...>
  name="$1"; port="$2"; shift 2
  if port_busy "$port"; then
    echo "[$name] 端口 $port 已在监听，跳过"
    return 0
  fi
  setsid nohup "$@" >"$LOGS/$name.log" 2>&1 < /dev/null &
  echo $! > "$PIDS/$name.pid"
  sleep 2
  if port_busy "$port"; then
    echo "[$name] 已启动 pid=$(cat "$PIDS/$name.pid") -> http://127.0.0.1:$port  (日志 $LOGS/$name.log)"
  else
    echo "[$name] 启动失败，看 $LOGS/$name.log"; tail -5 "$LOGS/$name.log"
  fi
}

start_backend() {
  detach backend 8000 env \
    PAPERCAST_DATA_DIR="$WS/var/runs" \
    PAPERCAST_UPLOAD_DIR="$WS/var/uploads" \
    "$APPS/papercast-server/.venv/bin/uvicorn" app.main:app \
      --host 127.0.0.1 --port 8000 --app-dir "$APPS/papercast-server"
}

start_frontend() {
  # 指向真实后端；想回 mock 就去掉 VITE_API_BASE
  detach frontend 5178 env VITE_API_BASE=http://127.0.0.1:8000 \
    npm --prefix "$APPS/papercast" run dev -- --host 127.0.0.1 --port 5178
}

start_mcp() {
  # 本机服务必须清掉代理变量，否则请求会被 http_proxy 吃掉；
  # 浏览器登录态与缓存统一落在工作区 var/cache（XDG_CACHE_HOME）。
  detach mcp 18060 env XDG_CACHE_HOME="$WS/var/cache" \
    env -u http_proxy -u https_proxy -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    "$WS/ops/bin/xiaohongshu-mcp" -headless=true -port 127.0.0.1:18060
}

MODE=all
if [ $# -gt 0 ]; then MODE="$1"; fi

case "$MODE" in
  backend) start_backend ;;
  frontend) start_frontend ;;
  mcp) start_mcp ;;
  *) start_backend; start_mcp; start_frontend ;;
esac
