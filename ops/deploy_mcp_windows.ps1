#Requires -Version 5.1
<#
    ⚠ 本文件必须保存为「UTF-8 with BOM」。
    Windows PowerShell 5.1 在没有 BOM 时会按系统 ANSI（简体中文 = GBK）解析 .ps1，
    中文注释/字符串会被拆成非法字节，直接报 ParserError。若用编辑器改过本文件，
    请确认 BOM 还在；修复命令见 ops/deploy_mcp_windows.sh 的注释。

.SYNOPSIS
    把 ops/bin 下的 Windows 版 xiaohongshu-mcp 部署到本机（默认 E:\xhs-test），
    并把自带的 Chrome 缓存重定向到目标目录，避免占用 C: 盘。

.DESCRIPTION
    为什么需要重定向：Go 在 Windows 上 os.UserCacheDir() 读 %LocalAppData%，
    而全仓库只有 browser/browser_download.go 一处用缓存目录，所以给进程设这个
    环境变量即可把 424.6MB 的 Chrome 放到任意盘，无需改代码。启动器里已经设好。

    为什么默认放 E:：C: 盘通常很紧张（本机曾只剩 8.5GB）。

    注意：本脚本只做部署与 /health 冒烟，不会对小红书发起任何账号相关请求。

.PARAMETER SourceRoot
    工作区根目录的 Windows 路径（UNC 或盘符均可），由 ops/deploy_mcp_windows.sh 传入。

.PARAMETER TargetDir
    目标目录，默认 E:\xhs-test。

.PARAMETER ServePort
    启动器 serve.cmd 里使用的端口，默认 127.0.0.1:18060。

.PARAMETER TestPort
    冒烟测试用的端口。**必须与 ServePort 不同**，否则会撞上正在轮询 18060 的前后端。
    默认 127.0.0.1:18061。

.PARAMETER SkipVerify
    跳过冒烟测试（不启动进程）。

.EXAMPLE
    powershell -File deploy_mcp_windows.ps1 -SourceRoot '\\wsl.localhost\Ubuntu\home\yydh\hack'
#>
param(
    [Parameter(Mandatory = $true)][string]$SourceRoot,
    [string]$TargetDir = 'E:\xhs-test',
    [string]$ServePort = '127.0.0.1:18060',
    [string]$TestPort  = '127.0.0.1:18061',
    [switch]$SkipVerify
)

$ErrorActionPreference = 'Stop'

# 统一输出编码为 UTF-8：本脚本的正式入口是 WSL 侧的 ops/deploy_mcp_windows.sh，那边是 UTF-8；
# 不设的话 PowerShell 会按系统 ANSI(GBK) 输出，两段中文混在同一个流里就会乱码。
# （在 Windows 控制台里若显示异常，用 chcp 65001 或 Windows Terminal。）
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Say($m) { Write-Output $m }
function Step($m) { Write-Output ""; Write-Output "== $m ==" }

# --- 0) 参数校验 ---------------------------------------------------------------
Step "0) validate"
if (-not (Test-Path $SourceRoot)) { throw "SourceRoot not found: $SourceRoot" }
$binSrc = Join-Path $SourceRoot 'ops\bin'
if (-not (Test-Path $binSrc)) { throw "ops/bin not found under SourceRoot. Run ./ops/build_mcp.sh first." }
foreach ($n in 'xiaohongshu-mcp.exe', 'xiaohongshu-login.exe') {
    if (-not (Test-Path (Join-Path $binSrc $n))) {
        throw "$n missing in $binSrc. Run ./ops/build_mcp.sh first (it cross-compiles the .exe)."
    }
}
if ($TestPort -eq $ServePort)   { throw "TestPort must differ from ServePort (a poller may be hitting ServePort)." }
Say "   SourceRoot : $SourceRoot"
Say "   TargetDir  : $TargetDir"
Say "   ServePort  : $ServePort"
Say "   TestPort   : $TestPort"

# --- 1) 停掉在跑的实例 ---------------------------------------------------------
Step "1) stop running instances"
$running = Get-Process -Name 'xiaohongshu-mcp' -ErrorAction SilentlyContinue
if ($running) {
    $running | ForEach-Object { Say "   stopping pid=$($_.Id)"; Stop-Process -Id $_.Id -Force }
    Start-Sleep -Seconds 2
} else { Say "   none running" }

# --- 2) 目录 -------------------------------------------------------------------
Step "2) create directories"
$cacheRoot = Join-Path $TargetDir 'cache'
New-Item -ItemType Directory -Force -Path $TargetDir, $cacheRoot | Out-Null
Say "   $TargetDir"
Say "   $cacheRoot   (becomes LOCALAPPDATA for the app)"

# --- 3) 复制二进制 -------------------------------------------------------------
Step "3) copy binaries"
foreach ($n in 'xiaohongshu-mcp.exe', 'xiaohongshu-login.exe') {
    Copy-Item -LiteralPath (Join-Path $binSrc $n) -Destination $TargetDir -Force
    $kb = [math]::Round((Get-Item (Join-Path $TargetDir $n)).Length / 1KB, 1)
    Say "   $n  $kb KB"
}

