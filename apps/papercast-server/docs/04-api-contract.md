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
  "config": { "article": { "variants": ["xhs"] }, "publish": { "targets": ["xiaohongshu"], "autoPublish": false } }
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
