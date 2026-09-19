#!/usr/bin/env bash
# Windows 侧 xiaohongshu-mcp 的起停封装（从 WSL 调用）。
#
# 为什么要有这个脚本：
#
# 1. **默认的 MCP 跑在 Windows 上**，不是 Linux。Linux 侧的形态是「无头 Chromium +
#    指纹伪装成 Windows + stealth 关闭」（见 browser/browser.go 的 WithHeadless/WithFingerprint/
#    WithStealthJS），在原生 Windows 上可以用真实有头 Chrome，指纹与真实 OS 一致，风控暴露面更小。
#    背景见 docs/xhs-account-safety.md。
#
# 2. **WSL 的 `ss` 看不到 Windows 的监听**（实测：Windows 起在 18060，WSL 里 `ss -ltn` 一片空白）。
#    所以这里所有存活检测都走 HTTP /health，而不是端口。start_all.sh 里 mcp 也因此单独用一个 probe。
#
# 3. PowerShell 的引号与编码在 bash 里极难拼对（踩过 GBK 乱码、MissingEndCurlyBrace），
#    所以统一用 `-EncodedCommand`：脚本按 UTF-16LE 编码再 base64，bash 侧只剩一串 ASCII，
#    引号怎么嵌套都安全。
#
# 4. 启动前会比对 Windows 侧 exe 与本地构建的 SHA256。不一致就重新部署 —— 这是防
#    「Windows 上悄悄跑着旧版、而旧版没有护栏」的兜底，别删。
#
# 用法：
#   ./ops/mcp_windows.sh start     # 确保已部署最新版，然后拉起
#   ./ops/mcp_windows.sh stop      # 停 MCP 与它自己的浏览器
#   ./ops/mcp_windows.sh status    # 活着吗、跑的是不是最新版
#   ./ops/mcp_windows.sh log [n]   # 读 Windows 侧日志（默认末尾 40 行）
#
# 环境变量：
#   XHS_MCP_WIN_DIR    Windows 侧部署目录，默认 E:\xhs-test
#   XHS_MCP_PORT       端口，默认 18060
#   XHS_MCP_HEADLESS   是否无头，默认 false（有头才是有意为之，见上面第 1 条）
set -uo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
WIN_DIR="${XHS_MCP_WIN_DIR:-E:\\xhs-test}"
PORT="${XHS_MCP_PORT:-18060}"
HEADLESS="${XHS_MCP_HEADLESS:-false}"
LOCAL_EXE="$WS/ops/bin/xiaohongshu-mcp.exe"

say() { echo "  $*"; }
die() { echo "  ❌ $*" >&2; exit 1; }

# 去掉结尾的反斜杠，避免拼出 E:\xhs-test\\
WIN_DIR="${WIN_DIR%/}"
case "$WIN_DIR" in *\\) WIN_DIR="${WIN_DIR%\\}" ;; esac
case "$WIN_DIR" in
  *\'*) die "XHS_MCP_WIN_DIR 里含单引号，本脚本不处理这种路径：$WIN_DIR" ;;
esac

command -v powershell.exe >/dev/null 2>&1 \
  || die "找不到 powershell.exe（不在 WSL，或没开 interop）。Windows 侧起停需要它。"

# 日志按端口分文件：默认端口用 mcp.log（文档里写的就是这个路径），别的端口用 mcp-<port>.log。
# 为什么必须分开：两个实例共用同一个日志文件时，第二个实例的 cmd 打不开重定向目标，
# 会**静默地什么都没起**（WMI 还老老实实返回成功），排查成本极高 —— 踩过。
LOGPATH="$WIN_DIR\\logs\\mcp.log"
[ "$PORT" = "18060" ] || LOGPATH="$WIN_DIR\\logs\\mcp-$PORT.log"

ps_encoded() {
  local b64
  # $ProgressPreference 必须放在最前面：否则 PS 5.1 会把「正在准备首次使用模块」这类进度记录
  # 以 CLIXML 形式写到 stderr，混进调用方的输出里（踩过，输出里会冒出 #< CLIXML 和一段乱码）。
  b64="$(printf '%s' "\$ProgressPreference='SilentlyContinue'; $1" | iconv -f UTF-8 -t UTF-16LE | base64 -w0)" \
    || die "编码 PowerShell 脚本失败"
  # stdin 从 /dev/null 走：别让 PowerShell 去读调用方的终端/管道
  powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand "$b64" < /dev/null
}

