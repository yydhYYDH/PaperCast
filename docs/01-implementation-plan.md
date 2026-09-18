# 01 · 实现方案（R1）

> 本文回答「**具体怎么建**」。`00-goal-and-architecture.md` 回答「为什么建、建成什么样」，`TODO.md` 回答「谁做什么」。
> 版本：**v1 草案** · 2026-09-19 00:20 · 编写时点了实测现状（见 §3），凡未验证的都标了「待验」。
> 阅读顺序：00（意图/分层）→ 本文件（实现）→ TODO（分工）。

---

## 1. 本方案的定位

当前工作区是**多会话并行**推进的：后端 M1–M3、渠道层（小红书/知乎/B站）、视频、前端各有会话在动。
所以本文不做「从零设计」，而是做三件事：

1. **固化集成契约** —— 把两端正在各自实现的东西钉成一份不可随意改的接口清单（§6），使并行不会跑偏；
2. **补齐没人负责的部分** —— 英文传播（§5.3）、前端接线收尾（§5.8）、视频契约闭合（§5.6）；
3. **给出里程碑与验收** —— 每个里程碑都能用命令判定「到底做完了没有」（§8）。

---

## 2. 目标与非目标

**R1 目标**：把「一份真论文 → 一整套可分发物料 → 真实投递到内容平台」端到端跑通，全过程在 dashboard 里可见、可控、可追溯。

**非目标**：全自动无人值守发布；远端部署（本轮不接入）；poster 真实生成（维持 skipped）。
**已定**：视频由另一会话负责（按 §5.6 契约接入）；英文传播本轮要做（§5.3）。

---

## 3. 现状基线（2026-09-19 00:20 实测）

### 3.1 已经能跑、且我亲自验过的

| 项 | 证据 |
| --- | --- |
| 后端 M1–M3 跑通一次全绿 | `apps/papercast-server/docs/06-verification.md`：run `run_224e72b5a672`，intake 11.4s / 68k 字符 / 12 图 / 23 章节；understand 11 条证据全可回溯；article 773 字 + 6 张 1080×1440 卡片；publish 走 draft |
| 前端 × 真后端已连通 | 我跑的 `ops/shot/live_check.mjs`：页面渲染 6 张阶段卡 + 7 行历史，**200 /api/runs**，控制台 0 错误，后端日志里累计 100+ 次轮询 |
| `/api/env` 真实探测可用 | 实测 200 / 755B：`intake{engine:pymupdf, gpu:false, mineru:false, ocr:false}`、`latex{engine:null, mode:source-only}`、`llm{configured:true, model:deepseek-v4.1-flash}`、`cards{chrome, cjkFont, cjkFontUsable:true}`、`publish.xiaohongshu{reachable:true, loggedIn:false}`、`dataDir`、`runs:3` |
| 上游 28 个可复现 | `./ops/sync_upstream.sh --list` → 28 一致；登记表 `docs/research/upstream-repos.md` |
| 启停与运行态 | `ops/start_all.sh`（backend + frontend + mcp，幂等）；日志 `var/logs/`、pid `var/pids/`、数据 `var/runs/` |

### 3.2 正在飞（别的会话在做，本方案只对接）

| 项 | 观察到的痕迹 |
| --- | --- |
| **渠道适配层** | 后端已有 **17 条路由**，含 `/api/platforms`、`/api/platforms/{id}`、`/api/platforms/{id}/login/qrcode`（`app/platforms.py`）；前端已出现 `listPlatforms / platformLoginQrcode / platformLoginStart / platformExportDraft / platformPublish / platformLogout`，类型里有 `loginMode: mcp \| playwright \| openapi \| cli` |
| **B站登录** | run 目录里已有 `login/bili_login_qr.png`（00:19） |
| **视频** | run 目录里已有 `video/论文分享/`；但 store 里 video 阶段仍是 skipped |

### 3.3 缺口（本方案要补的）