# cookies.json 按 cwd 解析；已存在则不覆盖，避免踩掉本地登录态
$cookiesSrc = Join-Path $SourceRoot 'apps\xiaohongshu-mcp\cookies.json'
$cookiesDst = Join-Path $TargetDir 'cookies.json'
if (Test-Path $cookiesDst) {
    Say "   cookies.json kept (already present)"
} elseif (Test-Path $cookiesSrc) {
    Copy-Item -LiteralPath $cookiesSrc -Destination $cookiesDst -Force
    Say "   cookies.json copied (carries the fingerprint seed over)"
} else {
    Say "   no cookies.json at source; app will create one on first use"
}

# --- 4) 搬运已下载的浏览器缓存（省掉一次 181MB 下载）---------------------------
Step "4) relocate existing browser cache (if any)"
$oldCache = Join-Path $env:LOCALAPPDATA 'xiaohongshu-mcp'
$newCache = Join-Path $cacheRoot 'xiaohongshu-mcp'
$browserExe = Get-ChildItem -Path $newCache -Recurse -Filter 'chrome.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($browserExe) {
    Say "   target cache already has chrome.exe; leaving it as is"
} elseif (Test-Path $oldCache) {
    Move-Item -LiteralPath $oldCache -Destination $newCache -Force
    $mb = [math]::Round((Get-ChildItem -Recurse -File $newCache | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
    Say "   moved $mb MB  $oldCache -> $newCache"
} else {
    Say "   no cache on C:; first run will download ~181MB into $newCache"
}

# --- 5) 生成启动器 -------------------------------------------------------------
Step "5) write launchers"
$serveCmd = @"
@echo off
rem Start xiaohongshu-mcp. Browser cache is pinned next to this script, keeping C: free.
set "LOCALAPPDATA=%~dp0cache"
cd /d "%~dp0"
"%~dp0xiaohongshu-mcp.exe" -headless=false -port $ServePort %*
"@
Set-Content -Path (Join-Path $TargetDir 'serve.cmd') -Value $serveCmd -Encoding ASCII

$loginCmd = @"
@echo off
rem Headed QR login: opens a real Chrome window. Scan with the Xiaohongshu app.
set "LOCALAPPDATA=%~dp0cache"
cd /d "%~dp0"
"%~dp0xiaohongshu-login.exe" %*
"@
Set-Content -Path (Join-Path $TargetDir 'login.cmd') -Value $loginCmd -Encoding ASCII
Say "   serve.cmd  ->  -headless=false -port $ServePort"
Say "   login.cmd  ->  headed QR login"
Say "   注意 serve.cmd 默认有头（-headless=false）：能看见浏览器，也能天然阻止高频轮询"

# --- 6) 冒烟测试 ---------------------------------------------------------------
if ($SkipVerify) {
    Step "6) verify  SKIPPED (-SkipVerify)"
} else {
    Step "6) verify (starts on $TestPort, hits /health only, then stops)"
    $env:LOCALAPPDATA = $cacheRoot
    $errLog = Join-Path $env:TEMP 'xhs-verify.err.log'
    $outLog = Join-Path $env:TEMP 'xhs-verify.out.log'
    Remove-Item $errLog, $outLog -Force -ErrorAction SilentlyContinue

    $p = Start-Process -FilePath (Join-Path $TargetDir 'xiaohongshu-mcp.exe') `
        -ArgumentList '-headless=true', '-port', $TestPort `
        -WorkingDirectory $TargetDir `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -PassThru
    Say "   started pid=$($p.Id)"
    Start-Sleep -Seconds 6

    try {
        $r = Invoke-WebRequest "http://$TestPort/health" -TimeoutSec 8 -UseBasicParsing
        Say "   /health = HTTP $($r.StatusCode)"
    } catch { Say "   /health FAILED: $($_.Exception.Message)" }

    $log = Get-Content $errLog -Raw -ErrorAction SilentlyContinue
    ($log -split "`r?`n") | Where-Object { $_ -match 'browser binary' } | ForEach-Object { Say ("   " + $_.Trim()) }
    if ($log -match 'download') { Say "   WARN re-downloaded the browser (cache redirect did not take effect?)" }
    else { Say "   OK   reused the browser cache, no download" }

    Get-Process -Name 'xiaohongshu-mcp' -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force }
    Start-Sleep -Seconds 2
    Say "   stopped; $TestPort released"
}

# --- 7) 汇总 -------------------------------------------------------------------
Step "7) result"
Get-ChildItem $TargetDir -Force | ForEach-Object {
    if ($_.PSIsContainer) { Say ("   " + $_.Name + "\") }
    else { Say ("   " + $_.Name + "  " + [math]::Round($_.Length / 1KB, 1) + " KB") }
}
$cacheMb = 0
if (Test-Path $cacheRoot) {
    $cacheMb = [math]::Round((Get-ChildItem -Recurse -File $cacheRoot | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
}
Say "   cache size: $cacheMb MB"
Say ("   C: free " + [math]::Round((Get-PSDrive C).Free / 1GB, 1) + " GB")
if (Test-Path 'E:\') { Say ("   E: free " + [math]::Round((Get-PSDrive E).Free / 1GB, 1) + " GB") }
Say ""
Say "下一步："
Say "  有头扫码登录   ->  $TargetDir\login.cmd"
Say "  起服务(18060)  ->  $TargetDir\serve.cmd"
Say "  WARNING: 起 serve.cmd 之前，先确认没有前端/后端在轮询 18060，"
Say "           否则每次轮询都会开一个真实浏览器去访问小红书。"
