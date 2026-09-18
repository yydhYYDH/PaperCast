# PaperCast 后端 · 总览

PaperCast 前端（`../papercast`，Vue 3 + Vite）已经定义了完整的运行模型与 HTTP 契约，但只带 **mock 适配器**。
本目录是它的 **真实后端**：把一份论文从「文件/链接」一路推到「可发布的小红书图文」。

后端由**三个模块**组成，正好覆盖前端 `STAGE_ORDER` 的前三段：

| 模块 | 名称 | 覆盖前端阶段 | 输入 | 输出 |
| --- | --- | --- | --- | --- |
| **M1** | 论文处理（intake） | `intake` | PDF / LaTeX 源 / arXiv 链接 | `content.md` + `images/*.png` + `meta.json` + `sections.json` |
| **M2** | 内容生成（generate） | `understand` + `article` | M1 产物 | `digest.json`（唯一事实源）+ 中文精读笔记 + 小红书图文（`xhs.md` + `cards/*.png`） |
| **M3** | 发布（publish） | `publish` | M2 产物 | 小红书发布回执 `xhs_receipt.json`（**闸门放行后**才真实投递） |

`poster` / `video` 两个阶段当前返回 `skipped`（前端契约里保留，后续接 Paper2Poster / Paper2Video 时再实现），
这样前端不需要改动就能把三段真实流水线跑起来。

## 数据流

```text
                       ┌──────────────── M1 论文处理 ────────────────┐
  PDF 上传 ─┐          │                                            │
  LaTeX 源 ─┼─► 归一化 ─┤  pdf_parser (PyMuPDF)                      │
  arXiv 链接┘          │  latex_parser (源码 → md)                  │
                       │  arxiv (下载 PDF + 源码包)                  │
                       └──────────────► paper/{content.md,images/} ─┘
                                              │
                       ┌──────────────── M2 内容生成 ────────────────┐
                       │  digest.json   唯一事实源（贡献/方法/证据/图表）│
                       │  reading_note.md 中文精读笔记                │
                       │  xhs.md 小红书文案（无公式、≤1000 字、标签）   │
                       │  cards/p1..pN.png 3:4 卡片图（HTML→PNG）     │
                       └──────────────► article/ ───────────────────┘
                                              │   ⏸ 人工闸门①确认理解层
                       ┌──────────────── M3 发布 ────────────────────┐
                       │  xiaohongshu-mcp (127.0.0.1:18060) 图文发布  │
                       └──────────────► publish/xhs_receipt.json ───┘
                                              ⏸ 人工闸门②发布前确认
```

## 设计原则（沿用前端已定的三条）

1. **单一理解层**：`digest.json` 是所有下游文案的唯一事实源，避免小红书文案和阅读笔记互相矛盾。
2. **数字可追溯**：小红书文案里出现的每个数字都必须能在 `digest.json` 的证据条目里找到；
   生成后有一道**校验**（`checks`）做数字回溯，找不到就标 `fail`。
3. **人工闸门**：理解层确认、发布前确认两处停下来等人放行，不是一把梭全自动。

## 运行目录约定

每次运行在前端约定的虚拟路径 `.papercast/runs/<runId>/` 下落地，真实根目录由 `PAPERCAST_DATA_DIR` 决定
（默认 `<工作区>/var/runs`，由 ops/start_all.sh 注入）：

```text
<工作区>/var/runs/<runId>/
├── run.json                 整条 PaperRun（重启后可直接恢复）
├── intake/
│   ├── paper.pdf            原始/下载的 PDF
│   ├── source.tar.gz        arXiv 源码包（arxiv/latex 输入时）
│   ├── content.md           ★ M1 主产物
│   ├── meta.json            标题/作者/来源/页数/校验和
│   ├── sections.json        章节树（M2 的阅读地图）
│   └── images/              ★ fig-1.png / table-2.png / page-1.png ...
├── understand/
│   ├── digest.json          ★ 唯一事实源
│   └── reading_note.md      中文精读笔记
├── article/
│   ├── xhs.md               ★ 小红书图文文案
│   ├── wechat.md            同源派生的公众号长文
│   └── cards/p1.png ...     ★ 发布用卡片图
└── publish/
    ├── xhs_receipt.json     发布回执
    └── export/              仅导出模式：图片 + 文案，人工手动发
```

## 技术选型

| 环节 | 选型 | 理由 |
| --- | --- | --- |
| HTTP 服务 | FastAPI + uvicorn | 已有环境、SSE 原生支持、契约式建模 |
| PDF 解析 | **PyMuPDF (fitz) + pymupdf4llm** | 本机没有 GPU（`nvidia-smi` 被系统禁用），MinerU 的 CUDA 通道不可用；PyMuPDF 零依赖、秒级、纯 CPU，版面/图/表都能拿 |
| 公式 | 保留 LaTeX 文本，前端 KaTeX 渲染 | 不引入 Node 侧渲染链 |
| LLM | OpenAI 兼容 /chat/completions | 默认复用 DSH 里已配好的 `opencode go` 通道（`GO_API_KEY`），可换成任意 OpenAI 兼容端点 |
| 卡片渲染 | PIL 直绘（`app/cards/render.py`） | 版式固定，PIL 比"起浏览器 → 截图"更快更可复现；本机 `chrome-headless-shell` 虽在，但不值得为固定版式引入浏览器进程 |
| 发布 | 本机 `xiaohongshu-mcp`（Go，:18060） | 已登录（账号 momo），MCP + HTTP 双接口齐全，不重造发布轮子 |

**为什么不是 MinerU**：本机 GPU 被系统屏蔽（`Failed to initialize NVML: GPU access blocked by the operating system`），
MinerU pipeline 只能退回 CPU，19 页论文要几分钟且需下载数 GB 模型；而当前目标是把链路先跑通、可复现，
PyMuPDF 的文本/图注/表格保真度对「生成小红书图文」这个目标已经够用。`intake.engine` 字段预留了
`mineru` 开关，将来上 GPU 机器时按同一接口换实现即可，见 `01-module-intake.md`。

## 与前端对接

```bash
# 后端
cd papercast-server && ./scripts/run_dev.sh          # http://127.0.0.1:8000
# 前端（自动从 mock 切到 HttpPipelineApi）
cd papercast && VITE_API_BASE=http://127.0.0.1:8000 npm run dev
```

契约细节见 `04-api-contract.md`，上线见 `05-deployment.md`。
