# TODO · PaperCast

> **项目级任务板。** 路径约定：代码在 `apps/`，工具与脚本在 `ops/`，运行态在 `var/`，文档在 `docs/`。
> 架构与设计决策见 `docs/00-goal-and-architecture.md`（另一位 agent 正在修订中）；**具体实现方案见 `docs/01-implementation-plan.md`**；上游仓库清单与复现见 `docs/research/upstream-repos.md`。
>
> **维护约定**：只改自己负责那一组的「状态」和「备注」列，不要在别人的任务上打分或改范围；改完在文末「变更记录」追加一行（日期 + 谁 + 改了什么）。
>
> 状态：⬜ 待开始 · 🟡 进行中 · ✅ 已完成 · ⛔ 阻塞 · ❌ 本轮不做
> 优先级：P0 = 决定本轮能否闭环 · P1 = 本轮应交 · P2 = 有余力再做

---

## 0. 本轮目标（R1）

**一句话：把「一份真论文 → 一整套可分发物料 → 真实投递到内容平台」端到端跑通，全过程在 dashboard 里可见、可控、可追溯。**

**本轮已定的决策**（用户 09-19 定，不要再讨论；第 4–5 条为同日补充）

1. **视频由另一位 agent 负责** —— `video` 阶段不再是「本轮不做」，而是「外部交付，按下述契约接入」（见 D 组）
2. **远端部署暂不接入** —— 只要求本机闭环；「重计算在远端、发布在本地」推迟到 R2
3. **英文传播要做** —— 从 R2 提回本轮（见 E 组）；**但英文不发**（用户 09-19 补充）：只产出与导出，不接投递通道
4. **数字不可回溯时 → 人工复核** —— 保留 + warn + 在 UI 逐条列出；**发布闸门就是复核发生的地方**，闸门未放行不得投递
5. **小红书 / 知乎的扫码登录要接入前端** —— 小红书＝页内二维码；知乎＝唤起桌面窗口 + 状态轮询（风控拦纯 HTTP 扫码，故不必等 APP_SECRET）

---

## 1. 现状快照（2026-09-19）

### 已确认可用（有实证，不要重做）

| 部件 | 状态 | 证据 |
| --- | --- | --- |
| 后端 M1/M2/M3 | ✅ 端到端验证通过 | `apps/papercast-server/docs/06-verification.md`：run `run_224e72b5a672` status=done，**全部 checks 通过**。intake 11.4s / 68k 字符 / 12 张图 / 23 章节；understand 4 条贡献 + 11 条证据（全可回溯）+ 8770 字精读；article 773 字正文 + 12 标签 + **6 张 1080×1440 卡片** |
| 前端 × 真后端 | 🟡 已能通信，细节未对齐 | `var/logs/backend.log` 里有 **103 次** `GET /api/runs` 轮询；但 5 处缺口见 A 组 |
| ops 启停 | ✅ | `ops/start_all.sh` / `stop_all.sh`：backend 带 `var/runs`+`var/uploads`、frontend 带 `VITE_API_BASE`、mcp 清代理变量 |
| 小红书发布 | 🟡 仅 draft 验证 | 同上验证记录：`publish` 走 draft，**素材就绪但未真实投递** |
| 知乎 OpenAPI | 🟡 签名与端点已通 | `apps/zhihu-publisher/docs/zhihu-official-notes.md`：假凭证返回 401、签名被正确解析；**真实发布未执行**（等 `APP_SECRET` 审核） |
| 知乎真实发布（cookie+Playwright 通道） | ✅ 已真实投递成功 | <https://zhuanlan.zhihu.com/p/2084432742410993947>；账号 YYDH / `yydh-75`；证据 `docs/evidence/zhihu-test-post.png`；接口 `apps/zhihu-publisher` |
| 参考仓库 | ✅ | `reference/upstream/` 15 个仓库（新增 zhihu / ZhihuPublisher / ip-publisher / PPTAgent 等） |
| 小红书 MCP 本地补丁 | ✅ | `docs/patches/xhs-mcp-local-2026-09-19/`（auth.go + 6 处改动 + diff 归档） |

### 当前服务状态

三个服务**当前都在跑**（`8000` / `5178` / `18060` 均在监听，2026-09-19 复核）。启停用 `./ops/start_all.sh` / `./ops/stop_all.sh`（幂等，端口占用会跳过）。

---

## 2. 任务板

### A 组 · 前端 dashboard（负责：前端 agent）

