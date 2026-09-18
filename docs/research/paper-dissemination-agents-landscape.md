# 论文多形态传播 · 6-Agent 流水线 的开源现状（GitHub 调研）

> 调研口径：GitHub API（gh CLI，已登录 yydhYYDH）实时查询 stars / 描述 / 推送时间；数据抓取时点见各条 pushed 字段最大值（2026-09 前后）。
> 目标流水线：解读Agent → 可视化Agent → 中文传播Agent → 英文传播Agent → 视频化Agent → 社区运营Agent

## 一句话结论
截至调研时点，**没有任何一个开源项目把这条 6 段链路完整打通**；但每一段都有可直接复用的成熟积木，
其中 3 个项目与你的设计重叠度最高（paper2anything / paper2x / paper-to-wechat），
而 **英文传播（Twitter/LinkedIn thread）与「选社区+互动」是明确空白**。

## 与整体设计最接近的项目（覆盖 2 个以上阶段）

| 项目 | ★ | 覆盖阶段 | 关键事实 |
|---|---|---|---|
| QuZhan51496/paper2anything | 442 | 可视化 + 中文传播 | Claude Code/Codex skills 包，论文 PDF → slides / poster / 单页 homepage / 小红书图文 / 微信公众号文章；每个子技能独立 SKILL.md，Apache-2.0 |
| pickxiguapi/paper2x | 2 | 解读 + 中文传播 | 架构与你的设想几乎一致：paper2note（中文精读笔记）为唯一论文理解基础 → paper2xhs / paper2zhihu / paper2wechat 复用该笔记；错字级重写而非复读 |
| flyanx/paper-to-wechat | 1 | 解读 + 中文传播 | 论文→公众号自包含 HTML 深度解读 + 封面/标题/简介/朋友圈文案；已并入其 studiohub |
| kangw24/paper2content | 0 | 中文传播 | 论文 PDF→平台文字稿；4 套风格系统（微信×学术、微信×媒体、小红书×学术、小红书×媒体） |
| smilebank7/Paper2Poster4Harness | 1 | 可视化（harness 化） | 把 Paper2Poster 的 AI 后端抽掉，用 Claude Code + AGENTS.md 编排，无需 API key |

## 单阶段最强的可用件

### 阶段1 解读
- kaixindelele/ChatPaper — 19.8k★，论文全文总结 + 专业翻译 + 润色 + 审稿
- binary-husky/gpt_academic — 71.4k★，论文阅读/翻译/润色交互平台（插件化）
- pickxiguapi/paper2x（paper2note）— 中文精读笔记，作为下游所有内容的唯一事实源（这个"单一理解层"设计值得抄）

### 阶段2 可视化
- Paper2Poster/Paper2Poster — 3.9k★，MIT，NeurIPS 2025；PosterAgent 是 top-down、visual-in-the-loop 多智能体：Parser（资产库）→ Planner（文图对齐）→ Painter → Evaluator，输出可编辑 pptx；自带免依赖 skills/ 供 Codex/Claude 调用
- HKUDS/Paper2Slides — 3.8k★，MIT；4 阶段流水线 rag → summary → plan → generate，逐阶段 checkpoint、可 --from-stage 续跑
- OpenDCAI/Paper2Any — 2.8k★，论文/文本/主题 → 可编辑研究配图、技术路线图、PPT（LangGraph）；注意 README 已转向 Nexus Office，paper2any 记为 Legacy Code
- multimodal-art-projection/P2P — 55★，ICLR 2026，paper-to-poster + 细粒度 benchmark（P2PInstruct/P2PEval）
- icip-cas/PPTAgent — 5.0k★，反思式 PPT 生成 agentic 框架（通用，可作渲染后端）

### 阶段3 中文传播（知乎/公众号/小红书）
- 上面 4 个 skills 类项目（paper2anything / paper2x / paper-to-wechat / paper2content）
- JimLiu/baoyu-skills — 26.0k★，小红书图、信息图、漫画、幻灯片、文章插画等 skills 生态，可作风格/素材层
- sanqi-cd/Sanqi-Skills — 小红书图文 + 论文解读 + YouTube 播客笔记（Codex/Claude Code/OpenCode/OpenClaw）

### 阶段4 英文传播（Twitter / LinkedIn thread）—— 空白区
- rachittshah/arxiv-to-linkedin — 0★，docling 抽论文 + Claude agent teams 生成 LinkedIn 帖；无社区认可度
- 以 "twitter thread"、"tweet thread generator"、"arxiv thread bot" 等关键词在 GitHub 检索，**没有可直接使用的成熟项目**
- 只能自建：结构上就是「解读层产物 → 平台风格重写 + 长度/钩子/配图规范」，可与阶段1共享同一份理解产物

