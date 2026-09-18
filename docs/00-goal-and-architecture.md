# PaperCast · 目标与分层架构

> 跨子项目总纲：前端 `apps/papercast` / 后端 `apps/papercast-server` / 发布 `apps/xiaohongshu-mcp` / 素材研究 `reference/baoyu-research`
> 版本：R1 · 2026-09-18 · 目录分层更新：2026-09-19 · 状态：待评审
> 目录与路径规范见 [`conventions.md`](conventions.md)，迁移对照见 [`migration-2026-09-19.md`](migration-2026-09-19.md)；
> 各子项目的实现细节见其自身文档：后端 `apps/papercast-server/docs/00~06`、前端 `apps/papercast/README.md`

---

## 1. 项目意图（为什么做）

**一句话：一篇论文进去，多形态传播物料出来，并且能安全地投递到内容平台。**

原始表述（项目最初的意图，未删改）：

> 论文解读Agent（把复杂论文翻译成通俗语言）→ 可视化Agent（生成论文核心图表的科普版）→
> 中文传播Agent（写知乎/公众号科普文）→ 英文传播Agent（写 Twitter/LinkedIn thread）→
> 视频化Agent（生成 3 分钟论文解读视频脚本）→ 社区运营Agent（选择合适学术社区发布+互动），
> **6 个 Agent 让一篇论文实现多形态传播**

拆成三层来理解：

| 层 | 内容 |
| --- | --- |
| **表层** | 论文（PDF / arXiv / LaTeX）→ 文章、卡片、海报、视频 + 一个展示 dashboard |
| **中层** | 把研究者的**传播工作流整体自动化**：读到论文 → 产出物料 → 投递 → 运营。小红书先行，因为它是唯一有可用开源发布通道（`xiaohongshu-mcp`）的中文平台，能把「进 → 出」真正闭环 |
| **深层** | 一个**可追溯、带人工闸门**的学术传播中台。传播内容偏离论文事实是学术声誉问题；发布是不可逆且有账号风险的动作。所以它宁可慢一点，也要多一道校验和闸门 |

**注意取向**：这不是「一键生成爆款」类项目。它的核心资产是**证据链**与**闸门**，不是出图速度。

---

## 2. 本轮目标（R1）

**一句话：把「一份真论文 → 一整套可发布物料 → 真实投递到小红书」端到端跑通，全过程在 dashboard 里可见、可控、可追溯。**

### 2.1 交付物（验收口径）

1. 前端切换到真后端（`VITE_API_BASE=http://127.0.0.1:8000`），流程不再依赖 mock 适配器
2. 后端 M1 + M2 + M3 三段真跑通：已上传的 `paper2video.pdf`（`up_e543faed5be4`）产出一整套物料
3. 小红书图文**真实投递成功**（人工闸门放行后），回执落盘为 `publish/xhs_receipt.json`
4. dashboard 上能直接看到**证据链**（`checks` 的数字回溯结果）与闸门控制
5. 一条可复现的 demo 路径 + 一段能讲给人听的说明

### 2.2 非目标（R1 明确不做）

| 不做 | 原因 |
| --- | --- |
| 全自动无人值守发布 | 发布不可逆、有账号风险，闸门是设计的一部分，不是临时限制 |
| `poster` / `video` 真实生成 | 依赖 Paper2Poster / Paper2Video 两个上游项目，先以 `skipped` 状态让主链路通 |
| MinerU 解析通道 | 本机 GPU 被系统屏蔽（`Failed to initialize NVML`），MinerU 只能退回 CPU 且要下数 GB 模型；先用 PyMuPDF |
| 英文传播（X / LinkedIn thread） | 属 R2 的差异化部分，先确保中文闭环 |
| 公网部署与域名 | 先在本机 `:8000` + `:5178` 跑通，再谈 nginx 与远端 |

---

## 3. 需要做的内容

工作项按依赖顺序排列。**归属**列指出由哪一端负责，**验收**列是可机器检查的判据。

### W1 · 前后端接线（前端，无依赖，最先做）

