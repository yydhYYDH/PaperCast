# 后端 HTTP 契约

后端**严格实现**前端 `papercast/src/api/http.ts` 已声明的契约（前端零改动即可从 mock 切到真实后端），
另外补了上传与产物静态服务两个必要接口。

## 1. 前端已声明的契约（必须一致）

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| `POST` | `/api/runs` | `{ source: SourceInput, config: RunConfig }` | `PaperRun` |
| `GET` | `/api/runs` | — | `PaperRun[]`（新→旧） |
| `GET` | `/api/runs/:id` | — | `PaperRun`（不存在 → 404） |
| `POST` | `/api/runs/:id/cancel` | — | `204` |
| `POST` | `/api/runs/:id/stages/:sid/gate` | `{ optionId, note? }` | `204` |
| `GET` | `/api/runs/:id/events` | — | `text/event-stream`（SSE） |

`PaperRun` 的形状与 `papercast/src/types.ts` **逐字段一致**：`id / createdAt / title / source / status /
stages[] / config / digest? / articles?`；
`Stage` 含 `id / label / engine / status / progress / startedAt / endedAt / logs[] / artifacts[] / gate? / checks?`。
后端不为「方便」改字段名 —— 前端 store 和 5 个 viewer 都直接读这些字段。

## 2. 后端补充的接口

### `POST /api/uploads` — 上传 PDF / LaTeX zip

```bash
curl -F file=@paper.pdf http://127.0.0.1:8000/api/uploads
# -> { "uploadId": "up_8f3a...", "filename": "paper.pdf", "bytes": 5251910, "sha256": "..." }
```

拿到 `uploadId` 后作为 `source.value` 建运行：

```bash
curl -X POST http://127.0.0.1:8000/api/runs -H 'Content-Type: application/json' -d '{
  "source": { "kind": "pdf", "value": "up_8f3a...", "title": "Paper2Video" },
  "config": { "article": { "variants": ["xhs-author", "zhihu-analyst"] }, "publish": { "targets": ["xiaohongshu"], "autoPublish": false } }
}'
```

`.zip` 走 `kind: "latex"`，`SourceInput.value` 同样填 `uploadId`。

### `GET /artifacts/<runId>/<path>` — 产物静态服务

`run.stages[].artifacts[].url` 指向这里，前端 `ArticleViewer` / `DigestViewer` 直接预览。

```
GET /artifacts/<runId>/intake/content.md
GET /artifacts/<runId>/intake/images/fig-1.png
GET /artifacts/<runId>/article/cards/p1.png
```

实现上做了两道限制：`resolve()` 之后必须仍在 run 目录内（`../../../etc/passwd` → 404），
且内部记账文件 `run.json` / `error.log` 不在暴露之列（→ 404）。产物本身（md / json / 图片）都可直接预览。

### `GET /api/env` — 引擎与环境状态

给前端的「引擎与环境」视图用：M1 解析引擎、LaTeX 引擎、LLM 通道、小红书 MCP 健康与登录账号、
Playwright/chrome-headless-shell 是否就绪。全部是**真实探测**结果，不写死。

### `/api/platforms` — 渠道账号与登录入口