# 存活检测走 HTTP：ss 看不到 Windows 的监听，HTTP 才是跨 WSL/Windows 都成立的判据
alive() { curl -s -o /dev/null --max-time 3 "http://127.0.0.1:$PORT/health"; }

local_exe_hash() { sha256sum "$LOCAL_EXE" 2>/dev/null | cut -d' ' -f1; }

win_exe_hash() {
  ps_encoded "\$p='$WIN_DIR\\xiaohongshu-mcp.exe'; if (Test-Path \$p) { (Get-FileHash \$p -Algorithm SHA256).Hash.ToLower() } else { '' }" \
    2>/dev/null | tr -d '\r\n '
}

# 确保 Windows 侧跑的是本地刚构建的那个版本。不一致就重新部署（部署很轻：只拷 exe，
# 浏览器缓存已存在时不会重下 181MB）。
ensure_deployed() {
  [ -f "$LOCAL_EXE" ] || die "本地没有 $LOCAL_EXE，先跑 ./ops/build_mcp.sh"

  local lh wh reason=""
  lh="$(local_exe_hash)"
  wh="$(win_exe_hash)"

  if [ -z "$wh" ]; then
    reason="Windows 侧还没有 exe"
  elif [ "$lh" != "$wh" ]; then
    reason="Windows 侧 exe 与本地构建不一致（多为旧版，可能不含护栏）"
  else
    return 0
  fi

  say "$reason，先重新部署"
  "$WS/ops/deploy_mcp_windows.sh" >/dev/null 2>&1 \
    || die "部署失败。单独跑 ./ops/deploy_mcp_windows.sh 看细节"

  wh="$(win_exe_hash)"
  [ "$lh" = "$wh" ] || die "部署后哈希仍不一致，不再继续（Windows 侧可能是别的构建）"
  say "部署完成，哈希已对齐"
}

cmd_start() {
  if alive; then
    say "127.0.0.1:$PORT 已有 MCP 在响应，跳过"
    return 0
  fi

  ensure_deployed

  # 建日志目录（不涉及进程创建，不会挂）
  ps_encoded "\$d='$WIN_DIR\\logs'; if (-not (Test-Path \$d)) { New-Item -ItemType Directory -Path \$d | Out-Null }" >/dev/null 2>&1

  # ⚠️ 这里必须用 WMI 创建进程，**不要**改回 Start-Process。
  # 从 WSL 调 PowerShell 时，Start-Process 拉起的子进程会继承控制台句柄，于是
  # `./ops/start_all.sh mcp | ...` 这类用法会永久挂住（实测 exit=124 超时，
  # 而服务其实已经正常起好了，极具误导性）。WMI 的 Win32_Process.Create 创建的进程
  # 完全脱离、不继承任何句柄。代价是输出重定向得自己写进 cmd 行（见下面 >> 那段）。
  # 这样也顺带满足了两件事：LOCALAPPDATA 让浏览器缓存落到 E: 而不是 C:；
  # cd 到部署目录让 cookies.json（cwd 相对路径）解析到 Windows 侧那一份。
  local line="set \"LOCALAPPDATA=$WIN_DIR\\cache\" && cd /d \"$WIN_DIR\""
  line+=" && \"$WIN_DIR\\xiaohongshu-mcp.exe\" -headless=$HEADLESS -port 127.0.0.1:$PORT"
  line+=" >> \"$LOGPATH\" 2>&1"

  ps_encoded "Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine='cmd /c $line'} | Out-Null" >/dev/null 2>&1 \
    || die "WMI 创建进程失败"

  local i
  for i in $(seq 1 25); do
    sleep 1
    if alive; then
      say "已启动（Windows 侧，有头=$HEADLESS）-> http://127.0.0.1:$PORT"
      say "日志 $LOGPATH"
      return 0
    fi
  done

  say "⚠️ 25 秒内 /health 无响应。Windows 日志末尾："
  cmd_log 25
  return 1
}

