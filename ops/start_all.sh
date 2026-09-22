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
# ⚠️ 小红书 MCP 默认跑在 **Windows 侧**（真实有头 Chrome，风控暴露面更小），
#    由 ops/mcp_windows.sh 起停，部署目录默认 E:\xhs-test。
#    服务器上没有 Windows 会自动回退到 Linux 侧；本机也可以 XHS_MCP_PLATFORM=wsl 强制。
#    背景见 docs/xhs-account-safety.md。
#
# 路径约定见 docs/conventions.md：代码在 apps/，工具在 ops/，运行态在 var/。
set -uo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
APPS="$WS/apps"
LOGS="$WS/var/logs"
PIDS="$WS/var/pids"
mkdir -p "$LOGS" "$PIDS"

port_busy() {
  # 任意本地地址都算占用。原写法只匹配 "127.0.0.1:$port "，而**前端特意绑 0.0.0.0**
  # （手机/平板要能直接打开界面）—— 于是每次 start_all 都以为前端没起、去起第二个 vite，
  # 撞 EADDRINUSE，还把 var/pids/frontend.pid 写成那个已经死掉的 pid，stop_all 会漏杀
  # （2026-09-19 实测；ss 过滤器比 grep 字符串更准，也不会把 15178 误判成 5178）。
  ss -ltnH "sport = :$1" 2>/dev/null | grep -q .
}

detach() {  # detach <名字> <端口> <命令...>
  name="$1"; port="$2"; shift 2
  if port_busy "$port"; then
    echo "[$name] 端口 $port 已在监听，跳过"
    return 0
  fi
  setsid nohup "$@" >"$LOGS/$name.log" 2>&1 < /dev/null &
  local pid=$!
  sleep 2
  if port_busy "$port"; then
    # pid 确认起得来再落盘：起失败就写进一个死 pid，stop_all 之后会照它去 kill（踩到过）
    echo "$pid" > "$PIDS/$name.pid"
    echo "[$name] 已启动 pid=$pid -> http://127.0.0.1:$port  (日志 $LOGS/$name.log)"
  else
    rm -f "$PIDS/$name.pid"
    echo "[$name] 启动失败，看 $LOGS/$name.log"; tail -5 "$LOGS/$name.log"
  fi
}

start_backend() {
  # 素材路径映射：MCP 跑在 Windows 侧时，后端递过去的 `/home/...` 对面根本不认
  # （Windows 看不到 WSL 的文件系统），MCP 只回一句「视频文件不存在或不可访问」，
  # 而且是在起浏览器之前就失败（2026-09-19 实测：真发一条视频笔记就死在这）。
  # Windows 用 \\wsl.localhost\<发行版>\ 访问 WSL，正斜杠同样被认（实测）。前缀从 $WS
  # 推导，不写死路径；同机部署（Linux 服务器上 MCP 与后端同机）留空即可，路径原样传。
  path_map="${CHANNEL_PATH_MAP:-}"
  if [ -z "$path_map" ] && [ "$XHS_MCP_PLATFORM" = "windows" ]; then
    distro="${WSL_DISTRO_NAME:-$(grep -m1 '^NAME=' /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"')}"
    [ -n "$distro" ] && path_map="${WS}=//wsl.localhost/${distro}${WS}"
  fi

  detach backend 8000 env \
    PAPERCAST_DATA_DIR="$WS/var/runs" \
    PAPERCAST_UPLOAD_DIR="$WS/var/uploads" \
    CHANNEL_PATH_MAP="$path_map" \
    "$APPS/papercast-server/.venv/bin/uvicorn" app.main:app \
      --host 127.0.0.1 --port 8000 --app-dir "$APPS/papercast-server"
}

start_frontend() {
  # 指向真实后端；想回 mock 就去掉 VITE_API_BASE
  #
  # 绑 0.0.0.0 而不是 127.0.0.1：手机/平板要能直接打开这个界面（用户要求，2026-09-19）。
  # 暴露的**只有前端**：接口与产物由 vite 的 /api、/artifacts 代理转发（见 apps/papercast/vite.config.ts），
  # 后端仍然只听 127.0.0.1，不需要跟着暴露、也不会有 CORS 问题。
  # 注意：局域网内谁都能打开这个前端（也就等于能用你的模型额度）；不想暴露就改回 127.0.0.1。
  detach frontend 5178 env VITE_API_BASE=http://127.0.0.1:8000 \
    npm --prefix "$APPS/papercast" run dev -- --host 0.0.0.0 --port 5178
}

