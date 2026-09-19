# 小红书账号安全 · 交接说明

> 2026-09-19 发生了真实的账号风控事件。这份文档说明**为什么会发生、已经修了什么、以及在账号恢复前不要做什么**。
> 下一个会话动小红书之前，先读完这一页。

## 0. 一句话

**不要在账号恢复期重启 MCP，也不要让任何东西以秒级轮询它。**
每次探测都会真的开一个浏览器访问 `xiaohongshu.com`——不是查询缓存，是**真实的浏览器会话**。

## 1. 发生了什么

用户确认账号出现**异常提示 / 要求验证 / 安全提醒**（2026-09-19 凌晨）。

客观证据（`var/logs/mcp.log`）：`GET /api/v1/login/status` 被持续调用，
**每次耗时 3.7–6.0 秒**——这个耗时就是一次真实浏览器加载。
一个小时内 57 次；MCP 每次被重启后，**几秒内**就开始被这样打。

同期还有：一次真实的测试发帖、对 `get_my_profile` 的反复重试（每次 60 秒超时）、
`notifications/list?limit=50` 连续三次、以及迁移时 `XDG_CACHE_HOME` 位置变化。

## 2. 根因链路

```
前端 apps/papercast/src/stores/platforms.ts   POLL_MS = 5000   ← 5 秒轮询
  → 后端 GET /api/platforms
  → apps/papercast-server/app/platforms.py:290  list_channels()
  → :176  _xhs_probe()                          ← 这一层没有缓存
  → MCP  GET /api/v1/login/status
  → 真的拉起一个 Chromium，导航到 xiaohongshu.com
```

**最讽刺的一处**：`platforms.ts:10` 的注释写着「后端每次探测都要开一次无头浏览器，别打太密」，
然后设了 `POLL_MS = 5000`。

量级：dashboard 开一小时 ≈ **260–720 次真实浏览器访问**，开一天上万次。
这不是"偶尔查一下"，是稳定的机器人流量。

## 3. 已经修了什么（2026-09-19）

### 3.1 访问预算 + 登录态缓存（`apps/xiaohongshu-mcp/guard.go`）

| 机制 | 说明 |
| --- | --- |
| `browserBudget` | 真实浏览器会话的滑动窗口计数。`newBrowser()` 是**唯一**咽喉（19 个调用点全走它），在那里记数，**没改签名** |
| `accessBudgetMiddleware` | 窗口饱和时对 `/api/v1/*` 返回 429，**fail closed**（多一次真实访问就多一分风险） |
| `statusCache` | 缓存 `login/status`。命中时**根本不会走到 `newBrowser()`**，所以轮询不再产生浏览器 |

环境变量：

```
XHS_BUDGET_MAX             窗口内允许的浏览器会话数，<=0 表示不限流（默认 30）
XHS_BUDGET_WINDOW_SECONDS  窗口长度（默认 600）
XHS_STATUS_TTL_SECONDS     login/status 缓存时长，<=0 表示不缓存（默认 300）
```

**实测效果**（2026-09-19 01:10，MCP 运行 15.5 分钟、43 次调用）：

```
login/status 调用次数: 43
真实浏览器会话次数:    15        ← 约每分钟 1 次，正好是 60s TTL 的封顶
```

日志里同一分钟内能直接看到缓存生效——未命中是**秒级**，命中是**微秒级**：

```
01:10:32  login/status   4.598889147s    ← 未命中，真开了浏览器
01:10:39  login/status        100.465µs  ← 命中
01:10:40  login/status         57.575µs  ← 命中
```

> ⚠️ **它是「封顶」，不是「消除」。** TTL 决定「无论上方轮询多密，都最多每 TTL 开一个浏览器」。
> TTL=60s 时是 60 次/小时；改成 300s 后是 12 次/小时。账号有风控标记时，**dashboard 不要长期开着**。

`login/status` 支持 `?force=1` 跳过缓存，供「用户主动点刷新」用；不要把 `force=1` 接到自动轮询上，
否则等于把缓存关掉（那时靠 30/10min 的预算兜底）。

**登录成功 / 删除 cookies 时会主动失效缓存**，所以扫码后不会等一个 TTL 才看到新状态——
这也是 TTL 可以设到 300s 的原因。

核心断言在 `guard_test.go::TestStatusCachePreventsBrowserLaunch`：
模拟 20 次轮询，访问预算消耗为 **0**。

### 3.2 `start_all.sh` 改指向带护栏的产物