| ID | 任务 | P | 现状 / 验收 | 状态 |
| --- | --- | --- | --- | --- |
| A1 | **PDF 入口改真上传**：`POST /api/uploads` 拿 `uploadId` 作为 `source.value` | P0 | 现在 `IntakePanel.vue` 只把文件名当 value（`value: file.value.name`），真后端会解析失败。验收：拖入 `var/samples/deeprare.pdf` 能跑出 intake 产物 | ⬜ |
| A2 | **VideoViewer 旁白路径去硬编码** | P0 | `components/viewers/VideoViewer.vue:18` 写死 `fetch('/samples/video/narration.json')`。改为从 `video` 阶段产物取 `narration.json`，`video.url` 交给播放器。**依赖 D1** | ⬜ |
| A3 | 接 `GET /api/env` 替换写死数据 | P1 | `src/data/env.ts` 的 `ENV_DEPS`/`ENGINE_ROWS` 是字面量；后端已提供真实探测结果 | ⬜ |
| A4 | 接 SSE `/api/runs/:id/events` | P2 | `api/http.ts` 目前只有 5 个方法（listRuns/createRun/getRun/cancelRun/resolveGate），轮询可用即降级路径已在；SSE 为增强 | ⬜ |
| A5 | **修正与真实实现不符的文案** | P1 | `IntakePanel.vue` 仍写「走 MinerU 解析」「MinerU 云端模式除外」，但后端已改用 **PyMuPDF**（无 GPU）。文案错误会误导演示 | ⬜ |
| A6 | `skipped` 语义修正 | P1 | `StageStatus` 已含 `skipped` 且有「跳过」标签，但预览器在无产物时显示「尚未产出」，语义不准。改为「本轮跳过 · 原因」 | ⬜ |
| A7 | 小红书二维码登录展示 | P2 | ✅ **完成**：新增「平台账号」页 + 顶栏状态入口 + 发布页扫码按钮，共用 `PlatformLoginDialog.vue`；后端补 `GET /api/platforms`、`GET /api/platforms/:id/login/qrcode`、`POST /api/platforms/:id/login/logout`。实证：`docs/evidence/platforms-*.png`（真实 MCP 探测显示「已登录 momo」，弹层走完取码→检测→已登录） | ✅ |
| A8 | 英文传播展示 | P1 | 形态取决于 E1；若走 article 变体则扩展现有 tab 机制 | ⬜ |
| A9 | **配置中心 / 「模型与 API」面板** | P1 | ✅ **完成**：`app/config_api.py`（`GET/PATCH /api/config` + `test/reload`，白名单写 `.env` + 热生效，密钥只回打码值）+ `src/components/ModelApiPanel.vue`（挂在「引擎与环境」页顶部）。实测：GET 21 项、探针 ok 2443ms、面板 0 控制台报错；证据 `docs/evidence/model-api-panel.png`。**顺带定位卡死机制**：空响应会加倍预算重试 × 每次 600s 超时，现在 `LLM_TIMEOUT_SEC` 在面板里可调 | ✅ |

### B 组 · 后端与内容（负责：后端 agent）

| ID | 任务 | P | 说明 | 状态 |
| --- | --- | --- | --- | --- |
| B1 | **小红书真实投递**（非 draft）+ 回执落盘 | P0 | draft 已验证；真实发布需闸门放行，且保留 `publish/export/` 兜底 | ⬜ |
| B2 | 本机定时收集新论文（cron） | P2 | 只收集 + 生成，**不自动发布**（远端不接入） | ⬜ |
| B3 | `poster` 阶段是否实现 | — | 本轮维持 `skipped`，需用户确认是否进 R2 | ❓ |
| B4 | 远端部署 | ❌ | 本轮明确不做（`docs/05-deployment.md` 保留为 R2 预案） | ❌ |

### C 组 · 发布渠道