### 阶段5 视频化
- showlab/Paper2Video — 2.4k★，MIT，NeurIPS 2025 SEA workshop；PaperTalker 单 agent 集成 slides + 字幕 + 光标定位 + 语音合成 + 数字人渲染，输入 LaTeX 源 + 参考图/音频，pipeline 分 stage 可断点
- Gen-Verse/Paper2Video（Preacher）— 51★，ICCV 2025；top-down 分层规划的多智能体论文→视频摘要系统，多角色可配置
- souzatharsis/podcastfy — 6.6k★，开源 NotebookLM 播客替代，多模态内容→多语言双人对话音频（音频形态的低成本替代）
- 3Blue1Brown/Manim 风格：edwardyen724-g/paper2video（6★）、JoaquinCampo/paper2video（1★）— 端到端 Manim 讲稿+配音，适合"3 分钟脚本+可视化"，但都很早期

### 阶段6 社区运营（发放 + 互动）
- yikart/AiToEarn — 26.0k★，MIT；四大 Agent：Create / Publish / Engage / Monetize，支持 MCP 与 OpenClaw，可在 Claude/Cursor 内直接调用（中文平台覆盖强）
- gitroomhq/postiz-app — 36.0k★，AGPL-3.0；agentic 社媒排期发布，配 postiz-agent CLI（469★）可直连 Claude/OpenClaw
- dreammis/social-auto-upload — 15.0k★，抖音/小红书/视频号/B站/快手/TikTok/YouTube 自动上传
- inovector/mixpost — 3.7k★，自托管 Buffer 替代
- 学术社区（arXiv/OpenReview/HF Papers/AlphaXiv/Reddit r/MachineLearning/HN）**没有专用 agent**，只有零散的 HN/Reddit 分析小项目，需要自建（选择社区 = 规则 + 元数据匹配，互动 = 抓取回复 + 拟稿，人工确认）

## 相关研究原型（可参考架构，而非直接生产可用）
- jmiao24/Paper2Agent — 2.7k★，多智能体把论文转为可交互 AI agent（"论文理解→多产物"的范式参考）
- AutoLab-SAI-SJTU/Paper2Rebuttal — 558★，ACL 2026，多智能体作者回复框架
- AutoLab-SAI-SJTU / aiming-lab/AutoResearchClaw — 14.4k★，idea→论文全自动（上游写作侧）

## 覆盖度速查
| 阶段 | 开源成熟度 | 首选复用 |
|---|---|---|
| 1 解读 | 高 | paper2note / ChatPaper / gpt_academic |
| 2 可视化 | 高 | Paper2Poster、Paper2Slides、Paper2Any |
| 3 中文传播 | 中高（skills 生态） | paper2anything、paper2x、paper-to-wechat |
| 4 英文传播 | 低（空白） | 需自建 |
| 5 视频化 | 中 | showlab/Paper2Video、Preacher、podcastfy |
| 6 社区运营 | 中（通用发布强，学术社区弱） | AiToEarn、Postiz(+postiz-agent)、social-auto-upload |

## 组装建议
1. 编排层用 Claude Code / Codex 的 skills 机制（paper2anything、paper2x 都是这个形态，最省事），或用 CrewAI/LangGraph 显式编排 6 个 agent；
2. 阶段1 只做一次「论文理解」，落一份结构化产物（图注、指标、贡献、局限），全部下游 agent 共享 —— 这是 paper2x 的核心设计，也是你 6 agent 能否一致的关键；
3. 阶段2/5 直接复用 Paper2Poster(skills/) 与 Paper2Video/Paper2Slides，别重造；
4. 阶段6 用 MCP 接 Postiz 或 AiToEarn 完成"发布"，学术社区选择与互动自建 + 人工确认闸门；
5. 差异化机会集中在阶段4（英文 thread/LinkedIn）与阶段6（学术社区选择+互动），以及"全链路一致性与可追溯引用"。

## 检索复现
```bash
gh search repos "paper2poster" --limit 8 --sort stars
gh search repos "paper2slides" --limit 8 --sort stars
gh search repos "论文 解读" --limit 8
gh search repos "paper2" --limit 10 --sort stars
gh api repos/<owner>/<repo>            # stars / license / pushed_at
```

## 附：中文平台运营件（小红书 / 知乎 / 公众号 / B站）