**这是个容易再次踩的坑**：`ops/build_mcp.sh` 会产出两个 Linux 二进制：

| 产物 | 来源 | 是否含护栏 |
| --- | --- | --- |
| `ops/bin/xiaohongshu-mcp` | `git archive HEAD`（干净版） | 只在 `guard.go` **已提交**后才含护栏 |
| `ops/bin/xiaohongshu-mcp-auth` | 工作树版 | ✅ 含（还有鉴权改动） |

`start_all.sh` 原来启的是**干净版**。在 `guard.go` 提交之前，那等于**零护栏**——
账号被标记那次就是它。现已改为启 `xiaohongshu-mcp-auth`。

> **待办**：把 `guard.go` 提交。提交后干净版自带护栏，这个绕法就可以撤掉。
> 提交前若有人把它改回干净版，漏洞会原样重开——改这一行之前先读本文件。

## 4. 账号恢复期（建议 24–72 小时）不要做的事

- ❌ **不要重启 MCP**，也不要跑 `./ops/start_all.sh` 全量拉起
- ❌ 不要保留开着 dashboard 的浏览器标签（它 5 秒轮询一次）
- ❌ 不要反复重试扫码登录。风控期高频重登**会加重标记**
- ❌ 不要做任何自动化探测（`list_feeds` / `search_feeds` / `notifications` 同样都要开浏览器）
- ✅ 只用**手机 App 正常使用**。正常的真人行为比什么都有助于恢复

**Windows 有头登录路径已就绪（`E:\xhs-test\login.cmd`），但恢复期内先别跑。**
在一个被标记的账号上从新环境首次登录，可能反而加重标记。用法见
[`windows-deployment.md`](windows-deployment.md)。

## 5. 已经默认切到 Windows 有头（2026-09-19）

`apps/xiaohongshu-mcp/browser/browser.go` 里这三行决定了 Linux 侧的实际形态：

```go
headless_browser.WithHeadless(headless),   // 默认 true = 无头
headless_browser.WithFingerprint(""),      // 空 = 按运行 OS 自动：Linux→windows
headless_browser.WithStealthJS(false),     // stealth 是关掉的
```

合起来是「**无头 Chromium + 指纹伪装成 Windows + stealth 关闭**」——单独看都不致命，
叠在一起是相当典型的可检测特征。原生 Windows + 真实 Chrome + 有头能同时消掉这三条。

所以 **MCP 的默认平台现在是 Windows**：

```bash
./ops/start_all.sh mcp          # 默认就走 Windows（XHS_MCP_PLATFORM=windows）
XHS_MCP_PLATFORM=wsl ./ops/start_all.sh mcp   # 本机想强制走 Linux 时
```

服务器上没有 Windows 会自动回退到 Linux 侧并打印警告。起停由 `ops/mcp_windows.sh` 负责，
细节与踩过的坑见 [`windows-deployment.md`](windows-deployment.md) §8。

### 5.1 切换之后立刻要知道的两件事

1. **登录态没跟着过来。** Windows 实例用的是 `E:\xhs-test\cookies.json`，与 Linux 侧的
   `apps/xiaohongshu-mcp/cookies.json` 是**两份文件**，会各自分叉。实测切过去之后
   Windows 侧报告 `login_required`（detail：MCP 在线，但当前未登录）。
   要恢复小红书功能，得在 Windows 侧跑 `E:\xhs-test\login.cmd` 重新扫码——
   **但账号还在恢复期，现在不该扫**。
   部署脚本对已存在的 `cookies.json` 是**保留不覆盖**，所以不用担心旧 cookie 踩掉新登录。

2. **超时链路核对过了，不用动。** 一度以为「后端探测超时 8 秒 < Windows 冷启浏览器 13–19 秒」，
   核对代码后是**误判**：`_xhs_probe()` 里 `timeout=8.0` 那条只用于 `/health`（实测 82µs），
   而 `login/status` 那条**本来就是 45 秒**。前端也没有 fetch 超时，会一直等。
   实测冷路径 8.2–18.9 秒、热路径 0.01 秒，都在预算内。
   **别去改那个 8.0** —— 改大了会让「MCP 挂了」要等 45 秒才报出来。详见
   [`windows-deployment.md`](windows-deployment.md) §8.5。

## 5.2 缓存击穿：窗口「成对」弹出的真正原因（2026-09-19 已修）

现象：用户看到小红书网页**反复开启**，而且总是**一次弹两个**。

实测日志（修复前）：