1. **视频契约未闭合**：产物已落盘，但 `stage.artifacts` 没登记 → 前端拿不到（见 §5.6）
2. **英文传播**：完全没有
3. **前端四处硬编码/缺失**：PDF 入口只记文件名（未真上传）；`/api/env` 未消费、「引擎与环境」视图仍写死；VideoViewer 旁白路径写死示例；skipped 呈现语义不准
4. **校验告警的处置策略未定**：实测日志里出现 `2 条含部分未回溯数字（已保留，人工复核）：["PresentArena 胜率：17.0%", "基准规模与统计：13.3"]` —— **校验真的在生效**，但「保留 + warn」是不是想要的语义，需要拍板（见 §9）
5. **小红书当前未登录**：`/api/env` 报 `loggedIn:false`（MCP 在跑但会话失效）→ 真投递前要重新扫码

### 3.4 01:20 复核补充（写 §5.5 时实测）

- **渠道层的真实能力比初稿假设的大**：本轮在用 3 条渠道（小红书 mcp / 知乎 playwright / B站 cli），带 `endpoint`、`needs[]`、`capabilities[]`、`loginHint` 与实时 `state` 探测，前端已有 `PlatformsView.vue` + `PlatformLoginDialog.vue`。
- **三条渠道当前全部不可用**：`xiaohongshu-mcp` 已停（18060 未监听，`/api/env` 也报 `reachable:false`）、`zhihu-publisher` 已停（18070 未监听）、B站未装 `biliup`。**所以此刻我无法复现扫码实测**；但另一会话已实证（证据见 §5.8 A7）。我这条只代表「此刻环境不可复现」，**不代表功能未实现**。
- **知乎不能纯扫码**：渠道自述「桌面窗口人工登录（风控拦纯 HTTP 扫码）」。用户要的「知乎扫码接入前端」在实现上等于：前端触发 + 引导 + 状态轮询，二维码在桌面窗口里；无显示环境走 `apps/zhihu-publisher/scripts/login-headed.sh`。**这也意味着知乎不必等 APP_SECRET**（初稿把 APP_SECRET 当成了前置，是错的）。

---

## 4. 实现路线与里程碑

```text
M0 契约对齐 ──► M1 中文闭环 ──► M2 英文 + 多平台 ──► M3 资产扩展
（§6 冻结）      （一篇真论文        （thread 产出、          （video 接入、
                  跑到真实投递）       知乎/B站通道）           poster、定时收集）
```

| 里程碑 | 完成定义（可命令判定） |
| --- | --- |
| **M0 契约对齐** | §6 的字段/接口两端一致：`vue-tsc --noEmit` 通过 + `/api/env`、`/api/uploads`、`/api/platforms` 三个接口前端全部真实消费（不再有写死数据） |
| **M1 中文闭环** | 一条真论文跑完 → `xhs.md` + `cards/*.png` → 闸门放行 → 真实投递成功 + 回执落盘；断 MCP 时 `export/` 仍可用 |
| **M2 英文 + 多平台** | 同一篇论文额外产出可粘贴的 X / LinkedIn thread（数字全部可回溯）；知乎通道真投成功；B站通道至少能产出可审核草稿 |
| **M3 资产扩展** | video 阶段在 UI 里可见可播（契约闭合）；poster 视需要启动；定时收集按日产出 run |

---

## 5. 模块实现方案

### 5.1 M1 · intake（已实现，只补边界）

- 现状：`app/intake/{pdf_parser, arxiv, latex_parser}.py`，PyMuPDF 单页管线（字号阶梯 → 标题、双栏 y 排序、`find_tables` → md 表 + 裁图、图注 120pt 配对、矢量图 `zoom=3` 回退）。
- 待补：**扫描件无 OCR 要明确报错**（`ocr:false` 已知），不要静默产出空 md；LaTeX 无引擎时走源码解析并在 UI 标注「未编译」。
- 验收：`var/samples/deeprare.pdf` 与 arXiv 2510.05096 两条入口都产出 `content.md` + `images/` + `sections.json`，checks 全 pass。

### 5.2 M2 · 理解与中文生成（已实现，补策略）

链路：`content.md` → `digest.json`（唯一事实源）→ `reading_note.md` / `xhs.md` → `cards/*.png`（HTML → PNG，chrome-headless-shell）。

