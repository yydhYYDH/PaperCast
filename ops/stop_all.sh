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
#   ./ops/stop_all.sh          # 真停
#   DRY=1 ./ops/stop_all.sh    # 只列出会停谁，不动手
set -uo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
PIDS="$WS/var/pids"
DRY="${DRY:-0}"

# "名字|命令行特征" —— 特征用固定串匹配（case 里加引号即为字面量），别写正则
PATTERNS=(
  "backend|uvicorn app.main:app --host 127.0.0.1 --port 8000"
  "frontend|apps/papercast/node_modules/.bin/vite"
  "mcp|ops/bin/xiaohongshu-mcp"
  "zhihu|uvicorn app.main:app --host 127.0.0.1 --port 18070"
  "mcp-browser|var/cache/xiaohongshu-mcp/browser"
)

SEEN=""   # 同一个进程可能先被 pid 文件、再被命令行特征匹配到，去重避免重复 kill 的噪音

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
  found_pidfile=1
  name="$(basename "$f" .pid)"
  pid="$(cat "$f")"
  if kill -0 "$pid" 2>/dev/null; then
    stop_pid "$pid" "$name"
    [ "$DRY" = "1" ] || pkill -P "$pid" 2>/dev/null
  else
    echo "  [$name] pid 文件过期（pid=$pid 不在）"
  fi
  [ "$DRY" = "1" ] || rm -f "$f"
done
[ "$found_pidfile" = "1" ] || echo "  （var/pids 下没有 pid 文件）"

echo "== 2) 按命令行特征兜底 =="
me="$$"
hit=0
for d in /proc/[0-9]*; do
  pid="${d#/proc/}"
  [ "$pid" = "$me" ] && continue
  cmd="$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null)" || continue
  [ -n "$cmd" ] || continue
  # 别碰任何沙箱包装进程：它们的命令行里会带上被执行的脚本正文，容易误伤调用方
  case "$cmd" in
    *bwrap*|*--die-with-parent*) continue ;;
  esac
  for entry in "${PATTERNS[@]}"; do
    pat="${entry#*|}"
    case "$cmd" in
      *"$pat"*)
        stop_pid "$pid" "${entry%%|*}"
        hit=1
        break
        ;;
    esac
  done
done
[ "$hit" = "1" ] || echo "  （没有匹配到残留进程）"

echo "== 完成（DRY=$DRY）=="