前端「平台账号」页与发布页的登录入口都走这一组接口。**前端不直连 :18060**（少一处 CORS，也多一层闸门）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/platforms` | 全部渠道状态；`?force=1` 绕过 5s 探测缓存 |
| `GET` | `/api/platforms/:id` | 单个渠道（默认 force） |
| `GET` | `/api/platforms/:id/login/qrcode` | 取扫码登录二维码（Base64 data URL + 过期时间）：`xhs` 走 MCP、`bilibili` 走通道服务里 biliup 写下的 `qrcode.png` |
| `POST` | `/api/platforms/:id/login/start` | 起一次「非页内二维码」的登录流程：`zhihu` 弹桌面窗口等人登录、`bilibili` 起 `biliup login` |
| `POST` | `/api/platforms/:id/login/logout` | 退出登录（清本机 cookies，不可逆）→ `204`；`xhs` / `zhihu` / `bilibili` 都支持 |

`PlatformChannel` 形状（与前端 `src/types.ts` 一致）：

```jsonc
{
  "id": "xhs",                       // xhs / wechat / zhihu / bilibili
  "name": "小红书",
  "kind": "mcp",                     // mcp / openapi / cli
  "login": "qrcode",                 // qrcode / env / cli / none
  "state": "ready",                  // ready / login_required / offline / unconfigured / blocked
  "account": "momo",                 // 未登录为空串
  "detail": "已登录：momo",
  "endpoint": "http://127.0.0.1:18060",
  "needs": ["扫码登录", "6 张卡片图"],
  "capabilities": ["图文发布"],
  "loginHint": "点「扫码登录」，用小红书 App 扫码…"
}
```

三条实现约定：

1. **只报真实探测结果**：没装工具 / 没配凭证的渠道返回 `unconfigured` / `blocked` / `offline`，不假装可用；
2. **探测有 5s 缓存**：MCP 的 `/api/v1/login/status` 每次都要开一次无头浏览器（3–10s），缓存防止前端轮询把它打爆；
3. **二维码一次只建一个会话**：MCP 侧 `GET /api/v1/login/qrcode` 会新建一个 4 分钟的等待会话并在扫码成功后写 cookies，
   再取一次会关掉上一个。所以前端**只在用户点「扫码登录」时调一次**，之后用 `GET /api/platforms/xhs` 轮询（5s）判断是否扫上；
4. **B 站的码是「顺手起一次」**：biliup 的交互菜单没有非交互开关，所以 `GET /api/platforms/bilibili/login/qrcode`
   在没有可用二维码时**自己**去起一次 `biliup login`（并在菜单里替用户选「扫码登录」），等 `qrcode.png` 落盘再返回，
   最多等约 24s。重复调用是安全的（biliup 会覆盖旧码），这与 MCP 侧「重复取会顶掉会话」正好相反；
5. **登录态是真实探测**：`bilibili` 读通道服务的 `/api/v1/login/status`（底层打 B 站 nav 接口校验 cookies），
   通道服务不在、biliup 没装、cookies 失效分别报 `offline` / `unconfigured` / `login_required`。

```bash
curl -s http://127.0.0.1:8000/api/platforms | jq '.[] | {id, state, account}'
curl -s http://127.0.0.1:8000/api/platforms/xhs/login/qrcode | jq '{isLoggedIn, timeout}'
curl -s http://127.0.0.1:8000/api/platforms/bilibili/login/qrcode | jq '{img: (.img|length), expiresAt}'   # B 站：真二维码 PNG
curl -s -X POST http://127.0.0.1:8000/api/platforms/zhihu/login/start | jq '{started, pid, hint}'          # 知乎：弹桌面窗口
```

### `GET /api/health` — 存活探针

`{ "status": "ok", "version": "...", "uptimeSec": 123 }`，给 systemd / nginx 用。

## 3. 状态机

```text
RunStatus:    queued → running → waiting → running → done
                              ↘ failed
StageStatus:  pending → running → waiting ─gate─► running → done
                              ↘ failed        ↘ skipped
```

规则：

- `RunStatus = waiting` 当且仅当某个 stage 在等闸门；闸门是**阶段级**的，`stage.gate.resolved` 记录选择。
- `cancel` 把当前 stage 标 `failed`（`error: "cancelled"`），未开始的 stage 保持 `pending`，run 置 `failed`。
- 后端重启后从 `run.json` 恢复；`running` 的 run 会被标成 `failed`（进程已丢，不能假装还在跑），
  `waiting` 的 run 原样恢复 —— 闸门状态是持久化的。

## 4. SSE 事件

`GET /api/runs/:id/events`，每行 `data: <json>\n\n`：

```jsonc
{ "type": "snapshot", "run": { /* 完整 PaperRun */ } }
{ "type": "stage", "stageId": "intake", "status": "running", "progress": 0.4 }
{ "type": "log", "stageId": "intake", "line": { "ts": 1789743, "level": "ok", "text": "..." } }
{ "type": "artifact", "stageId": "intake", "artifact": { /* Artifact */ } }
{ "type": "gate", "stageId": "understand", "gate": { /* StageGate */ } }
{ "type": "done", "status": "done" }
```

心跳：每 15s 发一行注释 `: ping`，防止 nginx / 浏览器断流。
前端未接 SSE 时退化为轮询 `GET /api/runs/:id`（`src/api/http.ts` 当前就是这条路径），两条路都必须正确。

## 5. 错误格式

统一 `{ "error": { "code": "SNAKE_CODE", "message": "人类可读", "details": {...} } }`，
HTTP 状态码：400 参数错 / 404 不存在 / 409 状态冲突（对已放行的闸门重复放行）/
422 输入无法解析（如扫描件无 OCR）/ 502 上游失败（arXiv、LLM、MCP）。

## 6. CORS

默认只允许 `http://127.0.0.1:5178` 与 `http://localhost:5178`（本机前端 dev server），
由 `PAPERCAST_ALLOW_ORIGINS` 覆盖；生产环境走 nginx 同源反代时不需要 CORS。

## 7. 渠道投递层（`app/channels/`，2026-09-19 新增）

上面 §2 的 `/api/platforms` 是**账号视角**（谁登录了、怎么登录）；
本节是**投递视角**（这份物料能不能投、缺什么），M3 发布阶段用这一层。

### `GET /api/channels` — 三个渠道及其实时就绪状态

```json
[
  {
    "id": "xiaohongshu", "name": "小红书", "aliases": ["xhs"],
    "capabilities": ["images", "text", "video"],
    "login": "qrcode", "transport": "mcp-http", "endpoint": "http://127.0.0.1:18060",
    "why": "图文/视频笔记：MCP 开无头浏览器操作网页版，扫码登录",
    "restart": "./ops/start_all.sh mcp",
    "state": "login_required", "account": "", "reachable": true,
    "detail": "MCP 在线，但当前未登录（或登录已失效）",
    "hint": "在「平台账号」页点扫码登录；注意 MCP 的 cookie 认启动目录（apps/xiaohongshu-mcp/）",
    "enabled": true
  }
]
```