| 项 | 内容 |
| --- | --- |
| 现状 | 前端只实现了 `GET` 轮询那条路径；后端的 `/api/uploads`、`/api/env`、SSE `/events` 尚未被使用 |
| 要做 | ① `VITE_API_BASE` 切真后端；② PDF 入口改为真上传（`POST /api/uploads` 拿 `uploadId`）；③「引擎与环境」视图改用 `GET /api/env`（现在写死了 5 条）；④ 接入 SSE `/api/runs/:id/events`，保留轮询作为降级；⑤ 阶段 `skipped` 状态在 UI 上正确呈现（现在只显示「尚未产出」） |
| 验收 | 关掉 mock 后，六段进度、日志、产物、闸门按钮全部由 `:8000` 驱动；`poster`/`video` 明确显示「本轮跳过」而不是「未产出」 |

### W2 · M2 内容生成真跑（后端）

| 项 | 内容 |
| --- | --- |
| 现状 | 代码已就位（`app/modules/generate.py`、`app/prompts.py`、`app/cards/render.py`），尚未跑过真 LLM |
| 要做 | 用真 LLM 通道（`opencode.ai/zen/go/v1` + `GO_API_KEY`，模型 `deepseek-v4.1-flash`）生成 `digest.json` → `reading_note.md` → `xhs.md`；卡片图 HTML→PNG 渲染（chrome-headless-shell） |
| 验收 | `<工作区>/var/runs/<id>/understand/digest.json` 字段齐全；`article/xhs.md` ≤1000 字且无公式；`article/cards/p1..pN.png` 均为 3:4 且中文不出现豆腐块（CJK 字体就绪） |

### W3 · 证据链在 UI 可见（前后端）

| 项 | 内容 |
| --- | --- |
| 现状 | 后端已设计 `verify_digest()` 数字回溯校验并写入 `stage.checks`；前端 `DigestViewer` 已能读 checks |
| 要做 | 跑通后确认 checks 的真实结果能落到前端：绿=数字可在原文检索到，红=找不到；红项要在 UI 上显式告警而不是静默 |
| 验收 | 故意注入一个假数字时，`checks` 变红并在 dashboard 上可见 |

### W4 · 发布链路（后端 + 发布）

| 项 | 内容 |
| --- | --- |
| 现状 | `xiaohongshu-mcp`（Go，`:18060`）已登录（账号 momo），实测过 `/api/v1/feeds/search`；后端 `app/modules/publish.py` 已写好调用 |
| 要做 | ① 发布前检查 `GET /api/v1/login/status`；② 二维码 `GET /api/v1/login/qrcode` 回传 base64 给前端展示（登录失效时不必下命令行）；③ 闸门放行调用 `POST /api/v1/publish`；④ `publish/export/` 兜底目录（title.txt + content.txt + 卡片图）——**MCP 掉线也能 30 秒手动发**；⑤ 回执写 `xhs_receipt.json` |
| 验收 | 端到端发出 1 篇小红书图文；断掉 MCP 后导出目录仍可用 |

### W5 · 部署与定时（运维，R1 末尾）

| 项 | 内容 |
| --- | --- |
| 边界 | **重计算在远端服务器；发布只在本地**（账号凭证与不可逆动作不出本机） |
| 要做 | ① 远端部署后端（`uv` + `.venv` + uvicorn + nginx 反代）；② 本地保留 `xiaohongshu-mcp`，通过隧道/本机回调投递；③「每日定时收集」——定时拉取关注方向的新论文并建 run（先只收集与生成，不自动发布） |
| 验收 | 远端能完成 intake→generate，导出目录回到本地后可手动发布 |

### W6 · R2 候选（本轮之后）

| 项 | 内容 |
| --- | --- |
| 补齐原始意图 | `poster` / `video` 两个阶段从 `skipped` 变为实现（Paper2Poster / Paper2Video） |
| 差异化 | **英文传播**（X / LinkedIn thread）与**学术社区运营**（社区选择 + 互动）——调研结论指出这两块才是没有开源项目打通的空白区 |
| 素材增强 | `baoyu-research` 的 AI 出图能力（封面 / 信息图 / 漫画）接入 M2；本机 `codex` CLI 在 PATH 里，`codex-cli` provider 可用订阅出图，无需图像 API key |