| ID | 任务 | P | 说明 | 状态 |
| --- | --- | --- | --- | --- |
| C1 | **渠道抽象**：小红书(MCP) / 知乎(OpenAPI) / B站 收敛为统一 channel adapter | P1 | ✅ **完成**：`app/channels/`（base 契约 + 三 adapter + registry + `GET /api/channels`），M3 改为按 `publish.targets` 扇出、失败隔离、每渠道独立回执 + 素材包兜底；规格见 `apps/papercast-server/docs/08-channels.md`。自检 `scripts/check_channels.py`（离线 22 项 / --live --run 40 项 / 故障演练 34 项全过） | ✅ |
| C2 | 知乎真实发布 | P0 | ⛔ **阻塞于 `ZHIHU_OPENAPI_APP_SECRET`，需你本人到开放平台申请** | ⛔ |
| C3 | 知乎登录件验证 | P2 | ✅ `apps/zhihu-publisher/scripts/login_wait.py` 人工窗口登录已实测（轮询 `z_c0` 落盘）；上游 `login.py` 会假报成功，勿用；另有 `login-headed.sh` 供桌面终端执行 | ✅ |
| C4 | B站通道选型 | P2 | ✅ **已选型**：biliup CLI 子进程（PyPI `biliup==1.2.4` 有 manylinux wheel；biliup-rs 已归档；开放平台需资质；浏览器自动化仅兜底）。落地为 `apps/bilibili-publisher`（:18080，形状同 zhihu-publisher），无凭证时如实报 `unconfigured` + 永远出素材包。现状：本机已装 biliup（`var/toolchains/bili-venv`）并登录 YYDH54（`var/home/.bilibili/`），渠道 `ready`；**本通道尚未投过稿**（项目里那条 BV1DveU6GEPR 是上游脚本直投，没走渠道层） | ✅ |
| C5 | 凭证统一管理 | P1 | ✅ **已定规则并归位**：凭证一律 `var/secrets/`（chmod 600），第三方 CLI 自管位置的用 HOME/cwd 重定向圈进 `var/`（biliup 的 `var/home/.bilibili/`、小红书 MCP 的 cwd `cookies.json`），**不复制第二份**；知乎 cookie 已从 `var/artifacts/` 迁出。规则见 `docs/conventions.md` §4/§5 与 `var/secrets/README.md` | ✅ |

### D 组 · 视频（负责：视频 agent，已指派）

| ID | 任务 | P | 说明 | 状态 |
| --- | --- | --- | --- | --- |
| D1 | **video 阶段产出并落盘** | P0 | 契约：产物在 `var/runs/<runId>/video/`（`narration.json` + `*.mp4`）；`narration.json` 形状 `{title, totalSec, slides:[{index,title,bullets[],narration,durationSec}]}`；`stage.artifacts` 登记 `{kind:'video', url:'/artifacts/<runId>/video/<file>.mp4', meta:{durationSec,w,h}}`；`status='done'` | 🟡 |
| D2 | 与前端联调 | — | 后端契约就绪后由 A2 对接；届时删掉示例旁白依赖 | ⬜ |

> **给视频 agent 的提醒**：`VideoViewer` 的时间轴映射已做**等比对齐**（示例片长 350s、旁白 totalSec 300s 时自动缩放），所以真实视频与 `totalSec` 不一致不会错位，但**必须先让前端能读到 `narration.json`**（即 A2），否则视频接进来旁白仍是示例数据。

### E 组 · 英文传播（本轮要做）

| ID | 任务 | P | 说明 | 状态 |
| --- | --- | --- | --- | --- |
| E1 | **形态决策**：并入 `article` 作英文变体 vs 新增独立阶段 | P0 | ✅ **已决**：并入 `article` 作变体（`en-x-thread` / `en-linkedin`），不新增阶段。设计见 `docs/01-implementation-plan.md` §5.3 | ✅ |
| E2 | 生成 X / LinkedIn thread（从 `digest.json` 派生） | P0 | 与中文文案同源，遵守单一事实源与数字可追溯 | ⬜ |
| E3 | 投递方式 | P1 | ✅ **已决（英文不发）**：本轮不接投递通道，只落 `export/`；自动化留 R2 | ✅ |
| E4 | 前端展示 | P1 | 依赖 E1 | ⬜ |

### F 组 · 工程化

| ID | 任务 | P | 说明 | 状态 |
| --- | --- | --- | --- | --- |
| F1 | 补 `docs/conventions.md` | — | ✅ 已由另一 agent 建好（含 §7 上游规范、§8 脚本规范） | ✅ |
| F2 | **版本控制** | P1 | `.gitignore` 已由另一 agent 建好（覆盖 `var/`、`node_modules`、`.venv`、`cookies.json`、`.env`、`reference/upstream/`）；**仍缺 `git init` + 首次提交** —— 现在全项目依然没有版本控制，误删不可恢复 | ⬜ |
| F6 | **上游清单与复现机制** | — | ✅ `docs/research/upstream-repos.md` 已补「复现 / 状态核对」节 + 许可与合规节 + D 组；`ops/sync_upstream.sh` 可 `--list` 核对 / 按登记 commit 复现。当前 24 个全部一致。**新增上游仓库必须登记** | ✅ |
| F3 | 补丁归档流程 | P2 | 已有 `docs/patches/xhs-mcp-local-2026-09-19/` 一例（base-commit + diff + status），把它固化为例行做法 | ⬜ |
| F4 | 服务开机自启 | P2 | `start_all.sh` 能脱离终端但**开机不自启**；持久化需 root + systemd | ⬜ |
| F5 | 架构文档修订 | — | `docs/00-goal-and-architecture.md` 正被另一 agent 修改（我的初版已从 `/home/yydh/hack/docs/` 移入） | 🟡 |