# MCP 跑在哪一侧，**默认 wsl**（2026-09-19 改）。
#
# 为什么把默认从 windows 换成 wsl：Windows 侧连续 3 次（1 视频 + 2 图文）都卡在"点发布"
# 那一步——表单全填好、`检查标题长度：通过`，然后页面不跳转、发布不落地；同一条 run 换到
# Linux 侧**一次就发成功**（3m15s，`发布成功，已跳转离开发布页`）。能发 > 暴露面小，所以
# 默认定在能发的那一侧。
#
# 代价要知道：Linux 侧是「无头 Chromium + 指纹伪装成 Windows + stealth 关闭」，风控暴露面
# 比 Windows 侧大（Windows 是真有头 Chrome、指纹与真实 OS 一致）。想用 Windows 侧就显式
# `XHS_MCP_PLATFORM=windows ./ops/start_all.sh`，但记得后端也要按同一边重启（见下面那段警告）。
# 详见 docs/xhs-account-safety.md。
XHS_MCP_PLATFORM="${XHS_MCP_PLATFORM:-wsl}"

# ⚠️ MCP 换边之后**必须按同一边重启后端**：素材路径映射（CHANNEL_PATH_MAP）是后端启动时
# 定死的，后端不会自己发现 MCP 换了机器。2026-09-19 实测踩到：只重启了 Linux 侧 MCP、
# 没重启后端，于是后端继续递 Windows 的 `//wsl.localhost/...`，Linux 进程只回一句
# 「图片文件不存在」，6 张图全丢、卡到 5 分钟超时——看上去像风控，其实是路径不对。
# 这里主动对照一次（后端把映射如实报在 /api/env 里），别让下一个人再猜。
mcp_side_mismatch_warn() {
  env_json="$(curl -s --max-time 5 "http://127.0.0.1:8000/api/env" 2>/dev/null)" || return 0
  [ -n "$env_json" ] || return 0
  case "$env_json" in
    *'"pathMap":""'*) backend_mapped=no ;;
    *'"pathMap"'*)    backend_mapped=yes ;;
    *) return 0 ;;
  esac
  if [ "$XHS_MCP_PLATFORM" = "windows" ] && [ "$backend_mapped" = "no" ]; then
    echo "[mcp] ⚠️ MCP 跑 Windows 侧，但在跑的后端没有路径映射 —— 素材路径对面读不到。"
    echo "[mcp] ⚠️ 修法：XHS_MCP_PLATFORM=windows ./ops/start_all.sh backend"
  elif [ "$XHS_MCP_PLATFORM" != "windows" ] && [ "$backend_mapped" = "yes" ]; then
    echo "[mcp] ⚠️ MCP 跑 Linux 侧，但在跑的后端还带着 Windows 路径映射 —— 素材会被翻译成"
    echo "[mcp] ⚠️ //wsl.localhost/...，本地进程读不到（实测就是这么白失败一次的）。"
    echo "[mcp] ⚠️ 修法：XHS_MCP_PLATFORM=wsl ./ops/start_all.sh backend"
  fi
}

# MCP 的存活检测走 HTTP 而不是端口：WSL 的 ss **看不到 Windows 的监听**（实测），
# HTTP /health 才是跨 WSL/Windows 都成立的判据。
mcp_alive() { curl -s -o /dev/null --max-time 3 "http://127.0.0.1:18060/health"; }

start_mcp() {
  mcp_side_mismatch_warn

  # 先问 18060 有没有实例在响应，再决定起不起 —— 不能用 ss 判断：WSL 的 ss 看不到 Windows
  # 侧的监听，会以为端口空闲，于是去起第二个（撞端口 → 「启动失败」，日志里一句 EADDRINUSE，
  # 看上去像 MCP 坏了，其实是它已经在服务了）。默认 Linux 侧时，占着端口的往往正是对面的实例，
  # 这里如实说清是哪一侧、以及换边要先停谁。
  if mcp_alive; then
    if [ "$XHS_MCP_PLATFORM" = "windows" ]; then
      echo "[mcp] 18060 已有实例在响应，跳过启动（要换到 Linux 侧：先 XHS_MCP_PLATFORM=windows ./ops/stop_all.sh mcp）"
    else
      echo "[mcp] 18060 已有实例在响应，跳过启动 —— 它可能是**对面（Windows）**那个；"
      echo "[mcp] 要改跑本机（Linux）侧：先 XHS_MCP_PLATFORM=windows ./ops/stop_all.sh mcp，再 ./ops/start_all.sh mcp"
    fi
    return 0
  fi

  if [ "$XHS_MCP_PLATFORM" = "windows" ]; then
    if command -v powershell.exe >/dev/null 2>&1; then
      "$WS/ops/mcp_windows.sh" start
      return $?
    fi
    # 服务器上没有 Windows，回退是预期路径；本机也可以 XHS_MCP_PLATFORM=wsl 强制走这边。
    echo "[mcp] ⚠️ 找不到 powershell.exe（不在 WSL / 没开 interop），回退到 Linux 侧二进制"
    echo "[mcp] ⚠️ Linux 侧是无头 Chromium + 指纹伪装成 Windows，风控暴露面更大"
  fi

  # 以下为 Linux 侧。必须清掉代理变量，否则请求会被 http_proxy 吃掉；
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