cmd_stop() {
  # ⚠️ 进程必须**按端口**筛，不能按进程名全杀。
  # 踩过：拿 XHS_MCP_PORT=18073 跑一个测试实例，stop 时按名字全杀，
  # 把 18060 上的正主一起干掉了，而且毫无提示。
  local port_match="*:$PORT*"

  local procs
  procs="$(ps_encoded "Get-CimInstance Win32_Process -Filter \"Name='xiaohongshu-mcp.exe'\" | Where-Object { \$_.CommandLine -like '$port_match' } | Measure-Object | Select-Object -ExpandProperty Count" 2>/dev/null | tr -d '\r\n ')"
  if ! alive && [ "${procs:-0}" = "0" ]; then
    say "Windows 侧 $PORT 上没有 MCP 在跑"
    return 0
  fi

  # 先收这个实例的进程树，再停 MCP。
  #
  # ⚠️ 浏览器**不能**按「exe 路径里含部署目录」全杀：那样会把别的端口上的实例的浏览器
  # 一起收掉。踩过：只停 18076 这个测试实例，却把 18060 正主正在用的 Chrome 窗口关了，
  # 用户看到浏览器窗口莫名消失。
  # 改成按「是不是目标 MCP 进程的后代」判定：rod 拉起的 chrome 可能是直接子进程，
  # 也可能再深一层，所以向下走几层把整棵树扫出来。
  local script="\$all=Get-CimInstance Win32_Process"
  script+="; \$mcps=@(\$all | Where-Object { \$_.Name -eq 'xiaohongshu-mcp.exe' -and \$_.CommandLine -like '$port_match' })"
  script+="; \$ids=@(\$mcps | ForEach-Object { \$_.ProcessId })"
  script+="; \$desc=@(\$ids)"
  script+="; for (\$i=0; \$i -lt 5; \$i++) { \$desc += @(\$all | Where-Object { (\$desc -contains \$_.ParentProcessId) -and (\$desc -notcontains \$_.ProcessId) } | ForEach-Object { \$_.ProcessId }) }"
  script+="; \$mcps | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }"
  script+="; Start-Sleep -Milliseconds 400"
  script+="; \$desc | Where-Object { (\$_ -ne 0) -and (\$ids -notcontains \$_) } | ForEach-Object { Stop-Process -Id \$_ -Force -ErrorAction SilentlyContinue }"

  ps_encoded "$script" >/dev/null 2>&1

  local i
  for i in $(seq 1 10); do
    alive || { say "$PORT 已停止（含它自己的浏览器）"; return 0; }
    sleep 1
  done
  say "⚠️ $PORT 仍有响应，可能还有别的实例占着"
  return 1
}

cmd_status() {
  if alive; then
    say "✅ HTTP 127.0.0.1:$PORT 有响应"
  else
    say "⚪ HTTP 127.0.0.1:$PORT 无响应"
  fi

  local procs
  procs="$(ps_encoded "Get-Process -Name 'xiaohongshu-mcp' -ErrorAction SilentlyContinue | ForEach-Object { 'pid=' + \$_.Id + '  start=' + \$_.StartTime }" 2>/dev/null | tr -d '\r')"
  if [ -n "$procs" ]; then
    printf '%s\n' "$procs" | sed 's/^/  Windows 进程: /'
  else
    say "Windows 侧无 MCP 进程"
  fi

  local lh wh
  lh="$(local_exe_hash)"
  wh="$(win_exe_hash)"
  if [ -z "$wh" ]; then
    say "Windows 侧未部署"
  elif [ "$lh" = "$wh" ]; then
    say "版本：与本地构建一致（含护栏）"
  else
    say "⚠️ 版本：与本地构建不一致，可能是旧版（不含护栏）；start 时会自动重新部署"
  fi
}

cmd_log() {
  local n="${1:-40}"
  ps_encoded "Get-Content -LiteralPath '$LOGPATH' -Tail $n -ErrorAction SilentlyContinue" 2>/dev/null | tr -d '\r'
}

case "${1:-}" in
  start)  cmd_start ;;
  stop)   cmd_stop ;;
  status) cmd_status ;;
  log)    cmd_log "${2:-40}" ;;
  *)      die "用法: $0 start|stop|status|log [n]" ;;
esac
