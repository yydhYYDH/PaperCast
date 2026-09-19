# Windows 侧部署（小红书 MCP）

> 为什么会有这条路径、怎么用、有哪些坑。脚本在 `ops/`，产物在 `E:\xhs-test`。

## 1. 为什么要跑在 Windows 上

不是为了性能，是**为了降低风控暴露面**。

`apps/xiaohongshu-mcp/browser/browser.go` 里这三行决定了 Linux 侧的实际形态：

```go
headless_browser.WithHeadless(headless),   // 默认 true = 无头
headless_browser.WithFingerprint(""),      // 空 = 按运行 OS 自动：Linux→windows，mac→macos
headless_browser.WithStealthJS(false),     // stealth 是关掉的
```

合起来就是：**无头 Chromium + 把指纹伪装成 Windows + 关闭 stealth**。
这三条单独看都不致命，叠在一起是相当典型的可检测特征。

移到原生 Windows 后：
- 指纹与真实 OS **一致**（不再需要伪装）
- 用的是**真实 Chrome 有头窗口**，不是无头

而且有头模式有个副作用是好事：**每次调用都会弹窗**，这天然阻止了「5 秒轮询一次」这种写法。

## 2. 架构：混合部署，只搬浏览器

```
Windows 原生
  └── xiaohongshu-mcp.exe  :18060     ← 真实 Chrome、有头、指纹与 OS 一致
              ▲
              │ 127.0.0.1 双向互通（mirrored networking，已实测）
              │
WSL2
  ├── papercast-server :8000          ← XHS_MCP_BASE 指过去即可，本来就是环境变量
  └── papercast (Vite) :5178
```

**只需要搬最容易触发风控的那一个部件**，后端/前端/渲染全不动。

## 3. 目录布局

```
E:\xhs-test\
├── xiaohongshu-mcp.exe      主程序（有头服务）
├── xiaohongshu-login.exe    扫码登录工具（硬编码有头，无参数）
├── cookies.json             会话 + fingerprint seed（按 cwd 解析）
├── serve.cmd                起服务，已内置缓存重定向
├── login.cmd                扫码登录
└── cache\                   作为 LOCALAPPDATA 传给进程
    └── xiaohongshu-mcp\browser\<版本>\browser\chrome.exe   （解压约 424 MB）
```

**为什么放 E:**：C: 盘常常很紧张（本机曾只剩 8.5 GB），而自带 Chrome 解压后 424 MB。

## 4. 脚本

| 脚本 | 作用 |
| --- | --- |
| `ops/build_mcp.sh` | 编 Linux 版 **+ 交叉编译 Windows 版 .exe**（`CGO_ENABLED=0`，纯静态 PE） |
| `ops/deploy_mcp_windows.sh` | WSL 侧入口：推导工作区路径 → `wslpath` 转 Windows 路径 → 调 .ps1 |
| `ops/deploy_mcp_windows.ps1` | 实际部署：复制产物、重定向缓存、生成启动器、`/health` 冒烟 |

用法：

```bash
./ops/build_mcp.sh                    # 编出 5 个产物（3 Linux + 2 Windows）
./ops/deploy_mcp_windows.sh           # 部署到 E:\xhs-test 并冒烟验证
./ops/deploy_mcp_windows.sh -SkipVerify
./ops/deploy_mcp_windows.sh -TargetDir 'D:\xhs'
```

部署后：

```powershell
E:\xhs-test\login.cmd    # 有头扫码登录（会开真实 Chrome 窗口）
E:\xhs-test\serve.cmd    # 起服务 18060
```

## 5. 关键机制：缓存重定向，零代码改动

全仓库**只有一处**用缓存目录：

```go
browser/browser_download.go:62:  base, err := os.UserCacheDir()
```

而 Go 在 Windows 上 `os.UserCacheDir()` 读的是 **`%LocalAppData%`**。
所以给进程设这个环境变量就能把 424 MB 的浏览器放到任意盘——**不用改代码**。

启动器里已经设好了：

```bat
set "LOCALAPPDATA=%~dp0cache"
```

验证方式是看启动日志：

```
using browser binary: E:\xhs-test\cache\xiaohongshu-mcp\browser\148.0.7778.215\browser\chrome.exe
```

并且**不应出现** `首次运行：下载内置浏览器` 那行（出现就说明重定向没生效，会重下 181 MB）。

## 6. 坑（都踩过）

### 6.1 mirrored networking 下 loopback 双向共享，但 Windows 看不全

Windows 能访问 WSL 的 `127.0.0.1:8000`，但 `Get-NetTCPConnection` 在 Windows 上**看不到**这个监听。

**危险后果**：起了 Windows 版 MCP 在 18060 后，WSL 的前端/后端会以为自己打的是 WSL 的实例，实际打到了 Windows 的——**你完全看不出来，而每次轮询都在开一个真实浏览器去访问小红书**。

**所以：两边不要同时跑 MCP；起 `serve.cmd` 前先确认没有轮询。**

### 6.2 `.ps1` 必须带 UTF-8 BOM

Windows PowerShell 5.1 在没有 BOM 时按系统 ANSI（简体中文 = GBK）解析 `.ps1`，中文注释/字符串会被拆成非法字节，直接 ParserError。

**注意 `edit` 之类的编辑工具会抹掉 BOM**，改完要重新加：

```powershell
$p = '<...>\ops\deploy_mcp_windows.ps1'
$c = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8)
[System.IO.File]::WriteAllText($p, $c, (New-Object System.Text.UTF8Encoding($true)))
```

校验：`[System.Management.Automation.Language.Parser]::ParseFile($p, [ref]$null, [ref]$err)`。

