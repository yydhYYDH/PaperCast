#!/usr/bin/env bash
# 启动 PaperCast 的服务：后端 / 前端 + 三个发布通道（小红书 MCP:18060、知乎:18070、B站:18080）。
#
# 用 setsid + nohup 把进程从当前终端会话脱钩：能活过终端和 agent 会话，
# 但**开机不会自启** —— 真正的持久化要用 root 装 systemd 单元（见 apps/papercast-server/docs/05-deployment.md）。
#
# 用法（在仓库任意位置都可执行，路径由脚本自身位置推导）：
#   ./ops/start_all.sh            # 全部起
#   ./ops/start_all.sh backend    # 只起某一个：backend | frontend | mcp | zhihu | bilibili
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
  #
  # 绑 0.0.0.0 而不是 127.0.0.1：手机/平板要能直接打开这个界面（用户要求，2026-09-19）。
  # 暴露的**只有前端**：接口与产物由 vite 的 /api、/artifacts 代理转发（见
  # apps/papercast/vite.config.ts），后端仍然只听 127.0.0.1，不需要跟着暴露、也不会有 CORS。
  # 注意：局域网内谁都能打开这个前端（也就等于能用你的模型额度）；不想暴露就改回 127.0.0.1。
  detach frontend 5178 env VITE_API_BASE=http://127.0.0.1:8000 \
    npm --prefix "$APPS/papercast" run dev -- --host 0.0.0.0 --port 5178
}

start_mcp() {
  # 本机服务必须清掉代理变量，否则请求会被 http_proxy 吃掉；
  # 四个必须注意的点（2026-09-19 踩过）：
  # 1. 必须在 apps/xiaohongshu-mcp/ 里起：它的 cookie 是**相对当前目录**的 cookies.json
  #    （见 apps/xiaohongshu-mcp/cookies/cookies.go 的 localCookiesPath），换 cwd 会新建空文件并掉登录；
  # 2. 清掉代理变量，否则请求会被 http_proxy 吃掉；
  # 3. XDG_CACHE_HOME 指向工作区 var/cache —— 浏览器 profile 与登录态在那里；
  # 4. **必须用 xiaohongshu-mcp-auth（工作树版），不能用 xiaohongshu-mcp（干净版）**：
  #    MCP 每个接口底层都会真开一个浏览器访问小红书，而渠道状态探测会被前端秒级轮询，
  #    guard.go 里的访问预算 + login/status 缓存就是挡这件事的。
  #    干净版由 build_mcp.sh 从 `git archive HEAD` 编译，只在 guard.go 已提交后才包含它——
  #    在它提交之前启干净版，等于把账号暴露给轮询。详见 docs/xhs-account-safety.md。
  #    （不带 AUTH_USER/AUTH_PASS 时鉴权是关闭的，不影响本机联调。）
  detach mcp 18060 sh -c 'cd "$1" && exec env XDG_CACHE_HOME="$2" \
    env -u http_proxy -u https_proxy -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    "$3" -headless=true -port 127.0.0.1:18060' _ \
    "$WS/apps/xiaohongshu-mcp" "$WS/var/cache" "$WS/ops/bin/xiaohongshu-mcp-auth"
}

start_zhihu() {
  # 知乎发布通道（apps/zhihu-publisher）：只读复用 reference/upstream/zhihu-mcp 的 ZhihuService，
  # 依赖 playwright，因此用 var/toolchains/zhihu-mcp-venv 而不是 backend venv。
  # 凭证（cookies）落 var/secrets/zhihu/，投递中转落 var/artifacts/zhihu/ —— 见 docs/conventions.md §4/§5。
  # 有头登录需要 DISPLAY，由 /api/v1/login/start 弹窗。
  detach zhihu 18070 env     COOKIES_PATH="$WS/var/secrets/zhihu/cookies.json"     PAPERCAST_WS="$WS"     PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}" \
    env -u http_proxy -u https_proxy -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    "$WS/var/toolchains/zhihu-mcp-venv/bin/uvicorn" app.main:app \
      --host 127.0.0.1 --port 18070 --app-dir "$APPS/zhihu-publisher"
}

start_bilibili() {
  # B 站发布通道（apps/bilibili-publisher）：底层是 biliup CLI，cookies 落 var/artifacts/bilibili/。
  # 没装 biliup 也能起（服务会如实报 unconfigured），export/ 素材包始终可用。
  detach bilibili 18080 env PAPERCAST_WS="$WS" BILIBILI_BILIUP="${BILIBILI_BILIUP:-}" \
    "$WS/apps/papercast-server/.venv/bin/uvicorn" app.main:app \
      --host 127.0.0.1 --port 18080 --app-dir "$APPS/bilibili-publisher"
}

MODE=all
if [ $# -gt 0 ]; then MODE="$1"; fi

case "$MODE" in
  backend) start_backend ;;
  frontend) start_frontend ;;
  mcp) start_mcp ;;
  zhihu) start_zhihu ;;
  bilibili) start_bilibili ;;
  *) start_backend; start_mcp; start_zhihu; start_bilibili; start_frontend ;;
esac
