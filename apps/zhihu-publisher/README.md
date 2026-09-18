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
| GET | `/api/v1/login/status` | `{is_logged_in, username, cookies_path, cookie_count}` |
| POST | `/api/v1/login/start` | 弹有头浏览器，等人工登录；返回后前端**轮询 status**。无 DISPLAY 时返回 409 `NO_DISPLAY` |
| DELETE | `/api/v1/login/cookies` | 清登录态 |
| POST | `/api/v1/export` | **无副作用**：把标题/正文/图片/话题落到 `var/artifacts/zhihu/export/<runId>/` |
| POST | `/api/v1/publish` | 真实发布；需 `confirmed=true`，可选 `confirm_account` 二次校验；`run_id` 会给回执 `zhihu_receipt.json` |

错误统一 `{"success": false, "error": {"code", "message"}}`，与 backend `PlatformError` 同形。

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
