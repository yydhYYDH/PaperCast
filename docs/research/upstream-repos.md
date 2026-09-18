# 上游参考仓库清单（`reference/upstream/`）

> 这里全是**别人的代码，只读**。用途是给 PaperCast 的设计找参考实现，不参与构建。
> 规则见 [`../conventions.md`](../conventions.md) 第 7 节：不改上游、不用 submodule、结论写回 `docs/research/`。
> 快照时间：2026-09-19 · 共 24 个 · 合计约 2.5G。删掉后可按下表来源重新克隆。
> 自查：`./ops/sync_upstream.sh --list` 会核对「本地目录数 vs 登记数」是否一致（多一个少一个都会报出来）。

## 复现 / 状态核对

本表**就是复现依据**（不维护第二份清单），脚本按表格的「目录 | 上游链接 | HEAD」三列解析：

```bash
./ops/sync_upstream.sh --list     # 只核对：登记 HEAD vs 本地 HEAD，不动任何文件
./ops/sync_upstream.sh            # 缺失的按登记 commit 取回来（浅克隆 + 固定 commit）
```

- 取的是**登记的那个 commit**，不是上游默认分支的最新提交 —— 上游更新不会让我们的参考实现静默漂移；要升级就改本表 HEAD 再重跑。
- **非破坏性**：已存在的目录只核对、不覆盖、不更新、不删除（防止冲掉并发会话的成果），不一致只报告并以非零码退出。
- 为什么不是 submodule：见 [`../conventions.md`](../conventions.md) §7.4 —— 上游是纯参考资料，不是构建依赖；以 gitlink 嵌进版本库会带来 `grep`/`glob` 跳过内容、未 init 时目录为空、并发 agent 误提交等代价，而它的核心价值（记录「我们改过上游哪个 commit」）对我们用不上。

## A. 论文 → 多形态物料（PaperCast L2 的参考）

