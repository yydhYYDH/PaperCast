# M3 · 发布（publish）

**目标**：把 M2 的小红书图文投递到小红书 —— 但**只在人工闸门放行之后**。默认行为是「准备」，不是「发出去」。

## 1. 发布通道

小红书走本机已运行的 **xiaohongshu-mcp**（Go 实现，`xpzouying/xiaohongshu-mcp`）：

```bash
# 服务健康检查（本机实测通过）
curl -s http://127.0.0.1:18060/health
# {"success":true,"data":{"service":"xiaohongshu-mcp","status":"healthy",...}}
```

后端不直连浏览器，只调它的 HTTP API：

| 用途 | 调用 |
| --- | --- |
| 登录状态前置检查 | `GET /api/v1/login/status` |
| 生成登录二维码 | `GET /api/v1/login/qrcode`（回传 base64 PNG 给前端展示） |
| 发布图文 | `POST /api/v1/publish`（标题 + 正文 + 图片数组 + 可选话题标签） |

图片以**本地路径**传入（卡片图就在 `<工作区>/var/runs/<id>/article/cards/`，同机无需上传到别处）。

## 2. 发布前准备（闸门之前做的事）

`publish` 阶段在等待闸门时会先行完成所有「可逆」步骤，并落盘 `publish/export/`：

```text
publish/
├── ready.json          待发布清单：标题 / 正文 / 图片顺序 / 标签
├── export/
│   ├── title.txt       小红书标题（已按 ≤38 计重校验）
│   ├── content.txt     正文 + 标签（UTF-8，直接可复制）
│   └── p1.png ...      按顺序的卡片图
└── xhs_receipt.json    放行后才写入的真实回执
```

`export/` 的存在意义：即使 MCP 掉线/未登录，用户也能拿这个目录 30 秒手动发出去，
**发布链路的可用性不依赖任何外部服务**。

## 3. 闸门

**流水线里的 `publish` 阶段不再提供「确认发布」**（2026-09-23 用户要求）：只有两个选项，
真实投递一律走作品库直投（`POST /api/runs/{id}/publish[/video]`，带 `confirmed` + 账号二次校验）。

```jsonc
{ "id": "publish-gate", "label": "发布前人工闸门",
  "detail": "这一轮只落草稿，不向任何平台投递。",
  "options": [
    { "id": "draft", "label": "仅存草稿" },
    { "id": "skip",  "label": "本轮不发布" }
  ] }
```

| 选项 | 行为 |
| --- | --- |
| `draft` | 不调发布接口，只把 `export/` 备好，回执 `status: "draft"`（默认） |
| `skip` | 什么都不做，回执 `status: "skipped"`，阶段标 `skipped` |

`_is_confirmed()` 仍是白名单（只有 `"continue"` 算真投递），但流水线已不再产生这个选择 ——
即使闸门被误放行，也不会真的发出请求。

自动化的调用方也要守同一条线：`scripts/smoke_test.sh` 对发布闸门的默认动作是 **`draft`**。
这条安全默认是踩过坑之后补上的 —— 第一版冒烟脚本对所有闸门一律回 `continue`，
结果验证运行把一篇测试帖真的发到了账号上。

## 4. 失败与回执

回执 `xhs_receipt.json`：

```jsonc
{
  "channel": "xiaohongshu",
  "status": "published | draft | skipped | failed",
  "optionId": "continue",
  "title": "...", "imageCount": 6,
  "noteId": "...", "permlink": "...",
  "raw": { "/* MCP 原始响应，便于排查 */": "..." },
  "error": { "code": "NOT_LOGGED_IN", "message": "..." },
  "at": 1789743355
}
```

已处理的错误码：

| code | 触发 | 处理 |
| --- | --- | --- |
| `MCP_UNREACHABLE` | `/health` 不通 | 阶段 `failed`，回执里给出启动命令，同时保留 `export/` |
| `NOT_LOGGED_IN` | 登录状态非 `logged_in` | 阶段 `waiting`，返回二维码 base64，前端展示扫码；`export/` 可用 |
| `TITLE_TOO_LONG` | 标题计重 > 38 | 发布前本地拦截（不消耗一次失败请求） |
| `IMAGE_EMPTY` | 卡片图缺失 | 回退到 M1 抽出的原始论文图 |
| `PUBLISH_FAILED` | MCP 返回业务失败 | 原样透出 message，回执 `failed`，可重放（幂等靠闸门控制） |

## 5. 合规与风控

- 发布是**人工闸门后**的一次性动作，后端不做批量/定时群发，不实现去重扫号逻辑。
- 浏览器由 MCP 自己用 go-rod 驱动，后端不注入 JS、不碰 cookie；cookie 由 MCP 管（`xiaohongshu-mcp/cookies.json`）。
- 默认不开「互动」（评论/点赞/收藏接口）。这些接口在后端**显式不暴露**，避免被当成自动化运营工具滥用。
- 若 MCP 报风控/验证码，后端不重试、不绕过，直接把原文返回给人工处理。