- **校验必须可见**：`verify_digest()` 的数字回溯结果写进 `stage.checks`，前端阶段卡片与产物面板原样展示；warn 项要在 UI 上显式列出（不是只写日志）。
- **已定（用户决策 1 · 2026-09-19）**：**保留 + warn + 人工复核** —— 不自动丢弃，也不静默通过。运营含义：`warn` 明细必须在 UI 逐条列出，**发布闸门就是复核发生的地方**（闸门放行 = 人工已看过这些数字），闸门未放行时不得投递。
- 长文生成注意 token：实测精读笔记用 `max_tokens=12000`，会触发重试路径 —— 要有明确的超时/重试与「第 N 次」日志（已有）。

### 5.3 M2' · 英文传播（**产出但本轮不投递** —— 用户决策 2：英文不发）

**形态选择**：**并入 `article` 阶段的变体，不新增阶段**。理由：与中文文案同源（都从 `digest.json` 派生）、复用现有 tab 机制、不必动六阶段契约（两端都改契约的成本远高于收益）。若演示确需独立阶段，再升级 —— 升级点只在 `STAGE_ORDER` 与 UI 分组。

| 项 | 设计 |
| --- | --- |
| 变体 id | `en-x-thread`、`en-linkedin`（与现有中文变体并列，见 `STAGE_META.article`） |
| 产物 | `article/en-x-thread.md`、`article/en-linkedin.md`；导出走既有 `publish/export/` |
| 生成 | 从 `digest.json` 派生（**不许直接读 `content.md`**，否则绕过单一事实源）：hook → 3–5 条论点 → 证据 → 链接 |
| 长度约束 | X：单条 ≤280 字符、整串 ≤7 条；LinkedIn：≤1300 字符、段落化 |
| 校验 | 同样跑数字回溯（注意英文数字格式差异：`17.0%` vs `17.0 %`），结果进 `checks` |
| 投递 | **本轮不接通道、不投递**（用户决策 2）：产物照出，只落 `export/`，要不要发由人自己复制。X / LinkedIn 的自动化一律留 R2（可参考上游 `baoyu-post-to-x`） |
| UI | `ArticleViewer` 的 tab 先按语言分组（中文 / 英文），再按平台 |
| 验收 | 同一篇论文产出可直接粘贴的 thread，**每个数字都能在原文检索到**，无公式、无中文残留 |

### 5.4 物料渲染（已实现，固化契约）

- 卡片：1080×1440（3:4）、中文用 CJK 字体（`/api/env` 报 `cjkFontUsable:true`）、确定性排版（HTML → PNG，**不用 AI 出图**）。
- 契约：卡片文件名有序（`p1.png` …），顺序即发布顺序；换行/溢出在模板侧解决，不靠人工修图。

### 5.5 渠道适配层与发布（**权威规格在别处，本节只记对接点**）

> **本节不是契约来源**：渠道的正式规格已由后端会话写在 `apps/papercast-server/docs/08-channels.md`（`app/channels/` 契约 + 三 adapter + registry + `GET /api/channels` + 每渠道独立回执）。本节只记**前端要对接什么**，避免维护第二份会漂移的契约。
> **待澄清（§9-7）**：现在同时活着两套端点 —— `/api/platforms*`（登录 / 账号 / 状态探测，「平台账号」页在用）与 `/api/channels*`（投递扇出与回执，C1 交付），两者都能 200。职责边界需后端 owner 明确，否则前端会出现两个「发布」入口。

**统一模型（已按后端实测更正）**：一条渠道 = `{ id, name, kind, login, state, account, detail, endpoint, needs[], capabilities[], loginHint }`
（初稿里我写的 `loginMode/available/loggedIn` 是想象出来的字段名，实测后端用的是 `kind` + `login` + `state` —— 契约以实测为准。）

- `kind`：传输形态 `mcp | playwright | openapi | cli`；`login`：登录形态 `qrcode | browser | env | cli`
- `state`：`ready | offline | unconfigured | unknown`；`needs[]` 是该渠道投递的硬性要求，`loginHint` 直接可当 UI 引导文案

动作固定为 **登录 → 导出草稿 →（闸门）→ 投递 → 回执**；两类登录形态要在同一套 UI 里表达（见 A7）。