| 目录 | 上游 | HEAD | 最后提交 | 体积 | 我们借用什么 |
| --- | --- | --- | --- | --- | --- |
| `Paper2Poster` | [Paper2Poster/Paper2Poster](https://github.com/Paper2Poster/Paper2Poster) | `623d042` | 2026-06-08 | 1.2G | R2 `poster` 阶段：论文→海报的视觉排版与图文对齐 |
| `Paper2Video` | [showlab/Paper2Video](https://github.com/showlab/Paper2Video) | `47beb50` | 2026-03-05 | 65M | R2 `video` 阶段：幻灯片+旁白+TTS 的成片流程 |
| `Paper2Slides` | [HKUDS/Paper2Slides](https://github.com/HKUDS/Paper2Slides) | `0785051` | 2026-05-20 | 40M | Beamer/HTML 幻灯片生成路径 |
| `sustech-slides-template` | [yhbcode000/sustech-slides-template](https://github.com/yhbcode000/sustech-slides-template) | `55147b3` | 2026-08-12 | 8.0M | 中英文 LaTeX Beamer 学术报告模板（`p2b` 幻灯片轨道的排版底座） |
| `Paper2Any` | [OpenDCAI/Paper2Any](https://github.com/OpenDCAI/Paper2Any) | `b538531` | 2026-08-31 | 345M | 一站式「一份论文→多形态」的编排方式 |
| `PPTAgent` | [icip-cas/PPTAgent](https://github.com/icip-cas/PPTAgent) | `2419d30` | 2026-06-28 | 148M | 论文→PPT 的 agent 编排与自评机制 |
| `paper2anything` | [QuZhan51496/paper2anything](https://github.com/QuZhan51496/paper2anything) | `72bf82d` | 2026-07-16 | 79M | `scripts/parse_pdf.py`：轻量 PDF 解析（M1 intake 对照） |
| `paper2x` | [pickxiguapi/paper2x](https://github.com/pickxiguapi/paper2x) | `b3138db` | 2026-07-13 | 524K | `paper2note` / `paper2xhs`：小红书文案的 SKILL 规范（M2 文案对照） |
| `paper2content` | [kangw24/paper2content](https://github.com/kangw24/paper2content) | `2bb9d7e` | 2026-09-15 | 224K | 论文→多平台内容的最新尝试 |

## B. 平台渠道与排版（PaperCast L3 与卡片图的参考）

| 目录 | 上游 | HEAD | 最后提交 | 体积 | 我们借用什么 |
| --- | --- | --- | --- | --- | --- |
| `paper-share-skills` | [yhbcode000/paper-share-skills](https://github.com/yhbcode000/paper-share-skills) | `bd2f48a` | 2026-08-12 | 7.2M | PDF→MinerU md→Beamer→配音视频→B站；`pdf-to-markdown`、`paper-to-beamer` 等 8 个技能 |
| `guizang-social-card-skill` | [op7418/guizang-social-card-skill](https://github.com/op7418/guizang-social-card-skill) | `cf4b810` | 2026-07-02 | 4.5M | 社交卡片的分栏排版与配色（卡片图 HTML 模板参考） |
| `paper-to-wechat` | [flyanx/paper-to-wechat](https://github.com/flyanx/paper-to-wechat) | `0a7ffd8` | 2026-08-12 | 3.3M | 论文→公众号文章的排版与配图 |
| `wechat-article-skills` | [aiworkskills/wechat-article-skills](https://github.com/aiworkskills/wechat-article-skills) | `985bfbe` | 2026-09-17 | 2.6M | 公众号写作技能集（R2 渠道扩展） |

## C. 知乎发布轨道（2026-09-19 由并发会话引入，尚未纳入五层结构）

| 目录 | 上游 | HEAD | 最后提交 | 体积 |
| --- | --- | --- | --- | --- |
| `zhihu-cli` | [KrisTHL181/zhihu-cli](https://github.com/KrisTHL181/zhihu-cli) | `5a8d9bd` | 2026-09-17 | 3.3M |
| `zhihu-automation-skill` | [liuboacean/zhihu-automation-skill](https://github.com/liuboacean/zhihu-automation-skill) | `9aca95d` | 2026-05-21 | 620K |
| `zhihu-mcp-server` | [meurz/zhihu-mcp-server](https://github.com/meurz/zhihu-mcp-server) | `89a8cb3` | 2026-09-12 | 4.3M |
| `zhihu-mcp` | [Douyh123/zhihu-mcp](https://github.com/Douyh123/zhihu-mcp) | `d3b8d3c` | 2026-03-28 | 258M |
| `zhihu-mcp-wingAGI` | [wingAGI/zhihu-mcp](https://github.com/wingAGI/zhihu-mcp) | `05b7ce2` | 2026-03-08 | 396K |
| `zhihuMcpServer` | [morrain/zhihuMcpServer](https://github.com/morrain/zhihuMcpServer) | `bb00efc` | 2025-08-14 | 488K |
| `zhihu_mcp_server` | [chemany/zhihu_mcp_server](https://github.com/chemany/zhihu_mcp_server) | `d554915` | 2025-06-06 | 1.4M |
| `zhihu-publisher` | [delankesita/zhihu-publisher](https://github.com/delankesita/zhihu-publisher) | `b7f38a7` | 2026-03-27 | 352K |
| `zhihu` | [liyxianren/zhihu](https://github.com/liyxianren/zhihu) | `3fbdbda` | 2026-02-11 | 276K |
| `ZhihuPublisher` | [zhihu/ZhihuPublisher](https://github.com/zhihu/ZhihuPublisher) | `97ca422` | 2026-08-11 | 484K |
| `ip-publisher` | [veeicwgy/ip-publisher](https://github.com/veeicwgy/ip-publisher) | `2121445` | 2026-04-23 | 28M |

## D. 出图后端调研（不在 `upstream/` 下，单独克隆）

- `reference/baoyu-research/` ← [JimLiu/baoyu-skills](https://github.com/JimLiu/baoyu-skills)，克隆在 `reference/baoyu-research/repo/`，HEAD `1567581`。
  我们借用：**出图后端选择规则**（运行时自适应：Codex 原生 `imagegen` > Cursor `GenerateImage` > `baoyu-image-gen`）、`codex-imagegen` 方案（用 `codex exec` 驱动 Codex CLI 内置 `image_gen`，复用订阅出图、不需要图像 API key）、21 个 `baoyu-*` 技能（小红书组图 / 封面 / 信息图 / 幻灯片 / 漫画）。
- 比上游更该读的是**我们自己的结论**：`reference/baoyu-research/docs/{image-generation.md, image-generation-tools.md, codex-imagegen-backend.md}`。
- 该目录被 `.gitignore` 单独排除，且**不在 `sync_upstream.sh` 的同步范围**（它是调研包，不是只读参考仓库）。

## C 组用途速查（按各仓库 README 实测摘录）

| 目录 | 一句话 |
| --- | --- |
| `ZhihuPublisher` | 知乎**官方**发布 skill：validate→preview→publish；`apps/zhihu-publisher/scripts/publish.py` 已按它的协议与 `X-Sign` 签名实现 |
| `zhihu-cli` | 终端操作知乎（发布 / 浏览） |
| `zhihu-automation-skill` | 浏览器操作知乎：发文章 / 写想法 / 回答问题 / 看热榜 |
| `zhihu-publisher` | 一键发布文章到知乎专栏 |
| `zhihu-mcp-wingAGI` | 最小知乎 MCP 服务 |
| `zhihu-mcp` | 知乎 MCP 服务（258M，含浏览器依赖） |
| `zhihu-mcp-server` | 基于 zhihu-plus-plus 的 MCP 服务器 |
| `zhihuMcpServer` | Puppeteer MCP：抓网页转 markdown（通用抓取，非知乎专有） |
| `zhihu_mcp_server` | 简化架构的知乎发布 HTTP API（与小红书 / 头条同构） |
| `zhihu` | 知乎自动发布 OpenClaw Skills 封装 |
| `ip-publisher` | IP Publisher（README 首屏是徽章，用途待知乎轨道补充登记） |

## 许可与合规（抄代码前必读）

| 许可 | 仓库 |
| --- | --- |
| MIT | `Paper2Poster`、`Paper2Slides`、`Paper2Video`、`PPTAgent`、`zhihu-cli`、`zhihu-automation-skill`、`zhihu-publisher`、`ip-publisher` |
| Apache-2.0 | `paper2x`、`paper2anything`、`Paper2Any`、`paper-share-skills`、`wechat-article-skills`、`sustech-slides-template`、`zhihu-mcp-wingAGI` |
| **AGPL-3.0** | `guizang-social-card-skill` —— ⚠️ 复制其代码会传染到整个分发物，动手前先评估 |
| 未见 LICENSE 文件 | `ZhihuPublisher`、`paper-to-wechat`、`paper2content`、`zhihu-mcp`、`zhihu`、`zhihuMcpServer`、`zhihu_mcp_server`、`zhihu-mcp-server` —— 按默认版权「保留所有权利」对待，**只能读，不要抄进 `apps/`** |

> 特别注意：`paper2content`（4 套风格操作系统，前端文章 4 变体就来自它）和 `paper-to-wechat` 我们**真在用其结论**，但这两个仓库都没有 LICENSE 文件 —— 所以边界是「读思路、自己实现」，不能复制代码。

## 注意

- **许可证**：逐仓库清单见上面「许可与合规」一节（含 AGPL 与无 LICENSE 的名单）。
- **不要在这里改代码**。需要改的上游（如 `xiaohongshu-mcp`）已经复制成 `apps/` 下的组件，补丁留档在 `docs/patches/`。
- **重新克隆**：用 `./ops/sync_upstream.sh`（以本表为依据，覆盖全部登记项）。`ops/skillsearch/clone.sh` 是早期一次性脚本、只覆盖前 11 个，已不代表现状。
- **新增克隆**：`git clone --depth 1` 到 `reference/upstream/<name>/`，然后**必须在本表登记一行**（登记 = 来源 / HEAD / 日期 / 借用点）；只克隆不登记视为违规。
