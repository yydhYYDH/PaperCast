#!/usr/bin/env bash
# 停掉 start_all.sh 起的进程。
#
# 为什么不能只靠 var/pids/*.pid：pid 文件是 start_all.sh 写的，而服务可能由别的方式拉起。
# 典型例子就是前端 —— 5178 早就被别的会话占着，start_all.sh 看到端口在监听就跳过，
# 于是**根本没有 frontend.pid**，只按 pid 文件停就会把它漏掉，留下一个占着端口的孤儿进程。
# 所以这里在 pid 文件之外，再按「命令行特征」兜底匹配一遍。
#
# 实现约束（2026-09-19 实测）：本沙箱里 lsof / fuser **看不到别的会话的进程**
# （/proc/<pid>/fd 不可读，lsof -ti:5178 直接 exit 1 无输出），端口→pid 只能靠读
# /proc/<pid>/cmdline —— 它是世界可读的，跨沙箱也能拿到。
#
# 用法：
#   ./ops/stop_all.sh                 # 停全部（backend/frontend/mcp/zhihu/bilibili）
#   ./ops/stop_all.sh backend         # 只停后端（可给多个：backend frontend）
#   ./ops/stop_all.sh backend zhihu   # 只停这两个
#   DRY=1 ./ops/stop_all.sh backend   # 只列出会停谁，不动手
#
# 注意：**默认停全部**。要只停某一个，必须显式给名字 —— 这条是 2026-09-19 补的，
# 之前没有模式参数，`stop_all.sh backend` 会连带把前端/知乎一起杀掉（踩过）。
set -uo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
PIDS="$WS/var/pids"
DRY="${DRY:-0}"
WANT="${*:-all}"

# "名字|命令行特征" —— 特征用固定串匹配（case 里加引号即为字面量），别写正则
PATTERNS=(
  "backend|uvicorn app.main:app --host 127.0.0.1 --port 8000"
  "frontend|apps/papercast/node_modules/.bin/vite"
  "mcp|ops/bin/xiaohongshu-mcp"
  "zhihu|uvicorn app.main:app --host 127.0.0.1 --port 18070"
  "bilibili|uvicorn app.main:app --host 127.0.0.1 --port 18080"
  "mcp-browser|var/cache/xiaohongshu-mcp/browser"
)

want() {
  [ "$WANT" = "all" ] && return 0
  for w in $WANT; do [ "$w" = "$1" ] && return 0; done
  # 停 mcp 时把它的浏览器一起停：无头 Chromium 是 MCP 自己开的，留着会占住浏览器 profile，
  # 下次起 MCP 可能因为这个残留 profile 出问题（它本来只能靠 stop_all.sh mcp mcp-browser 才停）。
  if [ "$1" = "mcp-browser" ]; then
    for w in $WANT; do [ "$w" = "mcp" ] && return 0; done
  fi
  return 1
}

if [ "$WANT" != "all" ]; then
  for w in $WANT; do
    ok=0
    for entry in "${PATTERNS[@]}"; do [ "$w" = "${entry%%|*}" ] && ok=1; done
    [ "$w" = "mcp-browser" ] && ok=1
    [ "$ok" = "1" ] || { echo "⚠️ 不认识的目标：$w（可选：backend frontend mcp zhihu bilibili mcp-browser all）"; exit 2; }
  done
fi
echo "== 目标：$WANT =="

SEEN=""   # 同一个进程可能先被 pid 文件、再被命令行特征匹配到，去重避免重复 kill 的噪音

# --- 0) Windows 侧的 MCP（**只在 MCP 真跑在 Windows 侧时才做**）-----------------
# 下面两种手段（pid 文件、/proc/<pid>/cmdline）都只能停 Linux 进程，所以真跑 Windows 侧时
# 这一步不能省：不单独停它就会留下一个占着 18060 的 Windows 孤儿，下次 start_all.sh 又因为
# WSL 的 ss 看不到 Windows 的监听而以为端口空闲、重复去起。
#
# 但**默认已经不是 Windows 侧了**：start_all.sh 里 XHS_MCP_PLATFORM 默认 wsl（2026-09-19 改，
# 能真发成功的那一侧）。而 WSL 里 `command -v powershell.exe` 恒为真 —— 只按它判断的话，
# 每次 stop 都会先去停 Windows 侧，而 mcp_windows.sh 的存活探测是 curl 127.0.0.1:18060，
# 在 WSL2 里会探到**我们自己的 Linux 监听**（localhost 转发），于是必然回一句
# 「18060 仍有响应」+「停止没成功」—— 纯假告警（2026-09-19 用户报的就是这个）。
# 所以这里跟 start_all.sh 用同一个开关：跑 Linux 侧时整段跳过，交给下面 1)/2) 停。
XHS_MCP_PLATFORM="${XHS_MCP_PLATFORM:-wsl}"
if [ "$XHS_MCP_PLATFORM" = "windows" ] && want mcp; then
  if command -v powershell.exe >/dev/null 2>&1; then
    echo "== 0) Windows 侧的 MCP =="
    if [ "$DRY" = "1" ]; then
      echo "  (dry) 会停 Windows 侧的 xiaohongshu-mcp 与它自己的 Chrome"
    else
      "$WS/ops/mcp_windows.sh" stop || echo "  ⚠️ Windows 侧停止没成功，看上面的输出"
    fi
  else
    echo "== 0) Windows 侧的 MCP：XHS_MCP_PLATFORM=windows 但找不到 powershell.exe，跳过 =="
  fi
