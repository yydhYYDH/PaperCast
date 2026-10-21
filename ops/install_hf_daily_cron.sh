#!/usr/bin/env bash
# 用 crontab 安装 HF Daily Papers 每日任务（系统没有 systemd 时的 Linux 方案）。
#
# 写入两行（带标记，便于替换/卸载）：
#   0 12 * * *  每天 12:00 跑
#   @reboot      开机补跑（脚本内部有"到点才跑 + 当天打卡"，早于 12:00 会自行跳过）
#
# 前提：cron 守护进程在跑，且会在 WSL 启动时自动运行（`service cron status` 可查）。
# 若 cron 没在跑：需要 root，`sudo service cron start`；要开机自启可给 /etc/wsl.conf 加
#   [boot]
#   command="service cron start"
#
# 用法：
#   ./ops/install_hf_daily_cron.sh              # 安装/覆盖
#   ./ops/install_hf_daily_cron.sh --uninstall  # 移除
set -euo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
MARK="# papercast-hf-daily"
JOB="$WS/ops/hf_daily_job.sh"

if [ "${1:-}" = "--uninstall" ]; then
  tmp="$(mktemp)"
  crontab -l 2>/dev/null | grep -vF "$MARK" > "$tmp" || true
  crontab "$tmp"; rm -f "$tmp"
  echo "已移除 cron 任务（$MARK）"
  exit 0
fi

command -v crontab >/dev/null || { echo "没有 crontab。" >&2; exit 1; }

tmp="$(mktemp)"
crontab -l 2>/dev/null | grep -vF "$MARK" > "$tmp" || true
cat >> "$tmp" <<EOF
0 12 * * * $JOB $MARK
@reboot $JOB $MARK
EOF
crontab "$tmp"; rm -f "$tmp"

echo "已安装："
crontab -l | grep -F "$MARK"
echo
if ! pgrep -x cron >/dev/null 2>&1 && ! pgrep -x crond >/dev/null 2>&1; then
  echo "⚠ 当前 cron 守护进程没在跑，定时不会触发。需要 root 启动：sudo service cron start" >&2
  echo "  （并考虑在 /etc/wsl.conf 加 [boot] command=\"service cron start\" 让 WSL 启动时自动起 cron）" >&2
fi
