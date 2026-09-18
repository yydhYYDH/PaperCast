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
XHS_STATUS_TTL_SECONDS     login/status 缓存时长，<=0 表示不缓存（默认 60）
```

效果：秒级轮询从「每次都开浏览器」变成「一分钟最多开一次」，且总次数被硬上限卡死。
**登录成功 / 删除 cookies 时会主动失效缓存**，所以扫码后不会等一个 TTL 才看到新状态。

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

## 5. 为什么最终应该走 Windows 有头

`apps/xiaohongshu-mcp/browser/browser.go` 里这三行决定了 Linux 侧的实际形态：

```go
headless_browser.WithHeadless(headless),   // 默认 true = 无头
headless_browser.WithFingerprint(""),      // 空 = 按运行 OS 自动：Linux→windows
headless_browser.WithStealthJS(false),     // stealth 是关掉的
```

合起来是「**无头 Chromium + 指纹伪装成 Windows + stealth 关闭**」——单独看都不致命，
叠在一起是相当典型的可检测特征。原生 Windows + 真实 Chrome + 有头能同时消掉这三条。

## 6. 相关

- Windows 部署：[`windows-deployment.md`](windows-deployment.md)
- 端口与目录约定：[`conventions.md`](conventions.md)
