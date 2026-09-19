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

## 测试

```bash
cd apps/papercast-server
export UV_CACHE_DIR="$(cd ../.. && pwd)/var/cache/uv"
uv pip install --python .venv/bin/python -r requirements-dev.txt   # 只有 pytest
.venv/bin/python -m pytest -q                                     # 秒级，全绿才算过
```

覆盖的是**不需要外部依赖**的那一层：`app/styles.py` 的平台 × 人格身份层（variant 解析、MAX_VARIANTS、
长度口径「中文按 CJK 字数 / 英文平台按词数」、标签小节中英都认），`generate.brief_checks`（含
「指令上限与平台 body_min 冲突时报 run 而不是 fail」），`poster_stage` 的 spec 收敛（引用不存在的图要丢、
数字回溯不了的条目要丢、清空的块要移除）与减块优先级，`community` 的人读版拼装与数据复盘口径，
`video` 的念稿清洗 / 数字回溯 / 工具链路径推导，`store.resolve_artifact` 的目录穿越防护，
以及 `models` 的阶段清单（6 段全实现、SKIPPED 为空）与平台枚举契约。

原则：**不联网、不起服务、不调真 LLM**（LLM 一律 `unittest.mock.AsyncMock`）、不写真实 `var/runs`
（全部走 pytest 的 tmp_path），所以 CI 里不需要 chrome / ffmpeg。CI 见 `.github/workflows/ci.yml`
的 backend job（`python -m pytest apps/papercast-server/tests`）。

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
| [`docs/07-poster-and-cards.md`](docs/07-poster-and-cards.md) | poster 阶段（HTML→PNG 海报）与卡片产物渲染 |
| [`docs/08-channels.md`](docs/08-channels.md) | 发布渠道控制面：渠道声明、登录态、素材适配 |
| [`docs/09-voice-styles.md`](docs/09-voice-styles.md) | 平台 × 人格的文案身份层（variant 解析与校验） |
| [`docs/10-module-video.md`](docs/10-module-video.md) | video 阶段：分镜 → edge-tts 配音 → ffmpeg 合成真 mp4 |
| [`docs/11-verification-6-stages.md`](docs/11-verification-6-stages.md) | 六阶段端到端真实验证记录（已知失败项 / 未修 bug 清单 / 未验证清单） |

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
  modules/poster.py       海报渲染（HTML→PNG 版式与几何自检）
  modules/poster_stage.py poster 阶段编排（digest → LLM 写 spec → 多画布；装不下自动减块重试）
  modules/video.py        video 阶段：分镜 → edge-tts 配音 → ffmpeg 合成横/竖版 mp4 + 封面 + 字幕
  modules/community.py    社区运营：选社区 + 每社区一版成稿文案 + 投递数据复盘（挂在 publish 尾部）
  styles.py               平台 × 人格身份层（xhs / zhihu / bilibili / en）
  ops.py                  运营：服务起停、日志、已发内容的真实数据（只读渠道接口）
  platforms.py            渠道控制面：4 个渠道声明，R1 仅小红书可用（登录态 / 扫码 / 发布）
  cards/render.py         小红书卡片图（PIL，1080×1440）
scripts/make_cards.py     卡片与海报的命令行入口
<工作区>/var/runs/<runId>/         运行产物（不进 git）
docs/                      设计文档
scripts/                   开发与冒烟脚本
```