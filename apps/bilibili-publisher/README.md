# bilibili-publisher（B 站投递通道服务）

给 PaperCast 用的 B 站投稿通道，形状对齐 `apps/xiaohongshu-mcp` 与 `apps/zhihu-publisher`：
**独立进程 + HTTP 接口**，backend 只按 HTTP 调它，因此 backend venv 不需要 biliup/浏览器依赖。

- 端口：`127.0.0.1:18080`（后端读 `BILIBILI_PUBLISHER_BASE` 覆盖）
- 底层：**biliup** CLI 子进程（选型理由与来源见 `apps/papercast-server/docs/08-channels.md` §4）
- 凭证：`var/secrets/bilibili/cookies.json`（`chmod 600`；兼容读 `var/artifacts/bilibili/cookies.json`）
- 发布是**不可逆动作**：`/api/v1/publish` 必须 `confirmed=true`
- 无论投没投，先落一份素材包到 `var/artifacts/bilibili/export/<runId>/`（大视频用硬链接，不复制几百 MB）

## 扫码登录怎么走通的

biliup 1.2.4 的 `login` 是**交互菜单**（账号密码 / 短信登录 / 扫码登录 / 浏览器登录 / 网页Cookie登录），
没有「直接扫码」的命令行开关，默认光标停在「短信登录」。所以通道服务在 pty 里替用户发一次
「↓ + 回车」把光标移到「扫码登录」，biliup 随后会 ① 把码画在终端（`var/logs/bilibili-login.log`）、
② 往 cwd 写一份 `qrcode.png`（`BILIBILI_LOGIN_DIR`，约 10s 内出现）。dashboard 用
`GET /api/v1/login/qrcode` 把那**同一张图**取回去直接展示，用户扫完 biliup 自己把 cookies 写盘。

## 接口契约

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 存活 + biliup 路径 + cookies 路径 + 默认分区 |
| GET | `/api/v1/login/status` | `{is_logged_in, username, cookie_file, cookie_count, has_sessdata, biliup_available, detail}`；用 B 站 nav 接口真实校验 |
| POST | `/api/v1/login/start` | 用 pty 跑 `biliup login`；默认 `{"method":"qrcode"}` 会自动在交互菜单里选「扫码登录」，输出落 `var/logs/bilibili-login.log` |
| GET | `/api/v1/login/qrcode` | 取 biliup 刚写的 `qrcode.png`（Base64 data URL）；超过 `max_age_sec`（默认 240s）视为过期 |
| POST | `/api/v1/login/renew` | `biliup renew` 续期（cookies 未过期时可用） |
| POST | `/api/v1/login/cookies` | 导入现成 cookies（`{cookies: {...}}` 或 `{cookies_path: "..."}`），免终端交互 |
| DELETE | `/api/v1/login/cookies` | 删掉本机 cookies |
| POST | `/api/v1/export` | **无副作用**：落素材包（title/desc/tags/视频/封面 + 投稿指引） |
| POST | `/api/v1/publish` | 真实投稿；需 `confirmed=true`；返回 `{bvid, url, command, stdoutTail}` |

错误统一 `{"success": false, "error": {"code", "message"}}`，与 backend `PlatformError` 同形。
常见 code：`BILIUP_MISSING`(501)、`NOT_LOGGED_IN`(401)、`VIDEO_MISSING`(400)、
`NOT_CONFIRMED`(409)、`UPLOAD_TIMEOUT`(504)、`PUBLISH_FAILED`(502)。

## 启用步骤（唯一的人工步骤是扫码）

```bash
WS="$(cd "$(dirname "$0")/../.." && pwd)"

# 1) 装 biliup（PyPI 有 manylinux wheel，不需要编译器）
"$WS/apps/papercast-server/.venv/bin/python" -m pip install "biliup==1.2.4"
#    或把预编译二进制放到 PATH/var/toolchains，并用 BILIBILI_BILIUP 指定路径

# 2) 起通道服务
"$WS/ops/start_all.sh" bilibili

# 3) 登录（三选一）
curl -s -X POST -H 'content-type: application/json' -d '{"method":"qrcode"}' \
  http://127.0.0.1:18080/api/v1/login/start                   # 自动选「扫码登录」
curl -s http://127.0.0.1:18080/api/v1/login/qrcode | jq -r .data.img > /tmp/qr.b64   # 取二维码图（dashboard 用的就是这条）
curl -s -X POST http://127.0.0.1:18080/api/v1/login/cookies \
  -H 'content-type: application/json' -d '{"cookies_path": "~/Downloads/cookies.json"}'

# 4) 确认状态：is_logged_in=true 才算可用
curl -s http://127.0.0.1:18080/api/v1/login/status
```

cookies 有效期约 1~3 个月，失效后 `POST /api/v1/login/renew` 或重新登录。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BILIBILI_COOKIES` | `var/secrets/bilibili/cookies.json` | cookies 文件路径（写入位置；读取时还会认 `var/artifacts/bilibili/` 与 `var/home/.bilibili/` 两处历史位置） |
| `BILIBILI_BILIUP` | `which biliup` → `var/toolchains/bili-venv/bin/biliup` | biliup 可执行文件（工作区把 biliup 装在自己的 venv 里，不在 PATH 中） |
| `BILIBILI_LOGIN_DIR` | `var/artifacts/bilibili/login` | biliup login 的 cwd：`qrcode.png` 就写在这里 |
| `BILIBILI_HOME` | `var/home` | 跑 biliup 时的 `HOME`，免得它把凭据写进别人的家目录 |
| `BILIBILI_TID` | `231` | 分区 id（以投稿页当前口径为准） |
| `BILIBILI_UPLOAD_EXTRA` | 空 | 追加投稿参数，如 `--submit web` |
| `BILIBILI_RETRY_ARGS` | `--line cnbd --limit 1` | 被 413 拒绝时的一次补救重试参数 |
| `BILIBILI_UPLOAD_TIMEOUT` | `2400` | 上传超时秒数（视频按分钟计） |
| `PAPERCAST_WS` | 从文件位置推导 | 工作区根 |

## 试投

```bash
# 只落素材包，不投稿
curl -s -X POST http://127.0.0.1:18080/api/v1/export -H 'content-type: application/json' \
  -d '{"title":"测试标题","desc":"简介","tags":["论文"],"video":"/abs/x.mp4","cover":"/abs/cover.png","run_id":"run_demo"}'

# 真实投稿（不可逆；没 confirmed 会被 409 拒绝）
curl -s -X POST http://127.0.0.1:18080/api/v1/publish -H 'content-type: application/json' \
  -d '{"title":"测试标题","desc":"简介","tags":["论文"],"video":"/abs/x.mp4","confirmed":true,"run_id":"run_demo"}'
```
