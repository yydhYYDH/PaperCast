#!/usr/bin/env bash
# HF Daily Papers → 小红书定时发布：每日任务入口。
#
# 幂等：先确保 backend/mcp 在跑（start_all.sh 已幂等），再交给 hf_daily_job.py。
# 每天 12:00 由外部触发器调用；"关机错过、开机补跑"由脚本内部的"到点才跑 + 当天打卡"
# 保证，所以任何时刻的触发都安全。可用触发器（见 ops/README.md）：
#   - Windows 计划任务 + 登录自启：ops/install_hf_daily_windows_task.sh（本机实际在用）
#   - systemd user timer：         ops/install_hf_daily_timer.sh
#   - user crontab：               ops/install_hf_daily_cron.sh
#
# 用法：
#   ./ops/hf_daily_job.sh              # 正常跑
#   ./ops/hf_daily_job.sh --dry-run    # 只生成、不排期
#   ./ops/hf_daily_job.sh --force      # 忽略当天 .done 卡
#   ./ops/hf_daily_job.sh --check      # 只体检
set -euo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$WS/var/logs"
mkdir -p "$LOGS"
LOG="$LOGS/hf-daily-job.log"

# 日志同时进 journal（systemd）和 var/logs/hf-daily-job.log（人看）。
exec > >(tee -a "$LOG") 2>&1

export PAPERCAST_BASE="${PAPERCAST_BASE:-http://127.0.0.1:8000}"
export XHS_MCP_BASE="${XHS_MCP_BASE:-http://127.0.0.1:18060}"
export PAPERCAST_DATA_DIR="${PAPERCAST_DATA_DIR:-$WS/var/runs}"

wait_health() { # url attempts
  local url="$1" n="${2:-40}" i
  for i in $(seq 1 "$n"); do
    if curl -sf --max-time 5 "$url" >/dev/null 2>&1; then return 0; fi
    sleep 3
  done
  return 1
}

# 纯查询类（--due-check / --check）不启动任何服务，直接交给 python。
case " $* " in
  *" --due-check "*|*" --check "*)
    exec python3 "$WS/ops/hf_daily_job.py" "$@"
    ;;
esac

# 登录自启/开机补跑会在任何时刻调用本脚本。先做一次轻量"该不该跑"判断，
# 不该跑就直接退出，**不启动任何服务**（否则每天早上登录都会白起 backend/mcp）。
# --force / --dry-run 显式跳过这道闸。
case " $* " in
  *" --force "*|*" --dry-run "*) ;;
  *)
    if ! python3 "$WS/ops/hf_daily_job.py" --due-check; then
      exit 0
    fi
    ;;
esac

echo "== 确保服务在跑 =="
# start_all.sh 一次只接一个模式，backend / mcp 分开起（都是幂等的）。
"$WS/ops/start_all.sh" backend >/dev/null 2>&1 || true
"$WS/ops/start_all.sh" mcp >/dev/null 2>&1 || true

if ! wait_health "$PAPERCAST_BASE/api/health" 20; then
  echo "papercast-server 起不来（$PAPERCAST_BASE），放弃本次。日志：$LOGS/backend.log" >&2
  exit 2
fi

# dry-run 不投递，无需 MCP。
if [[ " $* " != *" --dry-run "* ]]; then
  if ! wait_health "$XHS_MCP_BASE/health" 20; then
    echo "小红书 MCP 起不来（$XHS_MCP_BASE），放弃本次。日志：$LOGS/mcp.log" >&2
    exit 2
  fi
fi

exec python3 "$WS/ops/hf_daily_job.py" "$@"