| 能力 | 后端 | 前端（已出现） |
| --- | --- | --- |
| 渠道列表 | `GET /api/platforms`（`?force=1` 强制探测） | `listPlatforms(force)` |
| 渠道详情 | `GET /api/platforms/{id}` | — |
| 扫码登录 | `GET /api/platforms/{id}/login/qrcode`（回 base64 PNG） | `platformLoginQrcode` / `platformLoginStart` |
| 导出草稿 | `POST /api/platforms/{id}/export` | `platformExportDraft` |
| 真实投递 | `POST /api/platforms/{id}/publish` | `platformPublish` |
| 退出登录 | `POST /api/platforms/{id}/logout` | `platformLogout` |

**必须守住的三条**：

1. **投递前必须有闸门放行凭证**（publish 阶段的 gate 已 resolved），脚本默认只出 `export/`；
2. **每个渠道的产物目录自包含**：`publish/export/{title.txt, content.txt, images}` + `publish/<channel>_receipt.json`；
3. **渠道不可用（未登录/掉线）不能阻塞链路**：`export/` 必须完整到「30 秒手动发得出去」。

| 渠道 | kind / login | 现状（01:20 实测） | 本轮动作 |
| --- | --- | --- | --- |
| 小红书 | `mcp` / `qrcode` | `state=offline`：MCP 未运行（18060 未监听） | 起 `./ops/start_all.sh mcp` → 前端点「扫码登录」→ 真投一次 + 回执 |
| 知乎 | `playwright` / `browser` | `state=offline`：zhihu-publisher 未运行（18070 未监听）；**风控拦纯 HTTP 扫码** | 起 `./ops/start_all.sh zhihu` → 前端「打开浏览器登录」→ 桌面窗口扫码 → 状态自动转已登录；本机无显示时 `./apps/zhihu-publisher/scripts/login-headed.sh` |
| B 站 | `cli` / `cli` | `state=offline`：`biliup` 未安装 | 本轮只做「视频产物就绪 + 草稿」，投稿留 R2 |

### 5.6 M3 · 视频接入（**契约闭合，本方案负责对齐**）

**问题**：`var/runs/<id>/video/论文分享/` 已有产物，但 store 里 video 仍 `skipped`、`artifacts` 为空 → 前端拿不到。闭环要同时满足：

1. 产物落在 `var/runs/<runId>/video/`，**目录名用 ASCII**（建议 `video/share/`）—— 中文目录名会进 URL，编码与跨平台都容易踩坑；
2. 登记产物：`{ kind: 'video', url: '/artifacts/<runId>/video/<file>.mp4', meta: { durationSec, w, h } }`，并在同目录放 `narration.json`，形状 `{ title, totalSec, slides: [{ index, title, bullets[], narration, durationSec }] }`；
3. 阶段置 `status='done'`、`progress=100`；
4. 前端 `VideoViewer` 把写死的 `/samples/video/narration.json` 换成**从该阶段产物里取**；时间轴已做等比对齐（片长与 `totalSec` 不一致会自动缩放），无需视频侧迁就。

### 5.7 poster（**本节已过时，见 `07-poster-and-cards.md`**）

> poster 与卡片规格已由后端会话写在 `apps/papercast-server/docs/07-poster-and-cards.md`（00:19 更新），本节不再转述。前端只需保证：`skipped` 时显示「本轮跳过 · 原因」，有产物时按卡片顺序展示。

### 5.8 前端 dashboard（A 组实现细节）