---

## 4. 分层架构

### 4.1 五层 + 三条横切

```text
┌─────────────────────────────────────────────────────────────────────┐
│ L4 运营与治理层  排期 · 每日收集 · 回执与指标 · 账号状态 · 审计日志      │
├─────────────────────────────────────────────────────────────────────┤
│ L3 发布层        渠道适配器：小红书(MCP) · 公众号 · B站 · X             │
│                  ⏸ 人工闸门②：真实投递前必须放行                       │
├─────────────────────────────────────────────────────────────────────┤
│ L2 生成层        多形态物料：中文文章 · 小红书图文+卡片 · 海报 · 视频   │
│                  · 英文 thread（R2）                                  │
├─────────────────────────────────────────────────────────────────────┤
│ L1 理解层        digest.json —— 唯一事实源                            │
│                  ⏸ 人工闸门①：理解层确认后才往下生成                   │
├─────────────────────────────────────────────────────────────────────┤
│ L0 输入层        归一化：PDF 上传 · arXiv 链接 · LaTeX 源              │
└─────────────────────────────────────────────────────────────────────┘
      横切 A 控制面：状态机 / 持久化 / SSE / 闸门      (apps/papercast-server)
      横切 B 渲染底座：chrome-headless-shell · ffmpeg   (ops/shot 已验证)
      横切 C LLM 网关 + 证据审计：反幻觉约束 · 数字回溯校验
```

### 4.2 各层职责与现状

| 层 | 职责 | 输入 → 输出 | 现有实现 | 缺口 |
| --- | --- | --- | --- | --- |
| **L0 输入** | 任何形态归一化成「md + 独立图片 + 结构化元数据」，下游只认这一种 | PDF / arXiv / LaTeX → `content.md` + `images/` + `meta.json` + `sections.json` | `app/intake/{pdf_parser,latex_parser,arxiv}.py`（PyMuPDF，双栏、图注配对、表格裁图） | 扫描件无 OCR；LaTeX 无引擎，走源码解析 |
| **L1 理解** | 一次理解、处处复用；产出唯一事实源 | `content.md` + `images/` → `digest.json`（贡献/方法/证据/图表/局限） | `app/modules/generate.py` 前半 + `digest` 校验 | 未跑过真 LLM |
| **L2 生成** | 从同一事实源派生不同形态，互不矛盾 | `digest.json` → `reading_note.md`、`xhs.md`、`wechat.md`、`cards/*.png` | `app/modules/generate.py` + `app/cards/render.py`（HTML→PNG，**确定性排版，非 AI 出图**） | 海报 / 视频 = `skipped`；英文 thread 未做 |
| **L3 发布** | 渠道投递 + 闸门 + 兜底 | `xhs.md` + `cards/` → `xhs_receipt.json`、`export/` | `app/modules/publish.py` → `xiaohongshu-mcp` `:18060` | 仅小红书；公众号/B站/X 未接 |
| **L4 运营** | 排期、收集、回执、指标 | 定时任务 / 回执 → 新 run、投放记录 | 尚无 | 整层待建 |
| **横切 A 控制面** | 运行状态机、持久化、事件推送、闸门 | `PaperRun` 全生命周期 | `app/{pipeline,store,models}.py`；`run.json` 可恢复；REST + SSE | 前端未接 SSE |
| **横切 B 渲染底座** | 一切「HTML → 图 / 视频」的确定性渲染 | HTML → PNG；音频+图 → MP4 | `ops/shot/shot.mjs`（chrome-headless-shell 已验证）；Playwright 缓存内含 `ffmpeg-linux` | 视频合成未接 |
| **横切 C LLM + 审计** | 生成与校验分离，让幻觉可被发现 | prompt → 结构化 JSON；数字 → 回溯校验 | `app/{llm,prompts}.py`；`verify_digest()` → `stage.checks` | 未在真数据上验证 |

### 4.3 组件映射（现有目录 → 层）

