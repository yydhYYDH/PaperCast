# 论文出图 · 小红书/知乎视觉系统的现成仓库调研（2026-09-19）

> 起因：用户反馈「现在生成的 poster 完全不符合 —— 像论文墙报，不像小红书/知乎信息流里的图文卡片」，
> 要求去找现成仓库或小红书/知乎 skill。
> 结论已落地：**没有直接可用的 skill 能被后端流水线加载**，所以按「移植视觉系统进我们自己的渲染器」执行，
> 实现见 `apps/papercast-server/app/modules/poster_theme.py`（自写 CSS/模板，未复制任何 AGPL 代码）。
> 数据口径：`gh api repos/<owner>/<repo>` 实时读取（stars / license / pushed_at），抓取时点 2026-09-19。

## 1. 一个必须先认清的架构事实

我们的 `poster` 阶段是**后端 Python 在流水线里自动跑**的；而 GitHub 上这些"小红书 skill"都是
**给 agent 会话用的 SKILL.md 配方**（要模型、要交互确认、每次结果不确定）。所以只有三条路：

| 路 | 做法 | 代价 |
| --- | --- | --- |
| **A 移植视觉系统（本轮选它）** | 把 skill 的**版式规则/主题**变成我们渲染器的 CSS + 模板 | 确定性、能进 CI、能自动跑；但"好看"的上限取决于我们自己的设计功力 |
| B 装成技能会话里跑 | 像现在的设计技能那样装进 `~/.agents/skills` | 上限高，但每次要模型、进不了流水线、产物不可复现 |
| C 走文生图 | 用模型直接画封面/主视觉 | 需要出图 key（本机 codex CLI 与 DASHSCOPE 都不可用），且卡片上的中文由模型画，**必然出错字** |

## 2. 候选清单（按"能不能用"排序）

### 2.1 直接取代我们的出图（HTML/CSS → 截图，与我们同构）

| 仓库 | ★ | 许可 | 最近推送 | 路线 | 判断 |
| --- | --- | --- | --- | --- | --- |
| `op7418/guizang-social-card-skill` | 7.1k | **AGPL-3.0** | 2026-07-01 | 单文件 HTML → Playwright PNG；电子杂志风 × 瑞士风、28 版式、10 主题 | **最像小红书原生**。已在我们 `reference/upstream`（`cf4b810` = 上游最新）。AGPL → **只能读思路，不能抄代码**（本仓库 MIT 且公开发布） |
| `op7418/guizang-ppt-skill` | 26.5k | AGPL-3.0 | 2026-08-07 | 同作者姊妹项目：横版 deck + social covers | 同一套美学语言，风格参考 |
| `fxyadela/write-then-publish` | 544 | NOASSERTION | 2026-09-18 | Markdown → 小红书图文卡片 / 公众号长文，本地优先 | 许可不明，只能读思路 |
| `manwithshit/xhs-images` | 43 | MIT | 2026-01-19 | 小红书信息图系列 Skill | MIT，**可以抄**；体量小，适合当模板来源 |
| `norsizu/xhs-graphic-generator` | 19 | MIT | 2026-01-23 | 主题/文章 → 5–18 张卡片，HTML+Playwright | 同上 |
| `flyanx/xiaohongshu-card` | 2 | MIT | 2026-09-07 | 文章 → 1080×1440 卡片组，Playwright 校验 | MIT；与我们在用的 `paper-to-wechat` 同作者 |
| `yuling170916/pretty-card-skill` | 6 | MIT | 2026-08-30 | 文字 → 小红书图文卡片（Codex Skill） | MIT，备选 |

### 2.2 论文专用（内容侧，不是视觉侧）

| 仓库 | ★ | 许可 | 路线 | 判断 |
| --- | --- | --- | --- | --- |
| `QuZhan51496/paper2anything` → `paper2xhs` / `paper2poster` | 449 | Apache-2.0 | 手写 HTML + Playwright，MinerU 解析 | **已 clone**。与我们的做法同源，换它不会"变好看"；值得借的是内容策略（选题角度、封面文案） |
| `pickxiguapi/paper2x` → `paper2xhs` / `paper2zhihu` | 2 | Apache-2.0 | paper2note 作唯一理解层 → 各平台改写 | **已 clone**。"单一理解层"的设计我们已经沿用 |

### 2.3 文生图路线（本轮不用）

| 仓库 | ★ | 许可 | 判断 |
| --- | --- | --- | --- |
| `JimLiu/baoyu-skills`（`baoyu-xhs-images` 12 风格/8 版式、`baoyu-infographic`、`baoyu-cover-image`、`baoyu-slide-deck`） | 26k | MIT | 版权最干净、生态最大，但它是**文生图**：要出图后端（本机 codex CLI 不可用、DASHSCOPE 未配），且卡面中文由模型画、会错字。留作路线 C |
| `HisMax/RedInk` | 5.5k | — | Nano Banana Pro 出图，同上受限 |

### 2.4 知乎

**没有"知乎配图/海报"这一类 skill**（知乎侧全是发布器 / MCP / cookie 登录工具：`ZhihuPublisher`、`zhihu-cli`、
`zhihu-mcp*`、`wechat sync` 等，见 `upstream-repos.md` C 组）。知乎的图只能我们自己出 ——
沿用 `zhihu` 预设（1600×1200 横版）。这条是**空白**，不是没找到。

## 3. 本轮为什么这么落地

1. **风格不对 ≠ 换仓库**：候选里与我们同构的几个（paper2xhs / paper2poster）用的也是"手写 HTML + 截图"，
   换过去长相不会变；决定长相的是**视觉系统**，而视觉系统最强的那个（guizang）是 AGPL。
2. **所以我们自己写一套，只借规则**：安全边（72–96px）、封面结构（大标题 + 一个强视觉 + 底部一句要点）、
   栏目序号化（01/02）这些**版式规则**没有版权问题；具体 CSS 与模板全部按我们自己的三条判据重写
   （纸面 / 单一强调色 / 固定外框），配色直接取前端 `src/style.css` 的暖白 —— 顺带让海报与产品界面同语言。
3. **顺手修掉一个真 bug**：换风格时把 `.col > *{min-height:0}` 补上，才让"内容装不下"表现为
   面板报溢出（闸门看得见），而不是被 `.sheet{overflow:hidden}` 静默裁掉 —— 旧版 `zhihu` 画布就是这么
   带着半张被裁掉的图判 pass 的。

## 4. 还没做的（交接）

- **投放侧封面没按渠道挑**：`publish._pick_media` 给所有渠道同一张封面（按文件名排序挑到 `poster-bili-cover.png`），
  所以投到小红书的不是那张 3:4 首图；前端 `apps/papercast/src/data/works.ts` 的小红书封面回退同理。
  两处都在别的轨道正在改的文件里，本轮没动。
- **封面短标题**：`poster_stage` 现在把主标题切前 40 字当封面标题，中文长标题会被拦腰断行；
  应该单独让 LLM 写一句 ≤14 字的短标题。
- **可抄的 MIT 模板**：`manwithshit/xhs-images`、`flyanx/xiaohongshu-card` 等 MIT 仓库**尚未 clone**。
  若之后要扩版式（例如"对比表卡""步骤卡"），先 clone 到 `reference/upstream/` 并在 `upstream-repos.md` 登记。