| 编号 | 实现 | 备注 |
| --- | --- | --- |
| A1 | PDF 入口改真上传：`FormData` → `POST /api/uploads` → 用返回 `uploadId` 作 `source.value` | 现在只把**文件名**当 value（`IntakePanel.vue`），真后端会解析失败 |
| A2 | `VideoViewer` 旁白路径去硬编码 | 依赖 §5.6 |
| A3 | 接 `GET /api/env`，替换 `src/data/env.ts` 里写死的 `ENV_DEPS` / `ENGINE_ROWS` | 后端已给真实探测结果（§3.1） |
| A4 | 接 SSE `/api/runs/:id/events`，**保留轮询作为降级**（心跳 15s） | 可选增强 |
| A5 | 文案纠正：界面里「走 MinerU 解析」与实际（PyMuPDF）不符 | ✅ **已修完**（2026-09-19）：前端 `MinerU` 归零，6 处改 PyMuPDF；文档里剩下的 MinerU 都是「为什么不用它」的决策记录 |
| A6 | `skipped` 语义：预览器「尚未产出」→「本轮跳过 · 原因」 | 阶段卡片已有「跳过」标签 |
| A7 | 扫码 / 浏览器登录接入前端 | **已由另一会话基本实现**：`PlatformsView.vue`（渠道面板 + 探测 + 退出登录）+ `PlatformLoginDialog.vue`（二维码图 + 过期倒计时 + 状态轮询）。**待补**：知乎是 `browser` 形态（风控拦纯 HTTP 扫码），前端要能区分「页内显示二维码」与「唤起桌面窗口 + 轮询状态」两种 UX；且**另一会话已实证过**：证据在 `docs/evidence/platforms-qrcode-dialog.png`、`platforms-need-login.png`、`platforms-publish-integration.png`，含真实 MCP 探测「已登录 momo」。我那次没验成，只是因为当时 MCP 已停 —— **不要把「此刻我验不到」写成「功能没实现」** |
| A8 | 英文传播展示（§5.3） | 语言分组 |
| A9 | **配置中心可视化** | ✅ **已完成**（见 §5.10）：`ModelApiPanel.vue` + `/api/config` 三端点 + 探针，实测通过 |

### 5.9 ops 与运行态（已就绪，只加两条）

- 现有：`start_all.sh` / `stop_all.sh`（幂等）、`sync_upstream.sh`（上游复现）、`shot/live_check.mjs`（前端真渲染核验）、`shot/shot.mjs`（HTML → PNG）。
- 新增（M3）：定时收集（cron 触发的 run，只收集 + 生成，**不自动发布**）。

### 5.10 配置中心与「模型与 API」面板（**已实现并实测**）

**为什么做**：改 LLM 地址/模型/密钥原先只能手改组件根 `.env` 再重启；而且 `LLM_MAX_TOKENS` 名义上是配置、**实际 4 个调用点全写死** → 统一配置管不到真实行为。

**后端**（`apps/papercast-server/app/config_api.py`，APIRouter 挂 `/api/config`）：

| 端点 | 作用 |
| --- | --- |
| `GET /api/config` | 21 个可配项 + 当前值 + **值来自哪里**（default / .env / environment / dsh-credential）；密钥只回 `sk-****PUYh` |
| `PATCH /api/config` | 白名单写入 `.env`（原子替换 + chmod 600），随后**热替换 Settings 单例**，不必重启；密钥留空 = 不修改 |
| `POST /api/config/reload` | 手工改过 `.env` 后免重启生效 |
| `POST /api/config/test` | 连通性探针：真发一次最小请求，回显模型回话与耗时 |

**前端**（`src/components/ModelApiPanel.vue`，挂在「引擎与环境」页顶部）：按 group 渲染表单；密钥用 `type=password` 且**留空即不修改**；每项标注值来源；只读项单列；保存后回显改了哪些键；「测试连接」一键探针。

**实测（2026-09-19）**：GET 200（21 项，打码与来源识别均正确）；PATCH 写入→删除往返正常且测试残留已清理；探针 `ok:true, ms:2443, reply:"OK"`；面板 4 组 / 14 可配项 / 7 只读项、控制台 0 错误。

**顺带修掉两个真问题**：

1. **卡死的机制找到了**：`llm.py` 在「空内容 + `finish_reason=length`」时会**加倍预算重试**（最多 3 次），每次上限 `LLM_TIMEOUT_SEC=600s` → 最坏近 30 分钟，正好解释我看到的 38 分钟无进展。**这个旋钮现在就在面板里可调**。
2. **探针第一版是错的**：`max_tokens=16` 被推理模型的思维链吃满、返回空内容（`LLM_EMPTY / finish_reason=length`）。已改 1024 + 允许一次加倍重试 —— **本模型的预算要按「思维链 + 正文」一起估**。