| 目录 | 角色 | 层 |
| --- | --- | --- |
| `apps/papercast/` | Vue 3 前端 dashboard（6 阶段模型 + mock/http 双适配器） | 全层的**视图与控制面** |
| `apps/papercast-server/` | FastAPI 后端（M1/M2/M3） | L0–L3 + 横切 A/C |
| `apps/xiaohongshu-mcp/` | Go 实现的小红书 MCP + HTTP 接口（独立 git 仓库） | L3 的渠道适配器 |
| `reference/upstream/`（23 个仓库） | 上游参考实现（Paper2Poster / Paper2Video / paper2x / paper2anything / 知乎发布系 …） | L2 的 R2 来源、L3 渠道调研 |
| `reference/baoyu-research/` | 出图后端研究（21 个 `baoyu-*` skill + codex-imagegen 方案） | L2 的素材增强（R2） |
| `ops/shot/` | 截图与 HTML→PNG 渲染脚本 | 横切 B |
| `ops/{start_all,stop_all,build_mcp}.sh`、`ops/bin/` | 起停脚本与本地编译的发布二进制 | 横切 B / L3 运行入口 |
| `var/` | 运行态：runs · uploads · logs · pids · samples · cache · toolchains | 横切 A 的持久化落点 |

### 4.4 数据契约（稳定接口，两端共同遵守）

**阶段模型**：`intake → understand → article → poster → video → publish`

```text
pending ──► running ──┬─► done
             │        ├─► failed
             │        └─► skipped      （poster / video 在本轮为此状态）
             └─► waiting(gate) ──放行──► running
```

**HTTP 契约**（后端严格实现前端 `src/api/http.ts` 已声明的形状，前端零改动即可切换）：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/runs` | 建运行（`{source, config}` → `PaperRun`） |
| `GET` | `/api/runs` · `/api/runs/:id` | 列表 / 详情 |
| `POST` | `/api/runs/:id/cancel` | 取消 |
| `POST` | `/api/runs/:id/stages/:sid/gate` | 闸门放行 `{optionId, note?}` |
| `GET` | `/api/runs/:id/events` | SSE 事件流（心跳 15s） |
| `POST` | `/api/uploads` | 上传 PDF / LaTeX zip → `uploadId` |
| `GET` | `/artifacts/:runId/:path` | 产物静态服务（已做目录穿越防护） |
| `GET` | `/api/env` · `/api/health` | 真实探测的引擎环境状态 / 存活探针 |

**产物目录约定**（`PAPERCAST_DATA_DIR`，默认 `<工作区>/var/runs`，由 `ops/start_all.sh` 注入）：

```text
var/runs/<runId>/
├── run.json              整条 PaperRun（重启可恢复；不对外暴露）
├── intake/               content.md · meta.json · sections.json · images/
├── understand/           digest.json ★ 唯一事实源 · reading_note.md
├── article/              xhs.md ★ · wechat.md · cards/p1.png…
└── publish/              ready.json · export/{title.txt,content.txt,p1.png…} · xhs_receipt.json
```

---

## 5. 关键设计决策（ADR）

| # | 决策 | 理由 |
| --- | --- | --- |
| 1 | **单一理解层**：`digest.json` 是所有下游文案的唯一事实源 | 否则小红书文案与精读笔记会互相矛盾，且无法定位谁错 |
| 2 | **数字可追溯 + 机器校验**：`results[].value` 必须能在原文检索到 | 学术传播的可信度是硬约束；论文没给的数值写「未给出具体数值」而不是编 |
| 3 | **人工闸门是一等公民**：理解层确认、发布前确认 | 发布不可逆且有账号风险；也让人能在生成跑偏时及时止损 |
| 4 | **发布只在本地 + export 兜底** | 账号凭证不出本机；MCP 挂掉也能手动发出，发布链路的可用性不依赖任何外部服务 |
| 5 | **确定性排版优先于 AI 出图**：卡片图用 HTML→PNG | 论文卡片是排版问题不是创作问题；AI 出图会引入幻觉图形与不可复现性。`baoyu-research` 的能力留给封面/信息图等创作型产物 |
| 6 | **PyMuPDF 而非 MinerU** | 本机 GPU 被系统屏蔽；PyMuPDF 零依赖、秒级、纯 CPU，对「生成小红书图文」的保真度足够。`intake.engine` 预留 `mineru` 开关 |
| 7 | **前端 mock / http 双适配器** | 后端未就绪时前端可独立开发与演示；切换只靠一个环境变量 |
| 8 | **六阶段模型是 UI 的稳定契约** | 阶段可 `skipped` 不可删除；上游能力逐步补齐时前端无需改动 |

---

## 6. 验收标准（R1 收尾时的检查清单）

```bash
# 1. 后端存活
curl -s http://127.0.0.1:8000/api/health

