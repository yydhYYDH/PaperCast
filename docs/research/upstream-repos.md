# 上游参考仓库清单（`reference/upstream/`）

> 这里全是**别人的代码，只读**。用途是给 PaperCast 的设计找参考实现，不参与构建。
> 规则见 [`../conventions.md`](../conventions.md) 第 7 节：不改上游、不用 submodule、结论写回 `docs/research/`。
> 快照时间：2026-09-19 · 共 23 个 · 合计约 2.5G。删掉后可按下表来源重新克隆。

## A. 论文 → 多形态物料（PaperCast L2 的参考）

| 目录 | 上游 | HEAD | 最后提交 | 体积 | 我们借用什么 |
| --- | --- | --- | --- | --- | --- |
| `Paper2Poster` | [Paper2Poster/Paper2Poster](https://github.com/Paper2Poster/Paper2Poster) | `623d042` | 2026-06-08 | 1.2G | R2 `poster` 阶段：论文→海报的视觉排版与图文对齐 |
| `Paper2Video` | [showlab/Paper2Video](https://github.com/showlab/Paper2Video) | `47beb50` | 2026-03-05 | 65M | R2 `video` 阶段：幻灯片+旁白+TTS 的成片流程 |
| `Paper2Slides` | [HKUDS/Paper2Slides](https://github.com/HKUDS/Paper2Slides) | `0785051` | 2026-05-20 | 40M | Beamer/HTML 幻灯片生成路径 |
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

## 注意

- **许可证**：多数仓库带 `LICENSE`（Apache-2.0/dev 类）；`ZhihuPublisher`、`paper-to-wechat`、`paper2content`、`zhihu-mcp-server`、`zhihu-mcp`、`zhihu`、`zhihuMcpServer` 未见 `LICENSE` 文件，**要抄代码前先确认授权**。
- **不要在这里改代码**。需要改的上游（如 `xiaohongshu-mcp`）已经复制成 `apps/` 下的组件，补丁留档在 `docs/patches/`。
- 重新克隆：`ops/skillsearch/clone.sh` 是早期的一次性脚本（只覆盖 11 个），新增克隆请手工 `git clone --depth 1` 到 `reference/upstream/<name>/` 并更新本表。
