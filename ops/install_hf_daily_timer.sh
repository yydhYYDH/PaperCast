#!/usr/bin/env bash
# 安装/卸载 HF Daily Papers 每日定时任务（systemd user timer，每天 12:00）。
#
# 用法：
#   ./ops/install_hf_daily_timer.sh              # 安装并启用
#   ./ops/install_hf_daily_timer.sh --uninstall  # 停止并移除
#
# 关机补偿依赖 timer 的 Persistent=true：到点机器没开，开机后补跑一次。
# 需要 user systemd 可用（WSL2 已开 systemd 的机器默认可以）。若 `systemctl --user`
# 连不上总线，多半是没开启用户级 systemd 会话，按脚本末尾提示处理。
set -euo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE="papercast-hf-daily.service"
TIMER="papercast-hf-daily.timer"

if [ "${1:-}" = "--uninstall" ]; then
  systemctl --user disable --now "$TIMER" 2>/dev/null || true
  rm -f "$UNIT_DIR/$SERVICE" "$UNIT_DIR/$TIMER"
  systemctl --user daemon-reload 2>/dev/null || true
  echo "已卸载 $TIMER / $SERVICE"
  exit 0
fi

command -v systemctl >/dev/null || { echo "没有 systemctl，装不了 systemd timer。" >&2; exit 1; }

mkdir -p "$UNIT_DIR"
# 把 @WS@ 替换成本仓库路径后落盘（仓库路径不写死在模板里）。
sed "s|@WS@|$WS|g" "$WS/ops/systemd/$SERVICE" > "$UNIT_DIR/$SERVICE"
cp "$WS/ops/systemd/$TIMER" "$UNIT_DIR/$TIMER"

if ! systemctl --user daemon-reload 2>/dev/null; then
  echo "systemctl --user 连不上（用户级 systemd 未运行）。单元已写入 $UNIT_DIR，" >&2
  echo "请在有 DBus 会话的登录环境下重跑，或执行：loginctl enable-linger $USER" >&2
  exit 1
fi

systemctl --user enable --now "$TIMER"
# 让用户服务在未登录时也能跑（开机补跑依赖它）。失败不致命，多数桌面环境本就开着。
loginctl enable-linger "$USER" 2>/dev/null || \
  echo "提示：未能 enable-linger（可能需要 sudo）；仅影响未登录时的补跑。"

echo
systemctl --user list-timers "$TIMER" --no-pager || true
echo
echo "已安装。手动试跑一次：systemctl --user start $SERVICE"
echo "看日志：journalctl --user -u $SERVICE -f   或   tail -f $WS/var/logs/hf-daily-job.log"