- `state ∈ ready | login_required | offline | unconfigured | blocked`；**非 ready 一定带 `hint`**。
- 结果缓存 15s（探测会触达通道服务，知乎那次会开浏览器），`?force=true` 强制刷新。
- `GET /api/channels/{id}` 取单个；未知 id → 404 `CHANNEL_NOT_FOUND`。
- `capabilities` 如实声明：知乎没接视频通道，就不含 `video`。

### 发布阶段的渠道语义

- `RunConfig.publish.targets`（默认 `["xiaohongshu","zhihu","bilibili"]`）决定 M3 投哪些渠道，
  别名 `xhs` 也认；**未知/停用的渠道不静默丢弃**，会写成 `stage.checks` 里的 `渠道：<id> = fail`。
- 渠道级进展都在 `stage.checks`：`素材适配：<渠道>`、`渠道状态：<渠道>`、`可投递渠道`、`发布结果`。
- 产物：`publish/<渠道>/export/`（素材包，闸门之前就落盘）、`publish/<渠道>/receipt.json`、
  `publish/receipts.json`（总表，含 `published/failed/blocked`）、`publish/xhs_receipt.json`（兼容别名）。
- 闸门 `publish-gate` 选项：`continue`（只向就绪渠道投递）/ `draft`（只准备）/ `skip`（本轮不发）。

完整规格（新增平台四步、B 站选型、失败隔离的验收方式）见 `08-channels.md`。

## 8. 运营维护层（`app/ops.py`，2026-09-19 新增）

给「跑起来之后」用的四个端点。与渠道层的分工：渠道层回答「账号能不能投」，这一层回答
「机器还健康吗、投出去的内容效果如何」。

### `GET /api/ops/services` — 五个本机服务的真实状态

```json
[{ "name": "backend", "label": "后端 API", "port": 8000, "up": true, "pid": 30330,
   "url": "http://127.0.0.1:8000",
   "health": { "probed": true, "ok": true, "status": 200, "elapsedMs": 9, "detail": "HTTP 200" },
   "log": { "path": "…/var/logs/backend.log", "exists": true, "size": 3072, "updatedAt": 1789750938434 },
   "restartHint": "./ops/start_all.sh backend" }]
```

- 白名单固定 `backend | frontend | mcp | zhihu | bilibili`；未知名字 → 404 `SERVICE_NOT_FOUND`；
- `up` 用 TCP 连接 127.0.0.1:port 判断（不解析 `ss`/`netstat`，也不需要额外权限）；
- 前端（5178）没有 HTTP 健康接口，`health.probed=false` 并说明原因，不假装正常。

### `POST /api/ops/services/{name}/{action}` — 启停

`action ∈ {start, stop, restart}`；`restart` 先 `stop_all.sh <name>` 再 `start_all.sh <name>`。
一律通过 `ops/` 脚本执行（不自己拼命令行），90s 超时 → 504 `OPS_TIMEOUT`。

### `GET /api/ops/logs?name=backend&lines=200&grep=` — 日志尾巴

读 `var/logs/<name>.log`，返回 `{lines[], matched, size, truncated, path}`；`lines` 上限 2000。只读。

### `GET /api/ops/metrics?force=false` — 运营数据

```json
{ "fetchedAt": 1789751003955,
  "channels": [ { "id": "bilibili", "name": "B 站", "kind": "video",
      "source": "公开 view 接口（api.bilibili.com/x/web-interface/view）",
      "items": [ { "id": "BV1DveU6GEPR", "url": "…", "title": "…", "author": "YYDH54",
                   "publishedAt": 1789748791000,
                   "stats": { "view": 1, "like": 0, "coin": 0, "favorite": 0, "reply": 0, "danmaku": 0, "share": 0 },
                   "source": "var/runs/run_a7b9460d3953/video/upload_result.json" } ],
      "errors": [], "totals": { "view": 1, "…": 0 }, "gap": "" } ] }
```

约定（都在 `app/ops.py` 顶部注释里）：

- **内容从本机回执里发现**：扫 `var/runs` 与 `var/artifacts` 下 JSON 里的 BV 号与 `zhuanlan.zhihu.com/p/…`，
  只认真的投递过的条目；
- **每个渠道带 `source`**（数据来源）与 `gap`（拿不到什么、为什么），界面直接展示；
- **取不到不编**：知乎通道抓不到正文标题时返回 502 `STATS_EMPTY`，本层把它放进 `errors`，
  小红书未登录时提示「先去平台账号扫码」；两者都**不会**退化成 `0`；
- 60s 缓存（`force=true` 绕过）：小红书那次探测会真开一次浏览器，不缓存会拖死页面。

各平台能拿到什么（2026-09-19 实测：B 站全量互动数据 ✅、知乎赞同/评论需登录态 ⚠、两家浏览量均不公开 ❌）
见 `../../../docs/10-ops-and-theme.md`。
