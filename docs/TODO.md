# TODO · PaperCast

> **项目级任务板。** 路径约定：代码在 `apps/`，工具与脚本在 `ops/`，运行态在 `var/`，文档在 `docs/`。
> 架构与设计决策见 `docs/00-goal-and-architecture.md`（另一位 agent 正在修订中）；上游仓库清单与复现见 `docs/research/upstream-repos.md`。
>
> **维护约定**：只改自己负责那一组的「状态」和「备注」列，不要在别人的任务上打分或改范围；改完在文末「变更记录」追加一行（日期 + 谁 + 改了什么）。
>
> 状态：⬜ 待开始 · 🟡 进行中 · ✅ 已完成 · ⛔ 阻塞 · ❌ 本轮不做
> 优先级：P0 = 决定本轮能否闭环 · P1 = 本轮应交 · P2 = 有余力再做

---

## 0. 本轮目标（R1）

**一句话：把「一份真论文 → 一整套可分发物料 → 真实投递到内容平台」端到端跑通，全过程在 dashboard 里可见、可控、可追溯。**

**本轮已定的三条决策**（用户 09-19 定，不要再讨论）

1. **视频由另一位 agent 负责** —— `video` 阶段不再是「本轮不做」，而是「外部交付，按下述契约接入」（见 D 组）
2. **远端部署暂不接入** —— 只要求本机闭环；「重计算在远端、发布在本地」推迟到 R2
3. **英文传播要做** —— 从 R2 提回本轮（见 E 组）

---

## 1. 现状快照（2026-09-19）

### 已确认可用（有实证，不要重做）

| 部件 | 状态 | 证据 |
| --- | --- | --- |
| 后端 M1/M2/M3 | ✅ 端到端验证通过 | `apps/papercast-server/docs/06-verification.md`：run `run_224e72b5a672` status=done，**全部 checks 通过**。intake 11.4s / 68k 字符 / 12 张图 / 23 章节；understand 4 条贡献 + 11 条证据（全可回溯）+ 8770 字精读；article 773 字正文 + 12 标签 + **6 张 1080×1440 卡片** |
| 前端 × 真后端 | 🟡 已能通信，细节未对齐 | `var/logs/backend.log` 里有 **103 次** `GET /api/runs` 轮询；但 5 处缺口见 A 组 |
| ops 启停 | ✅ | `ops/start_all.sh` / `stop_all.sh`：backend 带 `var/runs`+`var/uploads`、frontend 带 `VITE_API_BASE`、mcp 清代理变量 |
| 小红书发布 | 🟡 仅 draft 验证 | 同上验证记录：`publish` 走 draft，**素材就绪但未真实投递** |
| 知乎 OpenAPI | 🟡 签名与端点已通 | `zhihu-official/README.md`：假凭证返回 401、签名被正确解析；**真实发布未执行** |
| 参考仓库 | ✅ | `reference/upstream/` 15 个仓库（新增 zhihu / ZhihuPublisher / ip-publisher / PPTAgent 等） |
| 小红书 MCP 本地补丁 | ✅ | `docs/patches/xhs-mcp-local-2026-09-19/`（auth.go + 6 处改动 + diff 归档） |

### 当前服务状态

三个服务**当前都在跑**（`8000` / `5178` / `18060` 均在监听，2026-09-19 复核）。启停用 `./ops/start_all.sh` / `./ops/stop_all.sh`（幂等，端口占用会跳过）。

---

## 2. 任务板

### A 组 · 前端 dashboard（负责：前端 agent）