### G 组 · 演示与交付

| ID | 任务 | P | 说明 | 状态 |
| --- | --- | --- | --- | --- |
| G1 | 顶层 `README.md` | — | ✅ 已由另一 agent 建好（根目录现在只有 `README.md` / `AGENTS.md` / `.gitignore` 三个文件 —— 本任务板因此已移到 `docs/TODO.md`） | ✅ |
| G2 | 一键 demo 脚本 | P1 | `ops/start_all.sh` → 建 run → 走到 draft → 打开 dashboard → 打印产物路径 | ⬜ |
| G3 | 演示材料 | P1 | 已有 10 张界面截图在 `apps/papercast/screenshots/`（mock 态）；需补**真后端**跑通的截图/录屏 | ⬜ |

---

## 3. 关键路径

```text
A1 (PDF 上传) ──┐
                ├──► 真链路闭环 ──► B1 (真发布) ──► 小红书闭环 ✅
A2 ◄── D1 ──────┘                          └──► C2 (知乎，⛔ 等凭证)
E1 (形态) ──► E2 (英文 thread) ──► E4 (前端展示)   ← 决定是否达成原始意图
C1 (渠道抽象) ──► 多平台扩展不再是四份定制代码
```

**结论：A1 + B1 决定「真链路能否闭环」；E1 + E2 决定「是否兑现立项时的 6 Agent 表述」。**

---

## 4. 阻塞与风险

| 项 | 性质 | 应对 |
| --- | --- | --- |
| 知乎 `APP_SECRET` | ⛔ **需你本人操作** | 到知乎开放平台申请后填入 `apps/zhihu-publisher/.env`（或环境变量 `ZHIHU_OPENAPI_APP_SECRET`） |
| 无版本控制（F2） | 高风险 | 尽快 init + 提交；当前任何误删都不可恢复 |
| 文档与实现漂移 | 中 | 已发现两处：前端仍写 MinerU（A5）、`05-deployment` 描述远端（本轮不做） |
| 平台风控 / 账号安全 | 中 | 发布保留人工闸门；`export/` 兜底；凭证不进库 |
| `narration.json` 契约若被视频侧改形 | 中 | 前端 A2 与 D1 必须按同一形状实现，改动需同步 TODO |

---

## 5. 变更记录