### 小红书（生态最成熟）
- 出图/排版（Agent Skill）：op7418/guizang-social-card-skill 7.1k★ AGPL-3.0（小红书组图 + Live Photo 卡 + 公众号封面对）；HisMax/RedInk 5.5k★（Nano Banana Pro）；freestylefly/xiaohongshu-skills 96★；norsizu/xhs-graphic-generator 19★ MIT（5–18 张卡片）
- 发布/互动：xpzouying/xiaohongshu-mcp 15.8k★ Apache-2.0（MCP：登录/发图文/发视频/搜索/详情+评论/发评论）；white0dew/XiaohongshuSkills 3.4k★ MIT（CDP 自动发布+评论+检索，README 自警风控/封号）；autoclaw-cc/xiaohongshu-mcp-skills 259★；luyike221/xiaohongshu-mcp-python 141★；ToDieOrNot/xiaohongshu-mcp-nodejs 78★
- 采集/选题：NanmiCoder/MediaCrawler 65.1k★（小红书/知乎/B站等笔记+评论）；JoeanAmier/XHS-Downloader 12.7k★；Panniantong/Agent-Reach 82.6k★；whiteguo233/OpenBiliClaw 3.3k★（跨平台内容发现，支持 DSH 插件）

### 知乎（基本空白）
- 发布：wechatsync/Wechatsync 6.3k★（浏览器插件一键同步到知乎/头条/掘金/CSDN，最现实路线）
- MCP：Douyh123/zhihu-mcp 6★、meurz/zhihu-mcp-server 5★（含 zse96 v2 签名）、chemany/zhihu_mcp_server 8★、morrain/zhihuMcpServer 4★、liyxianren/zhihu 10★（skills 封装）——全部 <10★
- 原因：强签名校验 + 登录风控、无官方写接口；生成端不需要专门 agent（Markdown 长文直接写）

### 公众号
- aiworkskills/wechat-article-skills 616★ Apache-2.0（选题→成稿→审稿→微信 HTML 排版→封面配图→发草稿箱，每步停等确认）
- MaydayV/wechat-article-skill 34★（原创文风引擎）；qiye45/wechatDownload 9.4k★（下载，支持 MCP/Skill）；wechat-article/wechat-article-exporter 12.9k★

### B站
- 投稿基础设施：biliup/biliup 5.4k★ MIT（命令行投稿、多P、扫码/短信/cookie 登录、19 平台直播录制）；biliup/biliup-app 1.4k★；biliup/biliup-rs 1.1k★；social-auto-upload 15k★；AiToEarn 26k★
- 运营 MCP：adoresever/bilibili-mcp 101★ MIT（27 工具：登录、搜索、评论/回复(楼中楼)、字幕、弹幕、视频详情、发动态(可定时)、上传视频、多P、图文专栏、分区、热门/热搜/排行、收藏夹、私信、收到的回复/@和点赞）；huccihuang/bilibili-mcp-server 190★；34892002/bilibili-mcp-js 192★；aimoyuhub/bilibili-mcp 19★
- 直播/弹幕互动：xfgryujk/blivedm 1.4k★；xbclub/BilibiliDanmuRobot 90★
- B站 Skill：yhbcode000/paper-share-skills 38★ Apache-2.0（**PDF 论文 → MinerU Markdown → Beamer 幻灯片 → 横竖双配音视频 → B站投稿**，编排技能 paper-to-bilibili，投稿走 biliup，Claude Code/Codex/OMP 通用）；HandsomeNPC/bilibili-skill 0★（SKILL.md + auth/comment_ops/data_ops，未验证）；weilanhanf/easy-bilibili-skill 4★（个人视频知识库）；RookieCuzz/codex-bilibili-skills 2★（字幕→笔记）；xdfdh666/bilibili-dashboard 0★（运营数据看板）
- API 底座：SocialSisterYi/bilibili-API-collect 20.2k★

### 平台成熟度速查
| 平台 | 生成 | 发布自动化 | 互动/评论 | 结论 |
|---|---|---|---|---|
| 小红书 | 强 | 强（15.8k★ MCP） | 强 | 可直接全链路搭 |
| B站 | 中（paper-share-skills） | 强（biliup + MCP） | 中（bilibili-mcp 回评/弹幕） | 投稿最稳，运营 skill 生态新 |
| 公众号 | 强（wechat-article-skills） | 中（发草稿箱，需人工） | 弱 | 生成可用，发布半自动 |
| 知乎 | 中（LLM 即可） | 弱（插件同步） | 弱 | 靠 Wechatsync 半自动 |