| ID | 任务 | P | 现状 / 验收 | 状态 |
| --- | --- | --- | --- | --- |
| A1 | **PDF 入口改真上传**：`POST /api/uploads` 拿 `uploadId` 作为 `source.value` | P0 | 现在 `IntakePanel.vue` 只把文件名当 value（`value: file.value.name`），真后端会解析失败。验收：拖入 `example-papers/deeprare.pdf` 能跑出 intake 产物 | ⬜ |
| A2 | **VideoViewer 旁白路径去硬编码** | P0 | `components/viewers/VideoViewer.vue:18` 写死 `fetch('/samples/video/narration.json')`。改为从 `video` 阶段产物取 `narration.json`，`video.url` 交给播放器。**依赖 D1** | ⬜ |
| A3 | 接 `GET /api/env` 替换写死数据 | P1 | `src/data/env.ts` 的 `ENV_DEPS`/`ENGINE_ROWS` 是字面量；后端已提供真实探测结果 | ⬜ |
| A4 | 接 SSE `/api/runs/:id/events` | P2 | `api/http.ts` 目前只有 5 个方法（listRuns/createRun/getRun/cancelRun/resolveGate），轮询可用即降级路径已在；SSE 为增强 | ⬜ |
| A5 | **修正与真实实现不符的文案** | P1 | `IntakePanel.vue` 仍写「走 MinerU 解析」「MinerU 云端模式除外」，但后端已改用 **PyMuPDF**（无 GPU）。文案错误会误导演示 | ⬜ |
| A6 | `skipped` 语义修正 | P1 | `StageStatus` 已含 `skipped` 且有「跳过」标签，但预览器在无产物时显示「尚未产出」，语义不准。改为「本轮跳过 · 原因」 | ⬜ |
| A7 | 小红书二维码登录展示 | P2 | 登录失效时前端直接展示 `/api/v1/login/qrcode` 的二维码，不必下命令行 | ⬜ |
| A8 | 英文传播展示 | P1 | 形态取决于 E1；若走 article 变体则扩展现有 tab 机制 | ⬜ |

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
| C1 | **渠道抽象**：小红书(MCP) / 知乎(OpenAPI) / B站 收敛为统一 channel adapter | P1 | 否则前端要为每个渠道各写一套 UI；这是 L3 发布层的核心设计 | ⬜ |
| C2 | 知乎真实发布 | P0 | ⛔ **阻塞于 `ZHIHU_OPENAPI_APP_SECRET`，需你本人到开放平台申请** | ⛔ |
| C3 | 知乎 `qr_login.py` 验证 | P2 | 文件已在 `zhihu-official/`，未验证 | ⬜ |
| C4 | B站通道选型 | P2 | 上游已有 `reference/upstream/paper-share-skills/paper-bilibili-uploader/`，决定复用还是自研 | ⬜ |
| C5 | 凭证统一管理 | P1 | 统一放 `.env`/`~/.config`，**绝不进版本库**（注意根目录目前还不是 git 仓库，见 F2） | ⬜ |

### D 组 · 视频（负责：视频 agent，已指派）

| ID | 任务 | P | 说明 | 状态 |
| --- | --- | --- | --- | --- |
| D1 | **video 阶段产出并落盘** | P0 | 契约：产物在 `var/runs/<runId>/video/`（`narration.json` + `*.mp4`）；`narration.json` 形状 `{title, totalSec, slides:[{index,title,bullets[],narration,durationSec}]}`；`stage.artifacts` 登记 `{kind:'video', url:'/artifacts/<runId>/video/<file>.mp4', meta:{durationSec,w,h}}`；`status='done'` | 🟡 |
| D2 | 与前端联调 | — | 后端契约就绪后由 A2 对接；届时删掉示例旁白依赖 | ⬜ |

> **给视频 agent 的提醒**：`VideoViewer` 的时间轴映射已做**等比对齐**（示例片长 350s、旁白 totalSec 300s 时自动缩放），所以真实视频与 `totalSec` 不一致不会错位，但**必须先让前端能读到 `narration.json`**（即 A2），否则视频接进来旁白仍是示例数据。

### E 组 · 英文传播（本轮要做）

| ID | 任务 | P | 说明 | 状态 |
| --- | --- | --- | --- | --- |
| E1 | **形态决策**：并入 `article` 作英文变体 vs 新增独立阶段 | P0 | 建议：**先并入 `article`**（成本低、复用现有 tab、不动六阶段契约）；若演示需要独立阶段再升级（两端都要改契约） | ❓ |
| E2 | 生成 X / LinkedIn thread（从 `digest.json` 派生） | P0 | 与中文文案同源，遵守单一事实源与数字可追溯 | ⬜ |
| E3 | 投递方式 | P1 | 建议**先导出、人工发**（与「发布有闸门、凭证不出本机」一致）；自动化可参考上游 `baoyu-post-to-x`(CDP) | ⬜ |
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
| 知乎 `APP_SECRET` | ⛔ **需你本人操作** | 到知乎开放平台申请后填入 `zhihu-official/.env` |
| 无版本控制（F2） | 高风险 | 尽快 init + 提交；当前任何误删都不可恢复 |
| 文档与实现漂移 | 中 | 已发现两处：前端仍写 MinerU（A5）、`05-deployment` 描述远端（本轮不做） |
| 平台风控 / 账号安全 | 中 | 发布保留人工闸门；`export/` 兜底；凭证不进库 |
| `narration.json` 契约若被视频侧改形 | 中 | 前端 A2 与 D1 必须按同一形状实现，改动需同步 TODO |

---

## 5. 变更记录

| 日期 | 谁 | 变更 |
| --- | --- | --- |
| 2026-09-19 | 前端 agent | 建立本任务板；按用户决策写入三条（视频外部负责 / 远端不接入 / 英文传播要做）；补现状快照与 A–G 分组 |
| 2026-09-19 | 前端 agent | 任务板移至 `docs/TODO.md`（根目录只允许三个文件）；F1/G1 完成、F2 收窄为「只差 git init」、新增 F6 上游复现机制；补登 `sustech-slides-template`（第 24 个上游） |