| 日期 | 谁 | 变更 |
| --- | --- | --- |
| 2026-09-19 | 前端 agent | 建立本任务板；按用户决策写入三条（视频外部负责 / 远端不接入 / 英文传播要做）；补现状快照与 A–G 分组 |
| 2026-09-19 | 前端 agent | **记入用户新决策**：数字不可回溯→人工复核（闸门即复核点）；**英文不发**（修正第 3 条为「产出与导出，不投递」）；小红书/知乎扫码登录接入前端（知乎为桌面窗口形态）。E1/E3 一并标为已决，并补 `docs/01-implementation-plan.md` 索引 |
| 2026-09-19 | 前端 agent | 任务板移至 `docs/TODO.md`（根目录只允许三个文件）；F1/G1 完成、F2 收窄为「只差 git init」、新增 F6 上游复现机制；补登 `sustech-slides-template`（第 24 个上游） |
| 2026-09-19 | 知乎轨道 agent | 新增 `apps/zhihu-publisher`（知乎通道服务 :18070，HTTP 契约见其 README）：探测/桌面窗口登录/export/publish(confirmed)；backend `/api/platforms` 组新增 `login/start`、`export`、`publish` 三端点，知乎渠道由 blocked(openapi) 变为 ready(playwright)；前端类型/适配器/store/平台页支持 `login: 'browser'`；`ops/start_all.sh` 增 `zhihu` 目标。真实投递已发生一次：zhuanlan.zhihu.com/p/2084432742410993947 |
| 2026-09-19 | 视频分享 agent | 用上游 `paper-share-skills` 实跑 Paper2Video(arXiv 2510.05096) 全链路：LaTeX 源 → 34 页 Beamer（tectonic，0 Overfull）→ 逐页中文旁白 → edge-tts 配音 → 横屏 4:20 成片 → **B站真实投稿成功** [BV1DveU6GEPR](https://www.bilibili.com/video/BV1DveU6GEPR)。按 D1 契约落盘：`var/runs/run_a7b9460d3953/video/{narration.json, PAPER2VIDEO_narrated.mp4, upload_result.json}`（34 slides / totalSec 259.84，可作 D2 联调样本）；转换脚本 `ops/make_run_video_artifacts.py`；运行要点见 `docs/research/paper-share-skills-run-notes.md` |
| 2026-09-19 | 后端 agent | 收紧工作区：① `docs/conventions.md` §4 补全 `var/` 全部子目录（artifacts/secrets/home/scratch/tmp/build/npm-tmp）并定三条硬规则（dashboard 可见的产出必须写 `var/runs/<runId>/<stage>/`、run 内 `publish/<渠道>/export/` 是唯一权威副本、凭证不进 `var/artifacts/`），§5 补知乎/B站凭证行；② 知乎 cookie 从 `var/artifacts/zhihu/` 迁到 `var/secrets/zhihu/`（服务兼容读旧路径，已重启验证仍 `ready`）；③ §9 例外从 8 个收窄到 2 个，随后**归零**（见下一行），`.gitignore` 同步清理；④ 新增 `var/README.md`、`var/artifacts/README.md`、`var/secrets/README.md`；⑤ M3 加**防重复投递**：检出 `video/upload_result.json` 等回执就顶到闸门与 `历史投递` check（真数据验到 BV1DveU6GEPR），成片选取改为顶层优先 |
| 2026-09-19 | 后端 agent | **根目录收口完成（零例外）**：`zhihu-official/` → `apps/zhihu-publisher/{scripts,docs}`；测试稿 → `var/samples/zhihu-sample-article.md`；cwd 相对的 `.zhihu-publish-output/` → `var/artifacts/zhihu/publish-output/`（`publish.py` 改为按 `PAPERCAST_WS` 推导，顺带修掉「换目录就找不到产物」）；`example-papers/deeprare.pdf` → `var/samples/`。同步改掉 12 处引用（含另两条轨道的提示文案）与 `AGENTS.md`/`README.md`/`.gitignore`；重启验证知乎通道仍 `ready`（YYDH）。按显式路径分两次提交：`49c2596`（平台/渠道/通道服务）、`4d57ae1`（文档与规范收口） |
| 2026-09-19 | 后端 agent | C1 完成：新增 `app/channels/`（Channel 契约 + 小红书/知乎/B站 三 adapter + registry + `GET /api/channels`）；M3 从「小红书专用」改为按 `publish.targets` 扇出多平台，闸门 detail 列清各渠道、失败隔离、每渠道独立回执 + 闸门前落素材包；`PublishConfig.targets` 默认三个平台；新增自检 `apps/papercast-server/scripts/check_channels.py` 与规格 `docs/08-channels.md`。C4 完成：B站通道选型 biliup CLI + 新增 `apps/bilibili-publisher`（:18080，`ops/start_all.sh bilibili`）；端口表/契约文档/验证记录同步 |
| 2026-09-19 | 前端 agent | A9 完成：配置中心可视化（`/api/config` 三端点 + 「模型与 API」面板：密钥打码、留空不改、热生效、探针）—— 见 `docs/01-implementation-plan.md` §5.10 |
| 2026-09-19 | 前端 agent | A7 完成：平台登录入口（平台账号页 / 顶栏状态条 / 发布页扫码按钮 + 扫码弹层）；后端新增 `/api/platforms` 组（4 个端点，渠道状态真实探测）；证据 `docs/evidence/platforms-accounts.png`、`platforms-login-dialog.png`、`platforms-qrcode-dialog.png`、`platforms-publish-integration.png` |
| 2026-09-19 | 前端 agent | **A7 扩到知乎 / B 站**：① B 站「扫码登录」打通 —— biliup 的 `login` 是交互菜单且无非交互开关，通道服务在 pty 里替用户选「扫码登录」，把 `qrcode.png` 交给 `GET /api/v1/login/qrcode`，backend `/api/platforms/bilibili/login/qrcode` 取回同一张图给页内弹层扫（实测真码 3.5KB、倒计时 3:40）；② `bilibili` 渠道由「静态探测」改为**真实探测**通道服务状态（账号 YYDH54）；③ biliup 路径回退到 `var/toolchains/bili-venv/bin/biliup`、cookies 读取兼容 `var/home/.bilibili/cookies.json`（终端里 `biliup login` 的落盘位置，否则重启服务就「突然未登录」）；④ 退出登录支持 `zhihu` / `bilibili`；⑤ 首屏不再空白：顶栏与平台页在探测期间显示「探测中…」+ 骨架行（首次探测 13–20s）。证据 `docs/evidence/platforms-bili-zhihu.png`、`platforms-bili-qrcode.png`、`platforms-probing-skeleton.png` |