```
浏览器会话： 07:13:16 ×2   07:19:16 ×2   07:25:15 ×2   07:31:16 ×2   ← 每 6 分钟一对
login/status：07:52:16 ×2   07:53:16 ×2   07:54:16 ×2   07:55:20 ×2  ← 每 60 秒一对
```

三层原因叠在一起：

1. **后端有两条独立路径都会碰 MCP**，而且节拍相同、几乎同时到达：
   - `GET /api/platforms` → `platforms.py::_xhs_probe()`（有 5 秒共享缓存）
   - `GET /api/env` → `main.py:196-205` **自己直接 httpx 调 `/api/v1/login/status`，完全绕过后端缓存**
   - 后端日志里两者调用数几乎相等（306 / 308），确认就是这一对。

2. **后端那 5 秒缓存挡不住"同一瞬间到达"**：两个请求同时检查缓存、同时发现已过期，
   于是两个都去探测——典型的缓存击穿（stampede / thundering herd）。

3. **MCP 侧的 `statusCache` 原本不是单飞的**，所以第 2 步的两个并发未命中
   各调一次 `newBrowser()`，**各开一个浏览器** → 用户看到成对弹窗。
   每 300 秒 TTL 到期一次，加上轮询相位，表现为「每约 6 分钟弹一对」。

**修复**：`guard.go` 给 `statusCache` 加 `begin()`/`end()` 单飞。
并发未命中时只有一个调用取得探测权，其余挂在同一个 `flight` 上等结果。

实测验证（两个请求同一瞬间并发打）：

| | 修复前 | 修复后 |
| --- | --- | --- |
| 新增浏览器会话 | 2 | **1** ✅ |
| 两个请求耗时 | 各自独立开 | 20.15s / 20.14s（第二个复用了第一个的结果） |

回归测试：`guard_test.go` 的 `TestStatusCacheSingleFlight` 与
`TestStatusCacheSingleFlightOnError`（含 `-race`）。

**已修**：`/api/env` 不再自己直连 MCP，改为复用 `platforms_mod.get_channel("xhs", force=False)`
——走 `_xhs_probe()` 与 `_XHS_CACHE`。这一步同时消掉两个问题：
① 探测次数不再翻倍（两条路径共用同一份缓存，也不会再同一瞬间双双未命中）；
② 那条 8 秒超时 / `timeout=6.0` 的短板没了（`login/status` 用的是 45 秒）。
字段仍写在 `publish.xiaohongshu` 下，与前端 `api/types.ts` 的 `EnvStatus` 对齐。

### 5.2.2 轮询不再主动探测：**禁止用本地 cookies 猜**

`CheckLoginStatus`（不带 force 的轮询路径）改成：

| 情况 | 行为 |
| --- | --- |
| TTL 内 | 直接返回 |
| 过期但查过 | **返回上次结果，不重新探测** |
| 进程启动后从没查过 | 真查一次（每个进程生命周期最多一次） |

要权威结果只能用 `?force=1`（`CheckLoginStatusForce`）。

**为什么不是「读本地 cookies.json 判断」——这个坑值得单独记一笔：**
本地文件**不能**用来判断登录态。实测当时的 `cookies.json` 有 18 个 cookie，
含 `web_session`、`id_token`、`unread`，看起来完全像已登录，
**但服务端会话其实早已失效**（真访问才发现是 `login_required`）。
本地文件只能证明「手里有 cookie」，不能证明「服务端还认它」。

所以正确做法是**复用上次真实验证过的结论**，而不是用一个会谎报的本地猜测。
代价：MCP 重启后只查一次，会话若在之后失效，轮询发现不了，要等真正发布才暴露
——对一个有风控标记的账号，这正是想要的：**别主动去碰它**。

回归测试：`TestStatusCachePeekIgnoresTTL`、
`TestCheckLoginStatusReusesStaleResultInsteadOfProbing`
（后者一旦退化成真探测，就会 `newBrowser()` 开浏览器，测试直接挂住）。

### 5.2.1 另一个坑：测试打真实业务端点会挂死

`auth_test.go` 原来拿 `/api/v1/login/status` 当"受保护接口"验鉴权，
而这个端点会**真开浏览器**，于是整个测试套件挂在 `browser.go` 上、60 秒超时。
受保护端点**全都是**小红书业务接口，没有一个便宜的可以替换，
所以测试里必须先热上 `loginStatusCA` 缓存再发请求。

## 6. 相关

- Windows 部署、起停脚本、已踩的坑：[`windows-deployment.md`](windows-deployment.md)
- 端口与目录约定：[`conventions.md`](conventions.md)