**新增配置项**：`LLM_MAX_TOKENS_CAP`（硬上限，0 = 不限，默认不改变既有行为）；`.env.example` 同时补齐了原先缺失的 6 个键。

---

## 6. 接口契约（冻结清单）

### 6.1 对象模型（两端一致，改动必须同步）

```text
PaperRun { id, createdAt, title, source, status, stages[], config, digest?, articles? }
Stage    { id, label, engine, status, progress, startedAt, endedAt, logs[], artifacts[], gate?, checks? }
Artifact { id, stageId, kind, label, path, url }        // url 形如 /artifacts/<runId>/<rel>
StageGate{ id, label, detail, options[{id,label}], resolved? }
Check    { label, state: pass|warn|fail, detail }
```

- 阶段：`intake → understand → article → poster → video → publish`（**可 skipped，不可删除**）
- 状态：`pending | running | waiting(gate) | done | failed | skipped`
- 闸门：`understand`（理解层确认）、`publish`（投递前确认，选项 `continue | draft | skip`）

### 6.2 REST（与本方案相关）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/runs` | `{source, config}` → PaperRun |
| GET | `/api/runs` · `/api/runs/{id}` | 列表 / 详情 |
| POST | `/api/runs/{id}/cancel` | 取消 |
| POST | `/api/runs/{id}/stages/{sid}/gate` | `{optionId, note?}` 放行 |
| GET | `/api/runs/{id}/events` | SSE（心跳 15s；未接时轮询降级） |
| POST | `/api/uploads` | 上传 PDF / LaTeX zip → `{uploadId, …}` |
| GET | `/artifacts/{runId}/{rel}` | 产物静态服务（已做目录穿越防护） |
| GET | `/api/env` · `/api/health` | 真实环境探测 / 存活 |
| GET/POST | `/api/platforms…` | 渠道列表 / 详情 / 登录二维码 / 导出 / 投递 / 退出 |
| GET/PATCH | ⎵/api/config⎵ | 配置中心：回显（密钥打码）/ 白名单写入并热生效 |
| POST | ⎵/api/config/test⎵ · ⎵/api/config/reload⎵ | 连通性探针 / 免重启重载 |

### 6.3 本轮新增或变更（两端同时改）

| 变更 | 内容 |
| --- | --- |
| 变体新增 | `article.variants` 增加 `en-x-thread`、`en-linkedin`；`ArticleVariant` 增加 `lang: zh \| en` 便于 UI 分组 |
| 产物命名 | `article/en-x-thread.md`、`article/en-linkedin.md`；`video/` 下**禁用非 ASCII 目录名** |
| 回执 | `publish/<channel>_receipt.json`：`{ channel, at, ok, url?, id?, error? }` |
| checks 可见性 | `warn` 状态必须在 UI 列出明细（不只是 pass/fail 两色） |

---

## 7. 状态机与错误语义

```text
pending ──► running ──┬─► done
                      ├─► failed    （写 logs + error.log；保留已产出的部分）
                      └─► skipped   （本轮不做：poster、video 未接入前）
          └─► waiting ──闸门放行──► running
```

- **可恢复**：`run.json` 持久化；进程重启后 `running` → `failed`（不假装还在跑），`waiting` 原样恢复。
- **失败不吞**：阶段失败必须留下可诊断信息（run 目录里已有 `error.log` 机制）。
- **部分产出可用**：intake 成功、understand 失败时，已落盘的 `content.md` / `images/` 仍要能在 UI 预览。

---

## 8. 验证方案

### 8.1 分层命令（改完随手跑）

```bash
./ops/start_all.sh                                   # 起三个服务（幂等）
curl -s http://127.0.0.1:8000/api/health             # 后端存活
curl -s http://127.0.0.1:8000/api/env                # 真实环境探测
cd apps/papercast && npx vue-tsc --noEmit            # 前端类型
node ops/shot/live_check.mjs --shot var/scratch/dashboard-live.png   # 真渲染核验
```

> `live_check.mjs` 里**不要用 networkidle 等待** —— Vite dev server 的 HMR 长连接会让它永远等不到空闲（已踩）。

