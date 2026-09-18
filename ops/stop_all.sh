#!/usr/bin/env bash
# 停掉 start_all.sh 起的进程（pid 文件在 var/pids/）
set -uo pipefail
WS="$(cd "$(dirname "$0")/.." && pwd)"
PIDS="$WS/var/pids"
for f in "$PIDS"/*.pid; do
  [ -e "$f" ] || continue
  name="$(basename "$f" .pid)"
  pid="$(cat "$f")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null && echo "[$name] 已停 pid=$pid"
    pkill -P "$pid" 2>/dev/null && echo "[$name] 已停子进程"
  else
    echo "[$name] 进程不在（pid=$pid）"
  fi
  rm -f "$f"
done