fi

stop_pid() {
  pid="$1"; label="$2"
  case " $SEEN " in *" $pid "*) return 0 ;; esac
  SEEN="$SEEN $pid"
  if [ "$DRY" = "1" ]; then
    echo "  (dry) 会停 [$label] pid=$pid"
    return 0
  fi
  kill "$pid" 2>/dev/null && echo "  [$label] 已发 TERM pid=$pid" || { echo "  [$label] TERM 失败 pid=$pid（可能无权限）"; return 1; }
  for _ in 1 2 3 4 5; do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 1
  done
  kill -9 "$pid" 2>/dev/null && echo "  [$label] TERM 超时，已 KILL pid=$pid"
}

echo "== 1) 按 var/pids/*.pid =="
found_pidfile=0
for f in "$PIDS"/*.pid; do
  [ -e "$f" ] || continue
  name="$(basename "$f" .pid)"
  want "$name" || continue
  found_pidfile=1
  pid="$(cat "$f")"
  if kill -0 "$pid" 2>/dev/null; then
    stop_pid "$pid" "$name"
    [ "$DRY" = "1" ] || pkill -P "$pid" 2>/dev/null
  else
    echo "  [$name] pid 文件过期（pid=$pid 不在）"
  fi
  [ "$DRY" = "1" ] || rm -f "$f"
done
[ "$found_pidfile" = "1" ] || echo "  （没有匹配的 pid 文件）"

echo "== 2) 按命令行特征兜底 =="
me="$$"
# 自己这一条祖先链一律不碰。原因：`bash -c '<整段脚本正文>'` 这种调用方式，进程 cmdline 里
# 带着正文，正文里只要出现过 "ops/bin/xiaohongshu-mcp" 字样（核验脚本里 ls 一下这个路径就够了），
# 按子串兜底就会把**调用方自己**当成 MCP 停掉 —— 2026-09-19 实测：核验脚本跑到这一步直接被
# 自己 SIGTERM，输出断在那里，看表像"停成功了但没输出"。
self_chain=" $me "
p="$me"
while [ -n "$p" ] && [ "$p" != "0" ] && [ "$p" != "1" ]; do
  p="$(awk '/^PPid:/{print $2}' "/proc/$p/status" 2>/dev/null)"
  [ -n "$p" ] || break
  case " $self_chain " in *" $p "*) ;; *) self_chain="$self_chain $p " ;; esac
done
hit=0
for d in /proc/[0-9]*; do
  pid="${d#/proc/}"
  case " $self_chain " in *" $pid "*) continue ;; esac
  cmd="$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null)" || continue
  [ -n "$cmd" ] || continue
  # 别碰任何沙箱包装进程：它们的命令行里会带上被执行的脚本正文，容易误伤调用方
  case "$cmd" in
    *bwrap*|*--die-with-parent*) continue ;;
  esac
  for entry in "${PATTERNS[@]}"; do
    pat="${entry#*|}"
    label="${entry%%|*}"
    want "$label" || continue
    # mcp 这条要更严：它的路径短、最容易被别人的脚本正文带上，所以只在 **argv0 就是那个二进制**
    # 时才认（正常运行时 argv0 正是 .../ops/bin/xiaohongshu-mcp-auth）。别的条目是长命令行串，
    # 误命中概率低，保持子串匹配。
    if [ "$label" = "mcp" ]; then
      argv0="$(tr '\0' '\n' < "$d/cmdline" 2>/dev/null | head -1)"
      case "$argv0" in
        */xiaohongshu-mcp|*/xiaohongshu-mcp-auth) ;;
        *) continue ;;
      esac
    fi
    case "$cmd" in
      *"$pat"*)
        stop_pid "$pid" "$label"
        hit=1
        break
        ;;
    esac
  done
done
[ "$hit" = "1" ] || echo "  （没有匹配到残留进程）"

# --- 收尾核对：18060 到底清干净没有 ------------------------------------------
# Linux 手段停不掉对面的实例，所以停完再问一次 18060。**HTTP 是跨 WSL/Windows 都成立的
# 判据**（WSL 的 ss 看不到 Windows 的监听），只按端口/进程表判断会误报"已停"。
# 还有响应就如实说清"剩下的是哪一侧"并给下一步，而不是留一句含糊的告警。
if [ "$DRY" != "1" ] && want mcp && curl -s -o /dev/null --max-time 3 "http://127.0.0.1:18060/health"; then
  if [ "$XHS_MCP_PLATFORM" = "windows" ]; then
    echo "⚠️ 18060 还有响应：Windows 侧那个实例没停掉，看上面 ops/mcp_windows.sh 的输出"
  else
    echo "⚠️ 18060 还有响应：本机这一侧已经按 pid 与命令行停过了，那它多半在对面（Windows）——"
    echo "   停对面：XHS_MCP_PLATFORM=windows ./ops/stop_all.sh mcp"
  fi
fi

echo "== 完成（DRY=$DRY）=="