### 8.2 里程碑验收

见 §4 表格。端到端 demo 脚本（M1 起）：起服务 → 建 run（真 PDF）→ 跑到闸门 → 放行 draft → 打印 export 目录 → 打开 dashboard。

### 8.3 质量门（不许绕过）

1. 文案里每个数字可回溯（`checks` 里无 fail；warn 需人工确认）；
2. 真实投递必须过闸门；
3. `export/` 在任何渠道不可用时都完整。

---

## 9. 开放问题与需要拍板的点

| # | 问题 | 我的建议 |
| --- | --- | --- |
| 1 | 数字不可回溯时怎么处理？ | ✅ **已决（用户决策 1）**：保留 + warn + 人工复核；warn 在 UI 逐条列出，闸门即复核点 |
| 2 | 英文 thread 是否自动投递？ | ✅ **已决（用户决策 2）**：**英文不发** —— 本轮只产出与导出，不接投递通道 |
| 3 | `video/` 下中文目录名是否改 ASCII？ | **改成 ASCII**，避免 URL 编码与跨平台问题 |
| 4 | 小红书 / 知乎登录入口接到前端 | ✅ **已决（用户决策 3）**：两者都要在 dashboard 里可完成登录。小红书＝页内二维码；**知乎＝唤起桌面窗口 + 状态轮询**（风控所限）。待起服务后实测 |
| 5 | ~~知乎 APP_SECRET~~ | ❌ **作废**：知乎走扫码/桌面窗口路径（`zhihu-publisher`），不必等 APP_SECRET |
| 6 | ~~版本控制（`git init` 仍缺）~~ | ✅ **已解决（2026-09-19）**：仓库已 init 并推送（`origin` = `git@github.com:yydhYYDH/PaperCast.git`），大文件已从历史抹除后强推 |
| 7 | `/api/platforms` 与 `/api/channels` 两套端点并存，职责边界未定 | 需后端 owner 拍板。建议 **platforms = 登录与账号状态、channels = 投递扇出与回执**，前端只认一套「发布」入口 |

---

## 10. 变更记录

| 日期 | 谁 | 变更 |
| --- | --- | --- |
| 2026-09-19 | 前端 agent | v1 草案：冻结集成契约（§6）、补英文传播设计（§5.3）、视频契约闭合（§5.6）、前端接线细节（§5.8）、里程碑与验收（§4/§8）；按实测现状标注「已跑通 / 在飞 / 缺口」 |
| 2026-09-19 | 前端 agent | **v1.4**：实现用户要的「统一 API 入口可视化」= §5.10：新增 `app/config_api.py`（GET/PATCH /api/config + test/reload）、`ModelApiPanel.vue`（含密钥打码与留空不改）、`LLM_MAX_TOKENS_CAP`、补齐 `.env.example` 14→21 键；顺带定位卡死机制（加倍预算重试 × 600s 超时）并把它做成可调旋钮 |
| 2026-09-19 | 前端 agent | **v1.3**：按用户要求，从本文件移除「只声明、无适配器、本轮不做」的渠道相关内容，本轮渠道收敛为 3 条（小红书 / 知乎 / B站）；渠道权威规格仍以 `apps/papercast-server/docs/08-channels.md` 为准 |
| 2026-09-19 | 前端 agent | **v1.2**：§5.5 改为「引用 `08-channels.md` 为权威 + 只记对接点」并记录双端点并存问题（§9-7）；§5.7 标注被 `07-poster-and-cards.md` 取代；修正 §3.4/§5.8-A7 中把「我此刻验不到」写成「未验证」的表述（另一会话已有实证与证据） |
| 2026-09-19 | 前端 agent | **v1.1**：落地用户三条决策（数字复核 / 英文不发 / 扫码登录接前端）；**更正 §5.5 渠道契约字段**（初稿的 `loginMode/available/loggedIn` 为臆测，实测为 `kind/login/state/endpoint/needs/capabilities/loginHint`）；新增 §3.4 实测补充（四渠道当前全不可用、知乎不能纯扫码、APP_SECRET 非前置） |