# 2. 真实探测的引擎环境（不写死）
curl -s http://127.0.0.1:8000/api/env

# 3. 上传 → 建 run → 看进度（SSE）
curl -F file=@var/uploads/up_eef613c136c1/paper2video.pdf \
     http://127.0.0.1:8000/api/uploads
```

| # | 判据 | 通过标准 |
| --- | --- | --- |
| 1 | 六段流水线 | `intake`/`understand`/`article`/`publish` 为 `done`（或 `waiting` 后放行），`poster`/`video` 为 `skipped` 且 UI 明确说明 |
| 2 | 理解层 | `digest.json` 字段齐全，`contributions`/`results`/`figures` 非空 |
| 3 | 证据链 | `stage.checks` 的数字回溯结果在 dashboard 可见，且不存在静默失败 |
| 4 | 物料 | `xhs.md` ≤1000 字无公式；卡片 3:4、中文无豆腐块 |
| 5 | 发布 | 闸门放行后 `xhs_receipt.json` 落盘且笔记在线可访问；断 MCP 时 `export/` 可用 |
| 6 | 可复现 | 删掉 `var/runs/*` 后按 demo 步骤重跑，结果一致 |
| 7 | 前端 | 无控制台错误；`vue-tsc --noEmit` 与 `vite build` 通过 |

---

## 7. 风险与边界

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 平台风控 / 账号封禁 | 发布失败或账号受损 | 保留人工闸门；`export/` 兜底；不自动发布 |
| LLM 幻觉导致事实错误 | 学术声誉风险 | 单一事实源 + 数字回溯校验 + 理解层闸门 |
| `poster`/`video` 长期 `skipped` | 产品承诺与实际能力不符 | UI 显式标注「本轮跳过」，不假装产出 |
| 本机无 GPU / 无 TeX / 无 OCR | 输入覆盖不全 | 扫描件与 LaTeX 编译明确报错，不静默降级 |
| 远端部署后发布回传 | 凭证外泄或链路复杂 | 「重计算远端、发布本地」的边界不可跨越 |
| 原始意图的英文传播 / 社区运营缺失 | 与立项表述有差距 | 明确列入 R2，并在文档中标注为已知差距 |

---

## 8. 现状快照（2026-09-19 00:xx，目录分层整理后）

| 组件 | 状态 |
| --- | --- |
| `apps/papercast-server` | 可运行：`./ops/start_all.sh backend` → `http://127.0.0.1:8000/api/health`；运行数据在 `var/runs`（`run_224e72b5a672` / `run_3b0e657e0f50` / `run_a7b9460d3953`），上传在 `var/uploads`（3 个 `paper2video.pdf` 上传副本） |
| `apps/papercast`（前端） | 可运行：`http://127.0.0.1:5178`；类型检查与构建通过；10 张界面截图在 `apps/papercast/screenshots/`；样例产物在 `apps/papercast/public/samples/` |
| `apps/xiaohongshu-mcp` | 已登录（账号 momo）；二进制在 `ops/bin/xiaohongshu-mcp`（配套 `-auth` 版与 `xiaohongshu-login`），`./ops/build_mcp.sh` 可重建 |
| `ops/` · `var/` · `reference/` | 2026-09-19 完成五层分层：代码 / 参考 / 工具 / 运行态 / 文档；规范见 `docs/conventions.md` |
| 前端 ↔ 后端 | 仍可切 mock 或真后端；W1（接线）状态以 `apps/papercast/src/api/` 为准 |
| 并行轨道 | 知乎发布（`zhihu-official/` 等 8 个目录，见 README 迁移期例外）正在开发中 |