### 6.3 UNC 路径不能当 cwd

`\\wsl.localhost\...` 可以作为**参数**传给 Windows 程序，但**不能作为工作目录**。所以二进制必须先复制到本地盘（脚本已经做了）。

### 6.4 不要把 PowerShell 的输出接进管道

被 `Start-Process` 拉起的子进程会继承句柄，管道等不到 EOF 就会假死。
`ops/deploy_mcp_windows.sh` 里是直接透传，不接管道。

### 6.5 `build_mcp.sh` 末尾不要 `| head -3`

Go 的 usage 较长，`head` 提前退出会让左侧进程吃到 SIGPIPE，配上 `set -o pipefail` 会让整个脚本以 141 退出——**明明编译是成功的**。已改成先落文件再 `head`。

### 6.6 首次运行要下 181 MB

`cdn.one-world.ai` 下载 `windows-x64.zip`（实测 19 秒，解压 424 MB），落在 `%LocalAppData%\xiaohongshu-mcp\`——被重定向后就是 `E:\xhs-test\cache\`。

## 7. 还没验证的

- **Chrome 的 profile 目录（user-data-dir）落在哪没验证**。只验证了 Chrome **程序本体**在 E:。go-rod 可能把 profile 放到系统临时目录；若确实落 C:，可用同样手法重定向 `TEMP`/`TMP`。
- **有头模式的实际表现没完全验证**。已验证「Windows 侧 Chrome 确实能被拉起并访问小红书」（第一次 `login/status` 18.9 秒，之后命中缓存 0 秒），但**登录态没迁移过来**：Windows 实例报告 `login_required`，需要在 Windows 侧重新扫码（`login.cmd`）。

## 8. 默认已切到 Windows：怎么起的、踩了什么

**默认平台现在是 Windows**（`ops/start_all.sh` 里的 `XHS_MCP_PLATFORM`，默认 `windows`）。
由 `ops/mcp_windows.sh` 起停；服务器上没有 Windows 会自动回退到 Linux 侧二进制并打印警告，
本机也可以 `XHS_MCP_PLATFORM=wsl` 强制走 Linux。

```bash
./ops/start_all.sh mcp                 # 起（走 Windows）
./ops/mcp_windows.sh status            # 活着吗 / 跑的是不是最新版
./ops/mcp_windows.sh log 60            # 读 Windows 侧日志
./ops/mcp_windows.sh stop              # 停（只停 18060 这个实例）
./ops/stop_all.sh                      # 全停（已包含 Windows 侧）
```

切过去之后踩到的四个坑，都已修，**改这个脚本前先读**：

### 8.1 用 WMI 创建进程，不要用 `Start-Process`

从 WSL 调 PowerShell 时，`Start-Process` 拉起的子进程会继承控制台句柄，于是
`./ops/start_all.sh mcp | ...` 会**永久挂住**（实测 300 秒超时被 SIGTERM），
而**服务其实已经正常起好了**——极具误导性。改用
`Invoke-CimMethod -ClassName Win32_Process -MethodName Create`，创建的进程完全脱离、不继承句柄。
代价是输出重定向得自己写进 `cmd /c` 那一行里。

### 8.2 `stop` 必须按端口筛进程

按进程名 `xiaohongshu-mcp` 全杀会误伤别的端口上的实例。已经改成按
`CommandLine -like '*:<port>*'` 匹配。

### 8.3 浏览器要按「后代进程」收，不能按 exe 路径全杀

按 `ExecutablePath -like '*xhs-test*'` 全杀会把**别的端口实例正在用的浏览器**一起收掉。
踩过：只停 18076 这个测试实例，却把 18060 正主正在用的 Chrome 窗口关了，用户看到窗口莫名消失。
现在按「父进程链上是不是目标 MCP」判定（向下走 5 层，rod 拉起的 chrome 可能不止一层深）。

### 8.4 日志必须按端口分文件

两个实例共用同一个日志文件时，第二个实例的 `cmd` **打不开重定向目标**，
于是**静默地什么都没起**（WMI 还老老实实返回成功），排查成本极高。
现在默认端口写 `logs\mcp.log`，其他端口写 `logs\mcp-<port>.log`。

### 8.5 超时链路已核对过：不用改（别再「顺手放宽」）

一度以为「后端探测超时 8 秒、Windows 冷启浏览器 13–19 秒」会超时，**核对代码后确认是误判**：

```python
# apps/papercast-server/app/platforms.py 的 _xhs_probe()
timeout=8.0    # 只用于 /health —— 实测 82µs，8 秒足够
timeout=45.0   # 用于 /api/v1/login/status —— 本来就是 45 秒
```

`login/status` 那条**早就是 45 秒**。把 8.0 一起改大会让「MCP 挂了」要等 45 秒才报出来，是退步。

前端也没有 fetch 超时（没有 AbortController），会一直等，所以冷路径慢一点不影响界面。

实测参考值（2026-09-19，Windows 实例）：

| 场景 | 耗时 |
| --- | --- |
| `login/status` 冷启浏览器（Windows） | 8.2 / 13.7 / 18.9 秒（首次最慢，看 OS 文件缓存） |
| `login/status` 命中 MCP 缓存 | 0.0006 秒 |
| `GET /api/platforms` 冷路径 | 8.16 秒 |
| `GET /api/platforms` 热路径 | 0.01 秒 |

链路最紧的一环是 MCP 的 300 秒 TTL 缓存，不是超时。
**真要动，动的是缓存策略，不是超时。**

## 9. 相关

- 端口约定见 [`conventions.md`](conventions.md)
- 风控、轮询与账号恢复期约定见 [`xhs-account-safety.md`](xhs-account-safety.md)

