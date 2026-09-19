# zhihu-publisher（知乎发布通道服务）

给 PaperCast 用的知乎投递通道，形状对齐 `apps/xiaohongshu-mcp`：**独立进程 + HTTP 接口**，
backend 只按 HTTP 调它，因此 backend venv 不需要 playwright。

- 端口：`127.0.0.1:18070`（后端读 `ZHIHU_PUBLISHER_BASE` 覆盖）
- 依赖：FastAPI/uvicorn（复用 `apps/papercast-server/.venv`）+ 只读上游 `reference/upstream/zhihu-mcp` 的 `ZhihuService`
- 登录态：`var/secrets/zhihu/cookies.json`（含 `z_c0`；凭证进 secrets，兼容读旧的 `var/artifacts/zhihu/cookies.json`）
- 发布是**不可逆动作**：`/api/v1/publish` 必须 `confirmed=true`

## 接口契约

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 存活 + cookies 路径 |
| GET | `/api/v1/login/status` | `{is_logged_in, username, account_token, cookies_path, cookie_count, checkedBy, detail}`。`checkedBy` 如实说明这次**怎么判的**：`api`=问过知乎本人接口、`browser`=起浏览器确认过、`cookies`=只看了 cookies 文件 |
| POST | `/api/v1/login/start` | 弹有头浏览器，等人工登录；返回后前端**轮询 status**。无 DISPLAY 时返回 409 `NO_DISPLAY` |
| DELETE | `/api/v1/login/cookies` | 清登录态 |
| POST | `/api/v1/export` | **无副作用**：把标题/正文/图片/话题落到 `var/artifacts/zhihu/export/<runId>/` |
| POST | `/api/v1/publish` | 真实发布；需 `confirmed=true`，可选 `confirm_account` 二次校验；`run_id` 会给回执 `zhihu_receipt.json`。**发布后会核验**（见下），核验不过则报 502 `PUBLISH_NOT_CONFIRMED` |
| GET | `/api/v1/verify?url=&title=` | **纯读**核验一个链接还在不在：账号文章列表里有没有它、文章页能不能打开；返回 `{verified, canonicalUrl, total, how, note}` |

错误统一 `{"success": false, "error": {"code", "message"}}`，与 backend `PlatformError` 同形。

## 快与慢：一次探测从 8 秒变 0.2 秒，以及两把锁

2026-09-19 实测（本机）之后做的三件事，都是为了「点发布别卡那么久」：

1. **探登录态不再起浏览器。** 老实现要起**两次**浏览器（先 `check_login_status()` 确认登录、再打一次
   `/api/v4/me` 取昵称），冷的一次 6~9 秒。现在带 cookies 直接打一次
   `https://www.zhihu.com/api/v4/me` 就拿到 `{name, url_token}` —— 这是向知乎本人接口核实，不是拿
   cookies 猜；实测 **8.0s → 0.22s**，后端 `/api/platforms?force=1` 从 **32s → 0.24s**。
   ⚠️ 这里只能用**标准库 urllib**：本服务的解释器是 `var/toolchains/zhihu-mcp-venv`，**没有 httpx**
   （2026-09-19 踩过：写完 httpx 版直接 500）。HTTP 问不上（网络/被挡）时才退一步起浏览器确认，
   并在 `checkedBy` 里如实标注。
2. **两把锁分工。** `_PUBLISH_LOCK` 只给真发布（一个账号同时只能有一篇在写，发布之间必须串行）；
   `_BROWSER_LOCK` 给其它要用浏览器的只读动作（运营数据、链接核验、登录态兜底探测）。原来所有动作
   共用一把锁，前端一探渠道状态就把发布排到后面 —— 实测三个探测接口并发时 /api/env 61.7s、
   /api/platforms 54.1s、drafts 45.8s；拆开后同一组并发 **1.0s / 0.002s / 1.1s**。
3. **8 张图一次传完。** 弹窗的 `input[type=file]` 支持 `multiple` 时，一次
   `set_input_files([...8 张])` 交给弹窗自己排队，轮询粒度 1s → 0.25s（还有 12s 无变化就认为卡住，
   不傻等超时）；不支持 `multiple` 时才回退到原来逐张传的老路。相同材料 dry_run 实测
   **61.1s → 24.0s**，8/8 张都进正文（正文块数 136 不变）。

## 发布后核验（`app/article_flow.py` 的 `verify_published`）

**点完「发布」不等于发出去了。** 2026-09-19 实测：回执里写过四次「知乎已发布」，只有两次是真的 ——
两次账号文章列表里根本没有那一篇（登录态打开链接是知乎 404「没有知识存在的荒原」），
另外两次文章确实在，但回执记的是 `…/edit` 编辑页地址。原因是老实现点完发布就 `success = True`，
URL 从编辑页地址栏取，取不到还会退而求其次拿「列表里第一条」顶上。

现在的判定（全部只读）：

1. 从链接里取文章 id，轮询账号文章列表（`/api/v4/members/<token>/articles`，4 次 / 每次隔 5s，
   刚发布可能还没进列表）—— id 命中或**标题命中**才算通过，并把列表里的**正式地址**写回 `url`；
2. 列表里没有，再打开文章页：不是知乎的「没有知识存在的荒原」且页面标题对得上 → 也算通过
   （附一条 warning 说明是「列表滞后」）；
3. 都不成立 → `success=false`，`/api/v1/publish` 报 502 `PUBLISH_NOT_CONFIRMED`，
   回执按**失败**落盘，错误里写清「账号文章列表（N 篇）里没有这一篇」或「连续几次都没读到列表」。

回放历史案例（**只读，不发布任何东西**）：

```bash
bash apps/zhihu-publisher/scripts/replay_verify_cases.sh      # 服务在跑即可
```

## 启动

```bash
WS="$(cd "$(dirname "$0")/../.." && pwd)"
"$WS/apps/papercast-server/.venv/bin/uvicorn" app.main:app \
  --host 127.0.0.1 --port 18070 --app-dir "$WS/apps/zhihu-publisher"
```

或由 `ops/start_all.sh` 一起起（见该脚本 `start_zhihu`）。

## 为什么不走官方 OpenAPI

官方 `openapi.zhihu.com/openapi/publish` 需要 `ZHIHU_OPENAPI_APP_SECRET`（内测申请，要等审核）。
本通道用登录态 + 浏览器自动化，**现在就能发**；等密钥到手后可再加一个 `openapi` transport 并存。
