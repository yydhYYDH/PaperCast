#!/usr/bin/env bash
# 重启后端前的闸门：**在读看板的提醒之外，给一个跑得出来、能拦住人的检查**。
#
# 为什么需要它：2026-09-19 02:35:18 与 02:40:21 连着两次重启后端，各把在途 run 判成
# failed(INTERRUPTED)，其中 verify6 那条覆盖 6 个 Agent 的验收 run 被打断两次。
# 看板提醒贴了 102 秒后照样被重启 —— 提醒是软的，这个闸门是硬的。
#
# 用法：
#   ./ops/guard_restart.sh              # 有 running 就退出 1，并列出会被判死的 run
#   ./ops/guard_restart.sh --wait 900   # 最多等 900 秒，等在途跑完/清空后放行
#   ./ops/guard_restart.sh --force      # 明确知情后仍要重启（记录到看板，需自己担责）
#
# 只读 var/runs/*/run.json，不改任何东西。退出码 0 = 可以重启。

set -uo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
WAIT=0
FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --wait) WAIT="${2:-600}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

list_live() {
  python3 - "$WS" <<'PY'
import glob, json, os, sys
WS = sys.argv[1]
out = []
for f in glob.glob(os.path.join(WS, "var", "runs", "*", "run.json")):
    try:
        d = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    if d.get("status") == "running":
        out.append((d.get("createdAt") or 0, d.get("id", "?"), (d.get("title") or "")[:40]))
for ts, rid, t in sorted(out):
    print("%s\t%s" % (rid, t))
PY
}

deadline=$(( $(date +%s) + WAIT ))
while :; do
  live="$(list_live)"
  if [ -z "$live" ]; then
    echo "[guard_restart] 没有在途 run，可以重启。"
    exit 0
  fi
  if [ "$FORCE" = "1" ]; then
    echo "[guard_restart] 明知有在途 run 仍要重启，以下 run 会被判 failed(INTERRUPTED)："
    while IFS= read -r line; do printf '  %s\n' "$line"; done <<< "$live"
    exit 0
  fi
  if [ "$WAIT" = "0" ] || [ "$(date +%s)" -ge "$deadline" ]; then
    echo "[guard_restart] !! 拒绝放行：现在有在途 run，重启会把它们判成 failed(INTERRUPTED)"
    echo "  在途清单（run_id / 标题）："
    # 别用 printf '  %s\n' $live：标题里有空格会被拆成多行（我自己踩过一次）
    while IFS= read -r line; do printf '  %s\n' "$line"; done <<< "$live"
    echo "  可选：等在途跑完（--wait 900），或知情强行重启（--force，请先在看板喊一声）。"
    exit 1
  fi
  echo "[guard_restart] 还有在途 run，等 15 秒再看…（剩余 $(( deadline - $(date +%s) ))s）"
  sleep 15
done
