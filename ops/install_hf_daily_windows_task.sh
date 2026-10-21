#!/usr/bin/env bash
# 在 WSL2（没开 systemd、cron 也不跑）里，用 Windows 任务计划程序 + 登录自启
# 安装 HF Daily Papers 每日任务。这是本机（WSL2 旧式 init）唯一实际可用的方案。
#
# 机制：
#   - Windows 计划任务 `PaperCast-HF-Daily`：每天 12:00 调用 wsl.exe → ops/hf_daily_job.sh；
#   - 登录自启 `hf_daily.vbs`（放进 Startup 文件夹，隐藏窗口）：每次登录都调一次，
#     由脚本内部"到点才跑 + 当天打卡"决定是否真跑 —— 这就是**关机/错过后的补跑**。
#   - 两者都有单实例锁，重复触发安全。
#
# 为什么不用 systemd / cron：本机 PID1 是 WSL 的 init(Ubuntu)，没开 systemd；cron 守护
# 进程也没运行且开机不自启（要 root）。若以后开了 systemd，改用 install_hf_daily_timer.sh。
#
# 用法：
#   ./ops/install_hf_daily_windows_task.sh              # 安装
#   ./ops/install_hf_daily_windows_task.sh --uninstall  # 卸载
set -euo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
JOB="$WS/ops/hf_daily_job.sh"
TASK="PaperCast-HF-Daily"
LUSER="$(whoami)"

WSL="/mnt/c/Windows/System32/wsl.exe"
[ -x "$WSL" ] || { echo "找不到 wsl.exe（不是 WSL 环境？）" >&2; exit 1; }

winpath() { # C:\Users\x → /mnt/c/Users/x
  printf '/mnt/c/%s' "$(printf '%s' "$1" | sed 's|^[A-Za-z]:[\\/]||; s|\\|/|g')"
}
winvar() { cmd.exe /c "echo %$1%" 2>/dev/null | tr -d '\r'; }

LOCALAPPDATA_W="$(winvar LOCALAPPDATA)"
APPDATA_W="$(winvar APPDATA)"
WUSER="$(winvar USERNAME)"
DISTRO="${WSL_DISTRO_NAME:-$("$WSL" -l -q 2>/dev/null | tr -d '\0\r' | head -1)}"

APPDIR_W="$LOCALAPPDATA_W\\PaperCast"
CMD_W="$APPDIR_W\\hf_daily.cmd"
VBS_W="$APPDATA_W\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\hf_daily.vbs"
APPDIR="$(winpath "$LOCALAPPDATA_W")/PaperCast"
STARTUP="$(winpath "$APPDATA_W")/Microsoft/Windows/Start Menu/Programs/Startup"

if [ "${1:-}" = "--uninstall" ]; then
  schtasks.exe /delete /tn "$TASK" /f >/dev/null 2>&1 || true
  rm -f "$APPDIR/hf_daily.cmd" "$STARTUP/hf_daily.vbs"
  echo "已卸载：计划任务 $TASK + 登录自启 hf_daily.vbs"
  exit 0
fi

mkdir -p "$APPDIR" "$STARTUP"

# Windows .cmd 包装（CRLF）：隐藏细节，把 wsl 调用固定下来，避免任务里引号地狱
printf '@echo off\r\n"%s" -d %s -u %s -- bash -lc "%s"\r\n' \
  'C:\Windows\System32\wsl.exe' "$DISTRO" "$LUSER" "$JOB" > "$APPDIR/hf_daily.cmd"

# 登录自启（隐藏窗口）
printf 'CreateObject("WScript.Shell").Run """%s""", 0, False\r\n' "$CMD_W" > "$STARTUP/hf_daily.vbs"

# 每日 12:00 的计划任务（非提升权限可创建；ONLOGON 触发器需管理员，故用 Startup 代替）
schtasks.exe /create /tn "$TASK" /tr "$CMD_W" /sc DAILY /st 12:00 /f >/dev/null

echo "已安装："
echo "  计划任务 : $TASK（每天 12:00，命令 $CMD_W）"
echo "  登录自启 : $STARTUP/hf_daily.vbs（每次登录补跑，脚本内部判断是否到点）"
echo
schtasks.exe /query /tn "$TASK" /fo LIST 2>/dev/null | iconv -f GBK -t UTF-8 2>/dev/null | tr -d '\r' | \
  grep -aE "任务名|下次运行时间|状态" || true
echo
echo "手动试跑：schtasks.exe /run /tn \"$TASK\""
echo "日志：tail -f $WS/var/logs/hf-daily-job.log"
