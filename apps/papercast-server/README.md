# papercast-server

PaperCast 的**真实后端**：论文进（PDF / LaTeX / arXiv），小红书图文出。
前端在 `../papercast`，契约 1:1 对齐，接上后前端无需改代码。

```
M1 论文处理   PDF / LaTeX / arXiv  ──►  content.md + images/ + meta.json + sections.json
M2 内容生成   M1 产物              ──►  digest.json（事实源）+ reading_note.md + xhs.md + cards/*.png
M3 发布       M2 产物              ──►  xiaohongshu-mcp 发布回执（人工闸门后）
```

## 快速开始

```bash
export UV_CACHE_DIR=/home/yydh/hack/var/cache/uv
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
./scripts/run_dev.sh                      # http://127.0.0.1:8000
```

```bash
# 丢一个 PDF 进去，跑完整条链路
./scripts/smoke_test.sh /path/to/paper.pdf
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [`docs/00-overview.md`](docs/00-overview.md) | 三模块划分、数据流、目录约定、技术选型理由 |
| [`docs/01-module-intake.md`](docs/01-module-intake.md) | M1：PDF / LaTeX / arXiv 三种输入 → md + 图片 |
| [`docs/02-module-generate.md`](docs/02-module-generate.md) | M2：digest 事实源、中文精读、小红书文案与卡片 |
| [`docs/03-module-publish.md`](docs/03-module-publish.md) | M3：小红书发布、人工闸门、失败回执、合规 |
| [`docs/04-api-contract.md`](docs/04-api-contract.md) | HTTP / SSE 契约与前端字段对照 |
| [`docs/05-deployment.md`](docs/05-deployment.md) | 服务器部署：systemd / nginx / 排障 |
| [`docs/06-verification.md`](docs/06-verification.md) | 真实论文端到端跑通记录 |

## 目录

```
app/
  main.py            FastAPI 路由（契约实现）+ 产物静态服务
  config.py          env 配置 + ~/.dsh 密钥兜底
  models.py          PaperRun / Stage / Artifact ...（1:1 前端 types.ts）
  store.py           RunStore：内存 + run.json 落盘，可恢复
  pipeline.py        编排、闸门、日志、取消
  llm.py             OpenAI 兼容客户端
  modules/intake.py  M1
  modules/generate.py M2
  modules/publish.py M3
  intake/pdf_parser.py     PyMuPDF：正文/标题/图/表 → md + images
  intake/latex_parser.py   LaTeX 源 → md + images
  intake/arxiv.py          arXiv 元数据 + PDF + 源码包
  cards/render.py         小红书卡片图（PIL，1080×1440）
<工作区>/var/runs/<runId>/         运行产物（不进 git）
docs/                      设计文档
scripts/                   开发与冒烟脚本
```
