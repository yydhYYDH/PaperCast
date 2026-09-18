#!/usr/bin/env bash
# 把 ops/bin 下的 Windows 版 xiaohongshu-mcp 部署到 Windows 本机（默认 E:\xhs-test）。
#
# 本脚本是 WSL 侧的入口：它负责按规范推导工作区路径（不写死 /home/yydh/hack），
# 再用 wslpath 转成 Windows 路径，交给 ops/deploy_mcp_windows.ps1 干活。
#
# 为什么要有 Windows 版：Linux 侧跑的是「无头 Chromium + 指纹伪装成 Windows」
# （见 apps/xiaohongshu-mcp/browser/browser.go 的 WithFingerprint("")），
# 这本身是可检测特征；原生 Windows 上可以用真实有头 Chrome，指纹与真实 OS 一致。
#
# 用法：
#   ./ops/deploy_mcp_windows.sh                       # 部署到 E:\xhs-test 并冒烟验证
#   ./ops/deploy_mcp_windows.sh -SkipVerify           # 只部署不启动
#   ./ops/deploy_mcp_windows.sh -TargetDir 'D:\xhs'   # 换目标盘
#   ./ops/deploy_mcp_windows.sh -ServePort '127.0.0.1:18060' -TestPort '127.0.0.1:18061'
#
# 说明：冒烟测试只打 /health，不会对小红书发起任何账号相关请求。
set -euo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
PS1="$WS/ops/deploy_mcp_windows.ps1"
BIN="$WS/ops/bin"

command -v powershell.exe >/dev/null 2>&1 || {
    echo "找不到 powershell.exe：本脚本只能从 WSL 调用 Windows 侧。" >&2
    exit 1
}
[ -f "$PS1" ] || { echo "缺少 $PS1" >&2; exit 1; }

# 先确保 .exe 存在；缺了就顺手编（build_mcp.sh 会一起编 Windows 版）
if [ ! -f "$BIN/xiaohongshu-mcp.exe" ] || [ ! -f "$BIN/xiaohongshu-login.exe" ]; then
    echo "== ops/bin 下缺少 Windows 版 .exe，先执行 build_mcp.sh =="
    "$WS/ops/build_mcp.sh"
fi

PS1_WIN="$(wslpath -w "$PS1")"
WS_WIN="$(wslpath -w "$WS")"

echo "== 工作区(Windows 视角): $WS_WIN =="
echo "== 部署脚本: $PS1_WIN =="

# 不要把 powershell 的输出接进管道：被启动的子进程会继承句柄，
# 管道等不到 EOF 就会假死（踩过一次），所以直接透传。
exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PS1_WIN" -SourceRoot "$WS_WIN" "$@"
