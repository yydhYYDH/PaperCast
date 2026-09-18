# 服务器部署

本文覆盖「从零到 www 可访问」的全部步骤。目标机器 = 当前这台服务器（20 核 / 1TB 盘 / **无可用 GPU**）。

## 1. 依赖

### 系统层

| 依赖 | 用途 | 本机状态 |
| --- | --- | --- |
| Python ≥ 3.10 | 后端运行时 | ✅ 3.13.12 |
| `uv` | 建 venv、装依赖 | ✅ 0.12.6 |
| Noto Sans CJK 字体 | 卡片图中文渲染 | 需检查（见 §6 排障） |
| chrome-headless-shell | HTML → PNG 卡片 | 复用 Playwright 缓存 |
| **可选** TeX Live | LaTeX 输入编译成 PDF | ❌ 未装，走源码解析通道 |
| **可选** tesseract-ocr | 扫描件 OCR | ❌ 未装，扫描件会明确报错 |

> **不要**用系统 `pip` 装依赖：本机 `pip` 指向 conda base 环境，会污染其他项目。一律用项目内 `.venv`。

### Python 层

```bash
cd /home/yydh/hack/apps/papercast-server
export UV_CACHE_DIR=/home/yydh/hack/var/cache/uv     # uv 默认缓存在 ~/.cache，本机沙箱下可能只读
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

## 2. 配置

复制 `.env.example` 为 `.env` 后按需修改，**全部有默认值，不配也能跑**：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `PAPERCAST_HOST` | `127.0.0.1` | 监听地址；生产用 nginx 反代时保持 127.0.0.1 |
| `PAPERCAST_PORT` | `8000` | 端口 |
| `PAPERCAST_DATA_DIR` | `<工作区>/var/runs` | 运行产物根目录（`ops/start_all.sh` 会注入；单跑组件时退回组件内 `./data/runs`） |
| `PAPERCAST_UPLOAD_DIR` | `<工作区>/var/uploads` | 上传的原始论文 |
| `PAPERCAST_ALLOW_ORIGINS` | `http://127.0.0.1:5178,http://localhost:5178` | CORS 白名单 |
| `PAPERCAST_INTAKE_ENGINE` | `pymupdf` | `pymupdf` \| `mineru`（上 GPU 后切换） |
| `LLM_BASE_URL` | `https://opencode.ai/zen/go/v1` | OpenAI 兼容端点 |
| `LLM_API_KEY` | 空 → 自动读 `~/.dsh/.credentials.yaml` 的 `GO_API_KEY` | |
| `LLM_MODEL` | `deepseek-v4.1-flash` | reasoning 模型，客户端已给足 token 并处理 `x-opencode-session` 头 |
| `XHS_MCP_BASE` | `http://127.0.0.1:18060` | xiaohongshu-mcp 地址 |
| `PAPERCAST_CARDS` | `on` | 是否渲染小红书卡片图（`off` 时只出文案） |

密钥不落库：`.env` 权限设 `600`，且不进 git（工作区根 `.gitignore` 已排除 `var/`、`.env`、`.venv/`、`cookies.json`）。

## 3. 启动

### 开发

```bash
./scripts/run_dev.sh                 # uvicorn --reload，http://127.0.0.1:8000
```

### 生产（systemd）

```ini
# /etc/systemd/system/papercast-api.service
[Unit]
Description=PaperCast API (paper intake / generate / publish)
After=network.target

[Service]
Type=simple
User=yydh
WorkingDirectory=/home/yydh/hack/apps/papercast-server
EnvironmentFile=/home/yydh/hack/apps/papercast-server/.env
Environment=PAPERCAST_DATA_DIR=/home/yydh/hack/var/runs
Environment=PAPERCAST_UPLOAD_DIR=/home/yydh/hack/var/uploads
ExecStart=/home/yydh/hack/apps/papercast-server/.venv/bin/uvicorn app.main:app \
          --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=3
StandardOutput=append:/home/yydh/hack/var/logs/api.log
StandardError=append:/home/yydh/hack/var/logs/api.err.log

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now papercast-api
systemctl status papercast-api --no-pager
```

**`--workers 1` 是刻意的**：运行状态与闸门在进程内存 + 索引文件里，多 worker 会让 `GET /api/runs/:id`
落到没有该 run 的进程上。要横向扩展时，得先把 `RunStore` 换成 Redis/SQLite —— 见 §7。

### 依赖的兄弟服务

```bash
# 小红书发布能力（M3 需要；不装则 M3 退化为 export-only，不影响 M1/M2）
# 二进制不入库：先 ./ops/install.sh --with-mcp 编出来（clone 源码 + Go 编译），详见 docs/INSTALL.md §5.2/§5.3
# 日常起停用 ./ops/start_all.sh mcp（它会在组件目录里起，cookie 是 cwd 相对路径）
cd <仓库根> && ./ops/bin/xiaohongshu-mcp -port :18060
curl -s http://127.0.0.1:18060/health
```

## 4. 反向代理（nginx）

```nginx
server {
    listen 80;
    server_name papercast.example.com;

    # API + SSE
    location /api/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_buffering    off;      # SSE 必须关，否则事件被攒着不发
        proxy_cache        off;
        proxy_read_timeout 3600s;    # 长运行 + 长连接
        client_max_body_size 200m;   # 上传大 PDF
    }

    # 产物静态（图片 / markdown / 卡片）
    location /artifacts/ {
        proxy_pass http://127.0.0.1:8000;
    }

    # 前端构建产物
    location / {
        root  /home/yydh/hack/apps/papercast/dist;
        try_files $uri $uri/ /index.html;
    }
}
```

前端构建（把 API 地址烧进产物）：

```bash
cd /home/yydh/hack/apps/papercast
VITE_API_BASE=https://papercast.example.com npm run build   # 产物在 dist/
```

## 5. 前端本地联调

```bash
# 终端 1
cd apps/papercast-server && ./scripts/run_dev.sh
# 终端 2（本机已有 5178 在跑，直接刷新页面即可）
cd apps/papercast && VITE_API_BASE=http://127.0.0.1:8000 npm run dev
# 或者一步到位（推荐）：工作区根执行 ./ops/start_all.sh
```

切到真实后端后，前端顶栏会显示 `HTTP · http://127.0.0.1:8000`（mock 时会显示 `Mock`），
这是判断有没有接上的最快方式。

## 6. 排障

| 症状 | 原因 / 处理 |
| --- | --- |
| `Could not create temporary file ... Read-only file system`（uv） | `export UV_CACHE_DIR=/home/yydh/hack/var/cache/uv` |
| 卡片图中文变方块 | 缺 CJK 字体：`fc-list \| grep -i cjk`；没有则装 `fonts-noto-cjk`，或把字体文件路径写进 `PAPERCAST_CJK_FONT` |
| 卡片图渲染失败 | `chrome-headless-shell` 路径探测失败：设 `PAPERCAST_CHROME` 指向可执行文件；失败不阻塞流水线 |
| M1 报「需要 OCR」 | 纯扫描件；本机无 tesseract，属预期行为 |
| M2 报 LLM 失败 | `401/403` 检查 `LLM_API_KEY`；`402` 是余额；reasoning 模型返回空 content 多为 `max_tokens` 太小 |
| M3 报 `NOT_LOGGED_IN` | 后端会返回二维码 base64，扫码后重试；或手动跑 `xiaohongshu-mcp` 的 login 流程 |
| SSE 收不到事件 | nginx `proxy_buffering off`；或前端用了轮询路径（也正常） |

## 7. 已知的扩展点

- **多 worker / 多机**：把 `RunStore`（当前：内存 dict + `run.json`）换成 SQLite 或 Redis，
  并把 M1/M2 的重活丢到任务队列（Celery/RQ/arq）。当前单机单进程足够跑论文这一量级。
- **MinerU 通道**：换到有 GPU 的机器后设 `PAPERCAST_INTAKE_ENGINE=mineru`，
  按 `docs/01-module-intake.md` 的同名接口实现，业务代码不动。
- **poster / video**：前端契约里已占位，接 Paper2Poster / Paper2Video 时新增两个模块即可。
