# 02 · 6 个 Agent 的覆盖、证据与边界

> 回答一个问题：立项时说的「**6 个 Agent 让一篇论文实现多形态传播**」，现在是不是**每个都在真干活**？
> 版本：R1.5 · 2026-09-19 · 状态：**6 个 Agent 已被一条 run 全面覆盖** —— `run_ec0f0e056f47` 六段全 done（630s），**51 件产物登记在同一条 run.json 里**（其中 42 件带前端 url，逐条 HTTP 200），check 53 pass / 1 fail / 3 run。此前那两条"拼起来才凑齐 6 个"的 run（`run_720e83bdae91` + `run_c5451b582400`）**依然有效**，仍列在 §4.3。验证的层级定义见 §1.2
> 相关文档：[总纲与分层架构](00-goal-and-architecture.md)（§1 的原始意图、§2.2 的 R1 非目标）、[实现方案](01-implementation-plan.md)、
> 组件内 [`apps/papercast-server/docs/07-poster-and-cards.md`](../apps/papercast-server/docs/07-poster-and-cards.md)、[`10-module-video.md`](../apps/papercast-server/docs/10-module-video.md)、[`08-channels.md`](../apps/papercast-server/docs/08-channels.md)

---

## 1. 一句话结论

**总纲 §1 的 6 个 Agent，现在已被**一条 run** 全面覆盖：`run_ec0f0e056f47`。** 它六段全 done（630s），**51 件产物登记在同一条 run.json 里**（42 件带前端 url 且我逐条取回 42/42 HTTP 200），check 53 pass / 1 fail / 3 run —— 6 个 Agent 的产物都在这一条里，逐条实物见 §6.9。

这条跑出来之前，6 个 Agent 的证据要靠**两条 run 拼起来**才凑齐；那两条**依然有效**，本文档各处仍在引用它们（来历见 §4.3）：

| run | 6 段状态 | 登记产物 | 它证明了哪几个 Agent |
| --- | --- | --- | --- |
| `run_ec0f0e056f47`（**单条覆盖 6 个**，§6.9） | 全 done | **51**（42 带 url） | **6 个全有**：论文解读 / 可视化 / 中文传播 / 英文传播 / 视频化 / 社区运营 |
| `run_720e83bdae91`（§4.1 主证据） | 全 done | 37 | 论文解读 / 可视化 / 中文传播 / **英文传播** / 视频化（**社区运营失败**：跑的是修复前代码） |
| `run_c5451b582400`（§3.6） | 全 done | 42 | 论文解读 / 可视化 / 中文传播 / 视频化 / **社区运营**（没配 `en` 变体） |

所以现在的准确说法是：**6 个 Agent 都有证据，且已由 `run_ec0f0e056f47` 一条 run 覆盖齐全**；"两条 run 拼合"在 §1.2 的层级口径下仍然成立，只是不再是**唯一**路径。这条 run 的配置就是把变体写成 `["xhs-author","zhihu-analyst","en-analyst"]`（照抄方式见 §6.9 与 §7.2）。

这里容易混的是**两条轴**，本文先把它们分开讲，再给映射：

| 轴 | 是谁的契约 | 内容 | 数量 |
| --- | --- | --- | --- |
| **轴一 · 前端可见的阶段（stage）** | UI 契约（前端按这 6 个位置渲染进度条） | `intake → understand → article → poster → video → publish` | 6 |
| **轴二 · 总纲的 Agent** | 产品意图（立项时原话） | 论文解读 → 可视化 → 中文传播 → 英文传播 → 视频化 → 社区运营 | 6 |

**两条轴都是 6，但不是一一对应**，关系是：

- **5 个 Agent 占 5 个 stage**：论文解读→`understand`、可视化→`poster`、视频化→`video`、中文传播+英文传播→`article`（**两个 Agent 共用一段**，靠"平台 × 人格"变体区分）、社区运营→`publish` 尾部；
- **`intake` 不承载任何 Agent**：它是 L0 输入归一化（总纲 §4.1 的输入层），是基础设施而不是"一个 Agent"；
- 所以 **6 个 Agent 落在 5 个阶段上**：其中 `article` 一段要出两种语言的产物，`publish` 一段里同时有"投递"和"运营"两件事。

### 1.1 先说清楚：本轮是**推掉了 R1 的边界**，不是一开始就在计划内

总纲 §2.2 的 R1 非目标表里，第 2 行和第 4 行原文写的是：

| 总纲 §2.2 的非目标 | 当时的原因 |
| --- | --- |
| `poster` / `video` 真实生成 | 依赖 Paper2Poster / Paper2Video 两个上游项目，先以 `skipped` 状态让主链路通 |
| 英文传播（X / LinkedIn thread） | 属 R2 的差异化部分，先确保中文闭环 |

**2026-09-19 这一轮把这两条都做了**：`app/models.py:21` 现在是 `IMPLEMENTED_STAGES = {全部 6 段}`、`SKIPPED_STAGES = set()`（第 20 行的注释也改成"poster/video 不再 skipped"），`app/styles.py` 里新增了 `en` 平台（第 138–172 行）。

也就是说：**这份覆盖表描述的是 R1.5 的实际状态，不是 R1 的验收清单**。拿总纲 §6 的 R1 判据去对，第 1 条（"poster/video 为 `skipped` 且 UI 明确说明"）今天已经不成立了 —— 因为能力追上来了，而不是当时写错了。附带后果：总纲 §7 风险表里"poster/video 长期 skipped → 产品承诺与实际能力不符"这条风险**已经解除**，而"英文传播 / 社区运营缺失"这条现在只剩后半句。

### 1.2 两级验证：run 级 vs 模块级（读本文档前先分清）

同一句"验证通过"，在这份工作区里可能指两件强度完全不同的事。本文档一律标明是哪一级：

| 层级 | 怎么做的 | 产物在哪 | 强度 |
| --- | --- | --- | --- |
| **run 级** | 起服务、建 run、**完整跑一遍 `pipeline.py` 的 6 段 plan**（含闸门），产物经 `ctx.artifact` 登记 | 落盘到 `var/runs/<id>/...`，并在 `run.json` 的 `stages[].artifacts[]` 里有条目（**前端可见**，带 `url`） | 最强：证明它在真实编排、真实素材、真实闸门下能跑 |
| **模块级** | 不起服务、不建 run：写个小脚本**直接调用**某个模块的函数，输入复用某条现成 run 的产物 | 可能落盘（如果模块自己写文件），但**通常不会进 run.json** —— 取决于那个脚本的 ctx 有没有真的把 check/artifact 写回去 | 较弱：证明"模块函数本身能出正确结果"，**不证明**它在流水线里能跑 |

本文档里：论文解读 / 可视化 / 中文传播 / 英文传播 / 视频化 都是 **run 级**（`run_720e83bdae91`）；社区运营则**同时有** run 级（`run_c5451b582400`，产物已登记）与模块级（`var/scratch/verify_community.py`，产物未登记）两级证据，细节见 §3.6。

层级高低的排序要记清：**"单条 run 覆盖 6 个 Agent"（`run_ec0f0e056f47`，§6.9）比"两条 run 拼合"更强** —— 前者一条 run 里 6 个 Agent 全部落盘、全部登记，是本文档的**首选引用**；后者（720e + c545）仍然有效，但只作为**补充与对照**（它们各自的失败与配置差异本身是有信息量的）。

---

## 2. 两条轴与映射表

### 2.1 轴一：前端可见的 6 个 stage（不要动它）

`apps/papercast-server/app/models.py`：

```python
# models.py:18
STAGE_ORDER: list[StageId] = ["intake", "understand", "article", "poster", "video", "publish"]

# models.py:20-22 —— poster/video 不再 skipped
IMPLEMENTED_STAGES: set[str] = {"intake", "understand", "article", "poster", "video", "publish"}
SKIPPED_STAGES: set[str] = set()
```

配套的 `STAGE_META`（`models.py:24-55`）给每个 stage 定了 `label` / `engine` / `hint`，前端进度条与"引擎与环境"视图直接读这三个字段。**这 6 个位置是稳定契约**（总纲 ADR #8）：阶段可以 `skipped`，不可以删；上游能力补齐时前端不需要改。

### 2.2 轴二：总纲 §1 的 6 个 Agent

原文（未删改，见 `docs/00-goal-and-architecture.md` 第 16–19 行）：

> 论文解读Agent（把复杂论文翻译成通俗语言）→ 可视化Agent（生成论文核心图表的科普版）→
> 中文传播Agent（写知乎/公众号科普文）→ 英文传播Agent（写 Twitter/LinkedIn thread）→
> 视频化Agent（生成 3 分钟论文解读视频脚本）→ 社区运营Agent（选择合适学术社区发布+互动），
> **6 个 Agent 让一篇论文实现多形态传播**

### 2.3 映射表（每条都对着代码核过）

| 总纲的 Agent | 落在哪个 stage | 实现位置 | 主要产物（run 内相对路径） |
| --- | --- | --- | --- |
| **论文解读** | `understand` | `apps/papercast-server/app/modules/generate.py` 的 `run_understand`（第 249 行）；提示词在 `app/prompts.py`（`DIGEST_SYSTEM` / `digest_user` / `NOTE_SYSTEM` / `note_user`） | `understand/digest.json`（**唯一事实源**）、`understand/reading_note.md`；另有 `understand/digest.raw.json`（模型原始输出，便于比对） |
| **可视化** | `poster`（**加** `article` 里的卡片） | 编排：`app/modules/poster_stage.py` 的 `run_poster`（第 309 行，digest → spec → 按渠道渲染）；渲染器：`app/modules/poster.py`（560 行，**别人的**，见 `docs/patches/`）；卡片：`app/cards/render.py`（182 行，PIL 确定性排版） | `poster/poster.png`（会议海报 2304×1728）、`poster/poster-xhs-long.png`（1080×2400）、`poster/poster-zhihu.png`（1600×1200）、`poster/poster-bili-cover.png`（1920×1080）+ `poster.spec.json`、`poster.spec.cover.json`；`article/cards/p1..pN.png`（3:4，1080×1440） |
| **中文传播** | `article` | `app/modules/generate.py` 的 `run_article`（第 382 行）；平台/人格身份层 `app/styles.py`（`PLATFORMS` 第 45 行起、`VOICES` 第 179 行起） | `article/xhs.md`、`article/zhihu-analyst.md`、`article/bilibili-peer.md` 等，文件名规则是 `{platform}-{voice}.md`（`generate.py:652`；voice 为默认 `author` 时退化成 `{platform}.md`）；外带 `article/export/{title.txt,content.txt}` |
| **英文传播** | `article`（**同一阶段，不同变体**） | `app/styles.py` 里新增的 `en` 平台（第 138–172 行：`unit="words"`、`language="英文"`、`output="markdown"`） | `article/en-analyst.md`（`{platform}-{voice}.md` 命名；spec 里的 `file="en-thread.md"` 只进提示词模板，不当文件名） |
| **视频化** | `video` | `apps/papercast-server/app/modules/video.py`（1438 行）的 `run_video`（第 1040 行） | `video/video.mp4`、`video/video-vertical.mp4`、`video/cover.png`、`video/narration.json`、`video/subtitles.srt`、`video/video.report.json` |
| **社区运营** | `publish` **尾部** | `apps/papercast-server/app/modules/community.py`（261 行）的 `run_community`；调用点 `app/modules/publish.py:395-404` | `publish/community.md`（**已登记、带前端 URL**）、`publish/community.plan.json` —— run 级证据在 `run_c5451b582400`，另有模块级直调证据，见 §3.6 |

### 2.4 为什么社区运营不新增一个 stage

因为**前端 6 个位置是契约**：`STAGE_ORDER` 多一段，UI 的进度条、阶段卡片、`STAGE_META` 查表全都要跟着改，而前端由另一个单写者负责（见 §6.1）。取舍是：把社区运营挂在 `publish` **尾部**，而不用新阶段——这个阶段的名字本来就是**「发布与运营」**（`models.py:51`，`engine` 写的是 `channels · 小红书 / 知乎 / B站`），语义上装得下。

代码里把这条取舍写成了注释（`publish.py:395-397`）：

```python
# ---- 6.5 社区运营：选社区 + 每个社区一版成稿文案 + 真实投递数据复盘 ----
# 挂在发布阶段尾部（该阶段的名字就是「发布与运营」），不新增 stage —— 前端 6 段的契约不动。
# 失败只标 check，不影响发布结果本身。
```

代价也说清楚：**社区运营失败不会让 `publish` 阶段变红**（异常被 catch 成一条 `check=fail`）。这是刻意的——投递结果与运营计划是两件事，一个失败不该把另一个也标成失败。但读 run.json 的人必须知道：`publish.status == "done"` **不代表社区运营成功了**，要看 `checks` 里那条「社区投放计划」。

---

## 3. 逐个 Agent 展开

每个 Agent 五问：**做什么 / 落在哪 / 产物在哪 / 一条可复核的验收 / 现状**。所有命令都在工作区根执行，先设一个通用变量与一个通用函数：

```bash
R=var/runs/run_720e83bdae91          # §4 的主证据 run（6 段全 done）

# 通用：打印某一段的状态、产物数、全部 checks（run.json 就是前端读的那份数据）
dump_stage() { python3 - "$R" "$1" <<'PY'
import json, sys
run = json.load(open(f"{sys.argv[1]}/run.json")); sid = sys.argv[2]
s = [x for x in run["stages"] if x["id"] == sid][0]
print(s["label"], "|", s["status"], "| 产物", len(s["artifacts"]))
for c in (s.get("checks") or []):
    print(" ", c["state"], c["label"], "::", c["detail"])
PY
}
```

### 3.1 论文解读 Agent → `understand`

**做什么**：把 PDF 解析结果（`intake/content.md` + `intake/figures.json`）压成一份结构化事实源；数字必须能在原文里检索到，检索不到就丢掉并记 `warn`。

**落在哪**：`apps/papercast-server/app/modules/generate.py` 的 `run_understand`；读 `ctx.shared["intake"]`，写 `ctx.work`（= `<run>/understand`）。**这一段有一个人工闸门**（gate id `digest`），放行前下游一段都不会开始。

**产物在哪**：`understand/digest.json`（`PaperDigest` 模型：贡献 / 方法 / 结果 / 图表 / 局限）、`understand/reading_note.md`（中文精读笔记，长文附加物）、`understand/digest.raw.json`。

**验收（run_720e83bdae91）**：

```bash
dump_stage understand
# → 论文理解层 | done | 产物 3
#    pass 事实源结构 :: 6 条贡献 / 697 字方法说明
#    pass 数值可回溯 :: 12 条结果全部能在原文中检索到
#    pass 图表选择   :: 选定 4 张：img-p17-1, img-p18-1, img-p19-1, img-p20-1
#    pass 精读笔记   :: 14023 字
```

数字对得上磁盘：`digest.json` 8,999 B、`reading_note.md` 27,731 B（= 14,023 个汉字 + Markdown 标记）。

**现状**：✅ 有真实产物（两个 run 都是 6 条贡献 / 12 条可回溯结果）。

### 3.2 可视化 Agent → `poster`（+ `article` 的卡片）

**做什么**：读事实源 → 让 LLM 写一份**版面描述** `poster.spec.json`（放什么，不管怎么排）→ 由确定性渲染器按渠道画布排版出图。**几何溢出即判失败**（DOM 实测每个面板的 `scrollHeight/clientHeight`），窄画布装不下就按优先级砍次要块，而不是把字缩小。

**落在哪**：`app/modules/poster_stage.py`（编排 + 闸门 + 登记产物）→ `app/modules/poster.py`（渲染器，来自上游 Paper2Poster，经 `docs/patches/` 留档）→ `ops/shot/render.mjs`（chrome-headless-shell）。卡片是另一条路：`app/cards/render.py`（PIL 直画 1080×1440），由 `generate.py` 在**第一个 `xhs` 变体**时渲染一次，其余变体复用（`generate.py:436-439`）。

**产物在哪**（`ctx.work` = `<run>/poster`）：4 张画布 png + `poster.spec.json` + `poster.spec.cover.json`；`<run>/article/cards/p1..pN.png`。

**验收（run_720e83bdae91：4 张画布全部过闸门）**：

```bash
dump_stage poster
# → Poster 生成 | done | 产物 6
#    pass 画布 · 会议海报 48×36in（打印/存档） :: (2304, 1728) · 正文 20.6px · scale 0.9229 · 溢出 0 处
#    pass 画布 · 小红书/知乎竖长图 1080×2400    :: (1080, 2400) · 正文 21.7px · scale 2.0747 · 溢出 0 处
#    pass 画布 · 知乎正文横版 1600×1200        :: (1600, 1200) · 正文 19.4px · scale 1.2513 · 溢出 0 处 · 已按优先级砍掉 3 个次要块
#    pass 画布 · B 站视频封面 1920×1080        :: (1920, 1080) · 正文 48.4px · scale 2.6 · 溢出 0 处
#    pass 几何闸门 :: 4/4 张画布无溢出
#    pass 图片引用 :: 全部引用图都渲染成功
#    pass 数字可回溯 :: spec 里的数字都能在 digest/原文找到
```

**"装不下就自动降级"是真的发生了，而且可复现**：知乎横版 1600×1200 塞不下完整版面，阶段日志记了 `装不下，砍掉 N 个次要块后通过（版面已存 poster.spec.{preset}.trim{N}.json）`（`poster_stage.py:300-302`），磁盘上留着每一步的中间版面，正是**砍了 3 步**的证据：

```text
var/runs/run_720e83bdae91/poster/poster.spec.zhihu.trim1.json
var/runs/run_720e83bdae91/poster/poster.spec.zhihu.trim2.json
var/runs/run_720e83bdae91/poster/poster.spec.zhihu.trim3.json
```

单个画布的渲染报告还能看到二分收敛过程（`poster-zhihu.render.json`）：`1.4175 溢出 186px → 1.0631 通过 → 1.2403 通过 → 1.3289 溢出 67px → … → 1.2513 通过`，最终 `body_px=19.4`（目标 22.0，即设计字号的 88%，仍在可读性下限 `LEGIBILITY_FLOOR=0.75` 之上）、`panel_fill=0.981`。

**现状**：✅ 有真实产物。**注意画布集合里没有 `poster-bili.png`**——第 4 张是 B 站**视频封面** `poster-bili-cover.png`（`models.py:48` 的 hint 与 `07-poster-and-cards.md` §1.5 的画布矩阵一致）。

### 3.3 中文传播 Agent → `article`

**做什么**：从同一份事实源派生各平台文案。**平台**决定体裁与硬约束（长度 / 公式 / 标签 / 输出格式），**人格**（voice）只决定语气与结构；校验只认平台硬约束，人格不参与。约束优先级：**事实源 > 平台硬约束 > 人格语气**。

**落在哪**：`app/modules/generate.py` 的 `run_article`；平台与人格定义在 `app/styles.py`（`PLATFORMS` / `VOICES`），提示词拼装在 `app/prompts.py` 的 `article_system` / `article_user`（`FACT_RULES` + `BRIEF_RULES`）。

**产物在哪**：`article/{platform}-{voice}.md`（`xhs` 的 voice=author 时就是 `article/xhs.md`，另有 `article/xhs.raw.json` 与 `article/cards/`）、`article/export/{title.txt,content.txt}`。

**验收（run_720e83bdae91 的知乎变体）**：

```bash
dump_stage article | grep '知乎 × 技术解读'
#    pass 知乎 × 技术解读 · 标题 :: 「DeepRare：三层多智能体系统做罕见病诊断，HPO 任务」= 19 字（上限 40）
#    pass 知乎 × 技术解读 · 正文长度 :: 2298 字（要求 2000-4000）
#    pass 知乎 × 技术解读 · 公式策略 :: 该平台允许 KaTeX 公式
#    pass 知乎 × 技术解读 · 标签数量 :: 5 个（要求 3-6）
#    pass 知乎 × 技术解读 · 指令遵从度 · 禁用表达 :: 未见 营销腔
#    pass 知乎 × 技术解读 · 指令遵从度 · 侧重 :: 已体现：方法
#    pass 知乎 × 技术解读 · 数字可回溯 :: 83 个数字全部可在事实源中回溯
```

小红书那一路的完整证据在另一条 run：`run_abb2805074e4`（`article/xhs.md` 3,438 B + **4 张卡片** `article/cards/p1..p4.png`，check「卡片渲染 pass 4 张 3:4 卡片」）与 `run_d76ca9da493e`（同样 4 张卡片 / 817 字）。

**现状**：✅ 有真实产物（`zhihu-analyst` / `xhs-author` / `xhs-analyst` / `bilibili-peer` / `wechat-*` 等变体都在 `styles.PLATFORMS × VOICES` 里可配）。

### 3.4 英文传播 Agent → `article`（`en` 平台）

**做什么**：写英文 thread（X / LinkedIn 通用），6–10 条编号帖，单条 ≤280 字符，全篇 320–850 **词**（`unit="words"` —— 纯英文用中文字数口径会算成 0，这是 `PlatformSpec.unit` 存在的理由）。

**落在哪**：**没有独立模块**，就是 `app/styles.py` 的 `PLATFORMS["en"]`（第 138–172 行）。英文传播与中文传播共用一个 `run_article`，这一点是刻意的：`docs/TODO.md` 的 E1 决策记录写着「**已决**：并入 `article` 作变体，不新增阶段」。

**产物在哪**：`article/en-analyst.md`。

**验收（run_720e83bdae91，变体 `en-analyst`）**：

```bash
dump_stage article | grep '英文传播'
#    pass 英文传播（X / LinkedIn） × 技术解读 · 标题     :: 「DeepRare: a three-layer agenti」= 75 字符（上限 90）
#    pass 英文传播（X / LinkedIn） × 技术解读 · 正文长度 :: 443 词（要求 320-850）
#    pass 英文传播（X / LinkedIn） × 技术解读 · 无公式   :: 未出现 LaTeX 表达
#    pass 英文传播（X / LinkedIn） × 技术解读 · 标签数量 :: 5 个（要求 3-6）
#    pass 英文传播（X / LinkedIn） × 技术解读 · 指令遵从度 · 禁用表达 :: 未见 营销腔
#    run  英文传播（X / LinkedIn） × 技术解读 · 指令遵从度 · 侧重 :: 指令要求侧重 方法，正文里未出现该词（可能换了说法，需人工看一眼）
#    pass 英文传播（X / LinkedIn） × 技术解读 · 数字可回溯 :: 58 个数字全部可在事实源中回溯

# 产物本身（2,859 B）：
head -3 $R/article/en-analyst.md
#   # DeepRare: a three-layer agentic system for traceable rare disease diagnosis
#   （空行）
#   1/10 DeepRare, an MCP-inspired three-layer multi-agent system, combines 40+ tools to diagnose rare diseases from free tex…
```

**现状**：⚠️ 后端有真实产物，**前端还没有可靠入口**（见 §6.1）。那条 `run` 是如实标注而不是静默通过：机检无法证明"换了说法也算侧重"。

### 3.5 视频化 Agent → `video`

**做什么**：`digest.json` → LLM 分镜（6–12 页，每页标题 / 2–4 条要点 / 40–120 字旁白 / 可选配图）→ PIL 画帧 → edge-tts 逐页配音 → ffmpeg 合成横竖两版 + 封面 + 字幕。**不是文生视频**，是"确定性排版 + 真 TTS + CPU 编码"。

**落在哪**：`apps/papercast-server/app/modules/video.py`（1438 行）的 `run_video`（第 1040 行）。只读三处：`understand/digest.json`、`intake/images/`、`article/cards/`。

**产物在哪**：`video/video.mp4`、`video/video-vertical.mp4`、`video/cover.png`、`video/narration.json`、`video/subtitles.srt`、`video/video.report.json`（+ 未登记的中间件 `video/frames`、`video/audio`、`video/clips`）。

**验收（run_720e83bdae91）**：

```bash
dump_stage video
# → 视频合成 | done | 产物 6
#    pass 视频可解码（横版） :: 1920×1080 h264 + aac 44100Hz/2ch；ffprobe 时长 269.10s（>0）
#    pass 视频可解码（竖版） :: 1080×1920 h264 + aac 44100Hz/2ch；时长 269.12s
#    pass 分镜数 :: 11 页（要求 6–12）；分镜来源 llm；3 页配图
#    pass 数字可回溯 :: 成片文本里的 70 个数字全部可在 digest.json 中回溯
#    pass 字幕与音轨对齐 :: 25 条字幕，末条结束 267.31s / 视频 269.10s，偏差 1.79s
#    pass 配音（TTS） :: 11 页全部用 zh-CN-XiaoxiaoNeural 配音（edge-tts）
#    run  时长 :: 成片 269.1s / 目标 180s（旁白合计 1344 字）
#    pass 封面 :: cover.png 1920×1080，361 KB
```

**模块独立实测（自带 CLI，原始输出在 `apps/papercast-server/docs/10-module-video.md` §5）**：`ffprobe` 读出 `video.mp4` = 1920×1080 / h264 **High** / yuv420p / 25fps + aac **LC** 44100Hz 2ch / 时长 **238.183203s** / **6,255,515 B**；`video-vertical.mp4` = 1080×1920 / 时长 **238.200000s** / **5,794,539 B**；8 条 check 全 pass，其中「数字可回溯 **76 个全部可在 digest.json 中回溯**、丢弃 0」。

那条独立实测跑在 `run_d5cd057bab48` 的输入上，**但该 run 的 `run.json` 里 `video` 仍是 `skipped`**——因为它用模块 CLI 单跑（`python -m app.modules.video --run run_d5cd057bab48`），没走流水线；产物落在 `var/runs/run_d5cd057bab48/video/`，只是没被登记进 `run.json`。**"产物在磁盘上"与"前端看得到"是两件事**，引用时要分清。

**现状**：✅ 有真实产物（流水线内 + 模块 CLI 两条路都验证过）。

### 3.6 社区运营 Agent → `publish` 尾部 —— **验收依据 = `run_c5451b582400`（真实流水线 run 级，产物已登记）**

**做什么**（按 `community.py` 的设计意图）：读事实源 + 已备好的素材 + 渠道账号现状，出**社区投放计划**——选 4–6 个社区（至少 1 个学术社区、中英各至少 1、至少 1 个帖子型平台），每个社区一版**可直接复制发布**的成稿文案 + 该社区的规矩 + 风险与规避 + 互动口径 + 该盯的指标，并附**真实投递数据复盘**（只走 `app/ops.py` 的只读接口，取不到就说取不到）。数字回溯口径与 M2 同源（`community.py:224-232`）。

**落在哪**：`app/modules/community.py`（`run_community`，第 157 行），由 `publish.py:395-404` 在写回执之后调用，异常被 catch 成一条 check。

**产物在哪（设计）**：`publish/community.md`（人读版，程序确定性拼装）、`publish/community.plan.json`（结构化）。

**产物在哪（实际）**：run 级证据在 `run_c5451b582400`；另有模块级直调证据落在 `run_720e83bdae91/publish/`。

**验收：一共三种证据，按"是不是完整 pipeline 跑出来的"分开读（定义见 §1.2）。**

| 层级 | 对象 | check 结果 | 产物落盘？登记？ |
| --- | --- | --- | --- |
| **run 级 · 成功** | `run_c5451b582400`（6 段全 done；`publish` 段 02:15:36 → 02:18:42） | 社区覆盖 / 草稿可用 / 社区规矩 / 数字可回溯 = **pass**；「投递数据复盘」= `run`（如实写"渠道接口没有返回任何已投递条目"） | **落盘且登记**：`publish` 段 12 个产物，含 `community.md`（**带前端 URL**）与 `community.plan.json` |
| **run 级 · 失败** | `run_720e83bdae91`（§4.1 主证据） | `fail 社区投放计划 :: LLMError: 模型输出不是合法 JSON` —— 跑的是**修复前**的代码 | 无产物 |
| **run 级 · 失败** | `run_d76ca9da493e` | `fail 社区投放计划 :: LLMError: 401 CreditsError: Insufficient balance` | 无产物 |
| **模块级** | `var/scratch/verify_community.py`（不起服务，复用 `run_720e83bdae91` 的 run.json + receipts 直调 `run_community`） | 按 `community.py` 的同一口径复算：草稿可用 / 社区规矩 / 数字可回溯 = pass，**社区覆盖 = fail**（只出了 3 个社区，门槛是 ≥4） | 落盘到 `run_720e83bdae91/publish/`，**未登记** |

**run 级那条的复核命令（可自己跑）**：

```bash
R=var/runs/run_c5451b582400
dump_stage publish | grep -E '社区|草稿|投递数据'
#   pass 社区覆盖     :: 6 个社区（语言 en/zh）；是否含学术社区：True
#   pass 草稿可用     :: 6 份草稿都可直接发布
#   pass 社区规矩     :: 每个社区都写清了该社区的投放规矩
#   pass 数字可回溯   :: 社区文案里的数字都能在事实源里找到
#   run  投递数据复盘 :: 暂无可读回数据：渠道接口没有返回任何已投递条目（可能还没投过东西）
#   run  发布结果     :: 仅存草稿（素材包已就绪）      ← 闸门点的是 draft，没真投递

python3 -c "
import json
d = json.load(open('$R/run.json'))
for a in [x for s in d['stages'] for x in s['artifacts'] if 'community' in x['path']]:
    print(a['kind'], '|', a['label'], '|', a['path'], '|', a.get('url'))
"
#   markdown | 社区投放计划（含每个社区的成稿文案） | …/publish/community.md      | /artifacts/run_c5451b582400/publish/community.md
#   json     | 社区投放计划（结构化）               | …/publish/community.plan.json | None
```

> 上面第二段用 `a.get('url')` 而不是 `a['url']`：`community.plan.json` 这条产物是 `preview=False` 登记的，**根本没有 `url` 这个键**，直接下标会 `KeyError`。

产物内容（我自己读过）：**6 个社区**——Reddit r/MachineLearning、Hacker News、X、知乎、小红书、B站；成稿文案合计 **8,183 字**；`community.md` 21,454 B；每个社区都写了该社区规矩、风险与规避、该盯的指标。第一版（Reddit）的切入角度选的是"三层 MCP 式 agent 的分工边界 + 作者主动公开的两类参考错误"。

**读 run.json 的人最容易踩的三个坑**（这也是本节要把层级分开写的原因）：

1. **成功时不写 wrapper check**：`run_community` 正常返回时只写它自己那 5 条 check；只有**抛异常**时才由 `publish.py:402-404` 补一条 `社区投放计划 = fail`。所以"看不到『社区投放计划』这条"= **成功**，不是"根本没跑"。
2. **失败时一个产物都不写**：`run_community` 是拿到完整计划后才落盘，截断 / 401 都发生在落盘之前 —— 这就是 `run_720e83bdae91` 里 `community.md` 曾经 404 的原因（代码问题，不是设计如此）。
3. **`ls` 不等于已登记**：模块级那次用的是自带 stub ctx（`check` / `artifact` 只 print、不写回 run.json），所以同一个目录里会出现"文件在磁盘上、前端看不到"。判断有没有登记，**只看 `run.json` 的 `stages[].artifacts[]`**。`run_720e83bdae91/publish/` 下那两个文件至今属于这一类（`run.json` mtime 仍是 02:00:05、`publish` 段仍是 10 个产物、那条社区 check 仍是 `fail`）。

**模块级那条怎么复跑**（脚本在 `var/scratch/`，不在 `ops/`，属临时验证物）：

```bash
python var/scratch/verify_community.py var/runs/run_720e83bdae91
# 注意：① 它只 print check、不写 run.json；② 它固定传 published=["zhihu"]；③ 它复用现成 run 的 run.json，所以失败原因（如 401 余额）不会体现在这里
```

**现状**：✅ **这一格的验收依据是 `run_c5451b582400`**（真实流水线 run 级：产物落盘 + 登记 + 带前端 URL + 4 条 check pass、1 条如实 `run`）。模块级那次直调（第 3 行）作为**补充证据**保留，用来证明"模块本身能独立跑"，但它**不是**验收依据。剩下的差距见 §6.7（只有计划层、没有真正的社区账号接入）与 §6.10（产出依赖 LLM 配额）。**单条 run 覆盖 6 个 Agent 的完整证据在 §6.9**（`run_ec0f0e056f47`，社区运营同样在这一条里成功落盘）。

---

## 4. 端到端证据

### 4.1 主证据：`run_720e83bdae91`（6 段全 done）

| 项 | 值 |
| --- | --- |
| 素材 | `var/samples/deeprare.pdf`（9,891,107 B，来源 `up_e2f9c3422f6d`；run 内副本 `intake/paper.pdf` 同尺寸） |
| `config.brief` | 「做成知乎长文，重点讲方法，不要营销腔」 |
| 变体 | `en-analyst` + `zhihu-analyst`（**这一轮没配 `xhs` 变体，所以没有卡片产物**） |
| 阶段 | 6 段全 `done`（`run.status = done`） |
| 登记产物 | **37** 个（intake 8 / understand 3 / article 4 / poster 6 / video 6 / publish 10） |
| 磁盘文件 | **116** 个（差值是 `video/frames`、`video/audio`、`video/clips` 等中间件，以及 §3.6 那次直调写下的 `publish/community.md` + `community.plan.json`——它们**都不登记**，前端看不到） |

分段结果（详细 check 见 §3）：`understand` 6 条贡献 / 12 条可回溯结果 / 笔记 14,023 字；`article` `en-analyst.md` 443 词（58 个数字可回溯）+ `zhihu-analyst.md` 2298 字（83 个数字可回溯）；`poster` **4 张画布几何闸门全过**，知乎横版触发自动降级（砍 3 个次要块）；`video` 横 269.10s / 竖 269.12s + 封面 + 25 条字幕，时长超目标记 `run`；`publish` 回执落到 3 个渠道目录 + 总表。

**发布这一段要读细**（它只有一小部分算"成功"）：

| check | state | 原文 detail |
| --- | --- | --- |
| 素材适配：小红书 | pass | 视频笔记 |
| 渠道状态：小红书 | **fail** | MCP 在线，但当前未登录（或登录已失效） |
| 素材适配：知乎 | pass | 长文（2848 字，无配图）；视频通道未接，只投文字与配图 |
| 渠道状态：知乎 | pass | 账号 YYDH（通道在线，已登录：YYDH（yydh-75）） |
| 素材适配：B站 | pass | 视频投稿（video-vertical.mp4 / 封面 有 / 1 个标签） |
| 渠道状态：B站 | pass | 账号 YYDH54（通道在线…） |
| 可投递渠道 | pass | 知乎、B站 |
| 社区投放计划 | **fail** | 见 §3.6（run.json 里这条是流水线那次失败的记录；02:13 直调成功产出的两个文件没被登记回来，所以这里仍是 fail） |
| 发布结果 | run | 仅存草稿（素材包已就绪） |

结论要念准两点：① **"有视频成片之后 B 站素材适配才通过"**——同一个 run 的 `video` 段出了 `video-vertical.mp4`，B 站这条才从"缺视频"变成"可投"（对照 `run_abb2805074e4`：那条没跑视频，B 站是"缺视频"✗）；② 小红书因为**未登录**整条 `fail`。最终闸门选的是 **draft**，所以**什么都没真发出去**，三个渠道的 `export/` 素材包都已就绪（`publish/<渠道>/export/`）。

**这条 run 的社区那一格是失败的**（跑的是修复前代码）。把这一格补上的是**另一条 run**：`run_c5451b582400`（6 段全 done / 42 个登记产物 / 社区计划 4 pass + 1 run），但它**没配英文变体**。这两条合起来才覆盖 6 个 Agent —— 而**单条 run 覆盖 6 个**的证据后来也跑出来了（`run_ec0f0e056f47`，见 §6.9）。本节的这两条 run 不因此作废：一条留着"英文传播 + 修复前失败"的对照，一条留着"社区运营 run 级成功"的对照。

### 4.2 第二证据：`run_abb2805074e4`（两个中文变体 + 4 张卡片 + brief 机检）

| 项 | 值 |
| --- | --- |
| `config.brief` | 「做成知乎长文，800 字以内，重点讲方法，不要营销腔，避免颠覆式表达」 |
| 变体 | `zhihu-analyst` + `xhs-author` → `article/zhihu-analyst.md`（7,356 B）、`article/xhs.md`（3,438 B）+ `xhs.raw.json` + **4 张卡片** `article/cards/p1..p4.png` |
| 阶段 | intake / understand / article / poster / publish = `done`，`video` = `skipped`（这一轮没跑视频） |
| 登记产物 | 34 个（intake 8 / understand 3 / article 7 / poster 6 / publish 10） |
| poster | 4 张画布全过（会议海报 scale 0.99 / 竖长图 2.0553 / 知乎横版 1.1296，同样砍 3 个次要块 / B 站封面 2.6） |

**brief（用户指令）的机检遵从度确实生效了**，这是 `generate.py` 的 `brief_checks`（第 54 行起）抽出的三类可判定约束（字数上限 / 禁用表达 / 必须体现的侧重）在真数据上的体现。该 run 里有两条例外：

| check | state | 原文 detail |
| --- | --- | --- |
| 知乎 × 技术解读 · 正文长度 | **fail** | 1930 字（要求 2000-4000） |
| 知乎 × 技术解读 · 指令遵从度 · 字数上限 800 | **fail** | 实际 3491 字，超出 2691 字 |
| 知乎 × 技术解读 · 指令遵从度 · 禁用表达 | pass | 未见 营销腔、颠覆式表达 |
| 小红书 × 作者自述 · 指令遵从度 · 字数上限 800 | pass | 实际 766 字 |

这就是**用户指令与平台硬约束的正面冲突**：brief 要 ≤800 字，而知乎这个平台的正文下限是 2000 字（`styles.py:84` 的 `body_min=2000`）。按 `prompts.BRIEF_RULES` 第 4 条，规则是**「平台硬约束 > 用户指令」**。

> ⚠️ **两条时间线要分清（这里有一处未验证）**：上面那两条 `fail` 是 **2026-09-19 01:42 那次 run 的记录**。现在工作区里的 `generate.py:69-77` 已经把这种情况判成 `run` 而不是 `fail`，并在 detail 里写明冲突原因（"指令要 ≤800 字，但该平台正文下限是 2000 字 —— 按「平台硬约束 > 用户指令」以平台为准（实际 N 字）；想真正压到 800 字请换短体裁平台"）。**这个新行为本文档没有复跑验证**——本轮只允许写文档，不跑新 run。所以：老证据（`fail`）是真实的，新行为（`run` + 冲突说明）是**读代码得到的、未验证**。
>
> 顺带一个容易误读的点：同一条正文，check「正文长度」算的是 **1930 字**，而 brief 那条算的是 **3491 字**——因为前者只数正文，后者数整篇 Markdown（含标题与小标题）。两个数不矛盾，但**引用时要写清是哪个口径**。

### 4.3 本文引用的 run 清单（每条的来历与用途 —— 它们**不是同一批实验**）

下表每一行都是**一次独立运行**：不同的上传副本、不同的变体配置、不同的时间，用途也不同。本文档任何一处提到 run id，都在这里能查到它是哪条。

| run id | 它是什么 / 什么时候跑的 | 素材（上传 id） | 变体 | 6 段状态 | 登记产物 | 本文用它证明什么 |
| --- | --- | --- | --- | --- | --- | --- |
| `run_ec0f0e056f47` | **§6.9 单条 run 覆盖 6 个 Agent 的验收依据**：deeprare 的完整跑，02:45:27 → 02:55:57（630s） | deeprare.pdf（`up_96c58bfae000`，23 页，9,891,107 B） | **xhs-author + zhihu-analyst + en-analyst** | 全 done | **51**（42 带 url） | **6 个 Agent 全在一条 run 里**；51 件登记 / 42 件 HTTP 200 / check 53 pass·1 fail·3 run |
| `run_720e83bdae91` | **§4.1 主证据**：deeprare 的完整跑，01:49 → 02:00 | deeprare.pdf（`up_e2f9c3422f6d`，23 页，9,891,107 B） | en-analyst + zhihu-analyst | 全 done | 37 | 6 个 Agent 里 **5 个**的 run 级证据；**英文传播那一格的首个证据**；社区那一格此条失败 |
| `run_c5451b582400` | **§3.6 社区运营的 run 级证据**：deeprare 的完整跑，02:09 → 02:18 | deeprare.pdf（`up_6d9dc259c0a8`，23 页） | zhihu-analyst | 全 done | 42 | **社区运营的 run 级成功**（`community.md` 已登记、带前端 URL，6 社区 / 8,183 字） |
| `run_a4cd493515f8` | **§6.9 的失败尝试 1**：02:33:35 起跑，**死在 `understand`** | deeprare.pdf | （§6.9 的同一配方） | intake done / understand **failed** | 14 | 外部重启把在途 run 判成 `failed` / `INTERRUPTED` 的现场 |
| `run_87ff2439468a` | **§6.9 的失败尝试 2**：02:36:36 起跑，**死在 `poster`** | deeprare.pdf | （同上） | intake/understand/article done / poster **failed** | 28 | 同上（第二次重启）；也证明前 3 段能跑完 |
| `run_abb2805074e4` | **§4.2 brief 冲突证据**：01:38 → 01:42 | deeprare.pdf（`up_a0e4c04dbec8`，23 页） | zhihu-analyst + xhs-author | video skipped | 34 | brief 机检遵从度（两条 `fail`）；小红书 **4 张卡片** |
| `run_d76ca9da493e` | 第二条"6 段全 done"的对照：01:36 → 02:05 | deeprare.pdf（`up_be91014e18e9`，23 页） | xhs-author + zhihu-analyst | 全 done | 42 | 视频 **291.4s** 那一例；社区计划栽在**渠道余额（401）**——与 720e 的"截断"是两个不同的失败原因 |
| `run_d5cd057bab48` | **video 模块 CLI 独立实测的输入**（模块单跑，非流水线） | deeprare.pdf（`up_e16f64575006`，23 页） | xhs-author | poster/video skipped | 29 | `10-module-video.md` 那组 ffprobe 数字（238.18s / 76 个数字）；video 产物在磁盘但**未登记** |
| `run_224e72b5a672` | **接线前**的历史快照（2026-09-18 23:14，M1/M2 时代） | paper2video.pdf（`up_d03bcdadb190`，19 页，5,251,910 B） | xhs | poster/video skipped | 29 | `06-verification.md` 里那次 **12 张图**的 smoke 跑；对照"当时 poster/video 还是 skipped" |
| `run_3b0e657e0f50` | 同上，更早一次（2026-09-18 23:14，M1 时代） | paper2video.pdf（`up_b6f8c22c1253`，19 页） | xhs | poster/video skipped | 22 | 同上，产物更少的早期版本 |

三件必须说清，免得读者把它们当成同一批：

- **第 1 条（ec0f）是本轮最终的验收证据**，它一条 run 覆盖 6 个 Agent；**第 2、3 条**（720e / c545）是它之前的"拼合证据"，变体配置不同（一个带英文、一个带社区成功），仍然有效、作为对照；
- **第 4、5 条（a4cd / 87ff）是同一个配方的失败尝试**，都被外部重启杀死（`INTERRUPTED`）——它们**只作 B1 现场证据**，不代表能力，也不代表配置错误；
- **中间两条**（abb / d76）是**同一篇论文的另外两次运行**，用途分别是 brief 冲突与时长/余额对照；
- **最后两条**（224e / 3b0e）是 **2026-09-18 的 M1/M2 时代产物**，那时 poster/video 还是 `skipped`——只作历史对照，**不代表当前能力**；
- 素材上：三条以 deeprare 为素材的 run 用的是**同一份 PDF（9,891,107 B）的不同上传副本**（`up_` 开头的 id 各不相同），不是同一次上传。

---

## 5. 可信性设计（为什么这张表值得信）

产物"存在"不等于"可信"。这一节是这份覆盖表与普通 demo 报告的区别所在。

| # | 机制 | 在哪实现 | 可复核点 |
| --- | --- | --- | --- |
| 1 | **digest.json 是唯一事实源** | 总纲 ADR #1；`understand` 之后所有模块只读它（`run_article` / `run_poster` / `run_video` / `run_community` 都先找 `understand/digest.json`，不重新理解论文） | 每个下游模块的"读入"清单里都只有这一份事实源 |
| 2 | **数字必须能回溯，不通过就丢弃** | M2：`generate.py` 的 `_drop_untraceable` + `numbers_in`；video 复用同一套（`video.py` 的 `residual_violations` 与 `droppedTraceability`）；poster：`poster_stage.py:371-373` 丢弃含不可回溯数字的内容；社区：`community.py:224-232` | run 里可读：`pass 数字可回溯 :: 12 条结果全部能在原文中检索到`、`83 个数字全部可在事实源中回溯`、`70 个数字全部可在 digest.json 中回溯`、`丢弃 0` |
| 3 | **LLM 只出 JSON，排版/合成是确定性程序** | 海报：spec（LLM）→ `poster.py`（程序）；卡片：`cards/render.py`（PIL）；社区：`community.render_markdown`（"模型只出 JSON，排版由程序拼"） | 换后端重排只需换 spec；同一 spec 出图可复现（总纲 ADR #5） |
| 4 | **两个人工闸门** | ① `understand` 的 `digest` 闸门（`generate.py:337-345`，选项 continue / revise+批注重跑）；② `publish` 的 `publish-gate`（`publish.py:286-295`，选项 continue / draft / skip） | 两个 run 的 gate 都在 `run.json` 里可见（`resolved` + `askedAt`）；`run_720e83bdae91` 的 digest 闸门 `resolved="continue"` |
| 5 | **发布默认草稿，真实投递必须人工确认** | `publish.py:298-307`：只有 `chosen not in ("draft","skip")` 才调发布接口；`scripts/smoke_test.sh` 里发布闸门**默认回 `draft`**，只有显式 `PUBLISH=1` 才真发 | 主证据 run 的「发布结果」= `run`「仅存草稿（素材包已就绪）」；三条渠道的 `export/` 都在 |
| 6 | **失败不静默** | `ctx.artifact`（`pipeline.py:89-93`）文件不存在就不登记；模块异常 → `stage.status=failed` + `error.log`（`pipeline.py:334-341`）；TTS 失败 → 降级但记 `check=fail` + 原始报错 | 社区运营**失败**时是一条可见的红色 check（`run_720e83bdae91`）、**成功**时是 5 条模块内 check（`run_c5451b582400`）—— 两种都比"阶段 done 一切正常"信息量大 |
| 7 | **check 的 `run` 是第三态，不是凑数的绿** | `StageCheck.state ∈ {pass, fail, run}`（`models.py:111`），`run` = "机器判不了，需人工看一眼" | 例：`run 时长 :: 成片 269.1s / 目标 180s`；brief 的"侧重"检查在英文变体上也是 `run` |

---

## 6. 边界与已知限制

照实写，不美化。

### 6.1 前端契约的分工（英文平台入口）

- **前端源码目录（`apps/papercast/src/`）归前端 agent 单写者负责**，本文档不描述、不修改它的行为。
- 后端这一侧：`app/styles.py` 的 `platform_menu()`（第 317 行）**目前没有生产调用方**——引用它的只有 `tests/test_styles.py:206`（单测）和 `scripts/test_article_variants.py:65`（手工脚本）。`voice_menu()` 同理。**英文平台在前端的入口由前端 agent 补**。
- 我核实到的事实：工作区里 `apps/papercast/src/components/IntakePanel.vue:70-71`（该文件在当前工作区**有未提交改动**）已经列了一个 `{ id: 'en', label: '英文传播', … }` 的平台选项，`src/types.ts:155` 的联合类型也已含 `'en'`。**但这条路我没有端到端验证过**（那是前端 agent 的地盘），所以本文档按"**英文传播的后端已就绪、前端入口归属前端 agent、当前状态未验证**"记录。
- 另外，`docs/TODO.md` 记的用户决策是「**英文不发**」：只产出与导出，本轮不接投递通道（E3）。所以 `en` 不在 `config.publish.targets` 里，与 §2.3 表里"英文传播→article"是一致的。

### 6.2 小红书必须人工扫码登录

主证据 run 的 `渠道状态：小红书 = fail「MCP 在线，但当前未登录（或登录已失效）」`。这是**已知且刻意**的：登录态在 `var/cache/xiaohongshu-mcp/browser/`（`docs/conventions.md` §4 已标为"贵重"），删掉就要重新扫码；MCP 必须在 `apps/xiaohongshu-mcp/` 目录里启动（cookie 按 cwd 解析）。**未登录时 `publish` 不会静默跳过**——它标 fail、把素材包留在 `export/`，让人 30 秒手动发。

### 6.3 视频是静态帧，没有动画、没有人

画面 = PIL 画的固定版式帧（标题 + 要点 + 配图）→ ffmpeg 逐页合成。**没有动画、转场、光标、数字人**。这是"确定性排版 + CPU 编码"的代价，也是它可靠的原因（`10-module-video.md` §6.1）。相关：竖版是把 1920×1080 缩到 980 宽的居中卡片，**小字在手机上偏小**（该文档 §6.8）；字幕是**句级**而不是词级高亮（该文档 §6.5）。

### 6.4 时长会漂移，而且闸门比"±30%"更宽

- 实现（`video.py:1274-1275`）：`pass if abs(total - target_sec) <= max(45, 0.35 * target_sec) else "run"` → **容差是 ±35%（且下限 45 秒）**，不是 ±30%；超出也只记 `run`（人工看），不是 `fail`。
- 实测四例：`run_720e83bdae91` 目标 180s → 成片 **269.10s**；`run_d76ca9da493e` 目标 180s → **291.4s**；`run_ec0f0e056f47` 目标 180s → **234.26s**（|234.26−180| = 54.26 ≤ max(45, 63) = 63，落在容差内 → check 是 **`pass`**）；`10-module-video.md` 的独立实测是 238.2s（+32%，也在容差内）。前两例已超出容差（180×1.35 = 243s），所以 check 是 `run` 并如实写出"成片 269.1s / 目标 180s"。**同一个目标时长能落到 pass 也能落到 run**，取决于 LLM 那轮分镜的篇幅。**时长是"接近"而不是"命中"**：总时长 = 各页配音时长之和，靠"旁白字数 ≈ 4.6 字/秒 × 目标"逼近。

### 6.5 时长与配图命中率依赖 LLM 波动（不可复现）

分镜是 LLM 采样的产物：`10-module-video.md` §6.6 记录**同一篇论文两次跑出过 8 页 194s 与 10 页 238s**；本次证据里是 11 页（`run_720e83bdae91`）和 12 页（`run_d76ca9da493e`）。配图同样是启发式：deeprare.pdf 的图注全是"（第 N 页内嵌图像，未匹配到图注）"，模型只能按"讲数据/结果的页可以配图"挑，11 页里只有 **3 页配图**（`run_d76ca9da493e` 是 12 页里 4 页）。图注可靠时（LaTeX 抽取的 `fig-1-teaser.png`）判断会好得多。要复现分镜得锁 `config.video.narration` 或走 `--no-llm`。

### 6.6 M1 的图注匹配在一类排版上失效（正在修，**未验证**）

主证据 run 的 intake check 是**通过**的，但内容值得警惕：

```bash
dump_stage intake
#    pass 正文抽取 :: 123k 字符 / 6 个标题
#    pass 图片抽取 :: 4 张（fig 0 / table 0 / 未匹配 4）      ← 0 张匹配到图注
#    pass 元数据   :: An agentic system for rare disease diagnosis with traceable reasoning
#    pass 图片引用 :: 全部图片文件存在
```

4 张图**全部按 `kind=img`、"未匹配到图注"**归类（caption 是占位文字"（第 N 页内嵌图像…）"）。对照 `docs/06-verification.md` §2，同一套"图注驱动 + 连续内容带"策略在 paper2video.pdf 上曾拿到 **12 张（fig 8 / table 4 / 未匹配 0）**——说明是**某类排版**让这套策略失效，不是策略整体不行。

**根因已由 intake 轨道定位（2026-09-19 02:08，看板留言；我未独立复核其结论）**：deeprare.pdf 是 Nature 系排版、**有文字层、不是扫描件**，失效有三条：① 该刊图注用**竖线**分隔（如 `Fig. 1 | caption`），原 `CAP_RE` 只认空格，全文 0 命中 → 图注驱动一张都没抽到，只剩兜底路径的 4 张 raster（也就是上面那个 `fig 0 / table 0 / 未匹配 4`）；② 图注在版面上只占左栏、图却跨两栏，按图注宽度裁只得到**左半张**；③ 柱状图窄柱宽度 `10.7pt`，被 `get_drawings` 的 `w > 12pt` 过滤整类滤掉，纯矢量图 vis 为空。据该留言，修完后 deeprare 的 figures 会从「4 张 kind=img 无图注」变成 **8 fig + 1 table 带真图注**（含 Extended Data 3 图 + 1 表）；paper2video 仍是 12 张不变。**这条修复我既没复核也没复跑**，所以本文档只记"正在修、未验证"。

`apps/papercast-server/app/intake/pdf_parser.py` 在当前工作区**有未提交改动**（文件头注释写着已改成"图注驱动 + 连续内容带"），**这个改动的实际效果本文档未验证**（本轮不跑新 run）。下游能感到的后果就是 §6.5 的配图命中率。

### 6.7 社区运营的社区清单只到"计划层"，没有真正的社区账号接入

- `community.py` **只产出计划与文案**：它不登录 Reddit / Hacker News / X，不建帖、不回复、不点赞。`_stats_snapshot` 是**只读**的数据复盘（走 `app/ops.py`），取不到就写"取不到"。
- 所以这一格的产物**永远止于** `publish/community.md` + `community.plan.json`（run 级已有，见 §3.6）。"社区运营 Agent 在干活"目前**准确的含义**是"写出了可直接复制粘贴的投放计划与成稿文案"，而**不是**"发了帖、回了评论、做了互动"。
- 计划里的社区清单是 **LLM 按提示词自己选的**（提示词要求选 4–6 个、至少 1 个学术社区、中英各至少 1、至少 1 个帖子型平台），**没有账号打通、没有社区白名单校验、也没有"这个社区允不允许这样发"的实证**（run 级那次的 6 个社区：Reddit r/MachineLearning、Hacker News、X、知乎、小红书、B站）。
- 论文事实层它只认 digest（`community.py:161-162`：缺 `understand/digest.json` 直接抛错），数字回溯口径与 M2 同源——这部分设计是可信的。

### 6.8 其它诚实标注

| 项 | 状态 |
| --- | --- |
| 海报"好看"与否 | 几何闸门只保证"不溢出、不空"（`panel_fill` 反映留白），**保证不了好看**；没有 VLM 打分（无 VLM key） |
| 卡片 3:4 版式 | PIL 固定版式，中文靠 `config.find_cjk_font`（本机命中 `~/.local/share/fonts/waic/msyh.ttc`）；缺字形直接报错，不产豆腐块 |
| 视频无背景音乐 / 无音量归一化 | edge-tts 输出直连，没有 `loudnorm` |
| 视频取消不即时 | 单次跑 2–4 分钟，ffmpeg 在 `to_thread` 里，`asyncio` 取消打断不了已启动的子进程 |
| 发布只有 3 个渠道 | 小红书（MCP）/ 知乎 / B 站；公众号封面按 2026-09-19 决定不做 |
| 平台菜单 API | `platform_menu()` / `voice_menu()` 无生产调用方（§6.1） |
| `/api/chat` | 后端另有 `app/chat_api.py` 端点（另一条轨道加的），**与本文档的 6 Agent 覆盖无关**，不要混在一起读 |

### 6.9 单条 run 覆盖 6 个 Agent —— **已验证**（`run_ec0f0e056f47`）

> 本节此前写的是"没有哪一条 run 单跑齐 6 个 Agent（未验证，合并跑我没跑）"。**那一格现在已补上、原声明作废**：`run_ec0f0e056f47` 一条 run 就把 6 个 Agent 全覆盖了。

| 项 | 值（下面每一条我都自己复核过，复核命令见本节末） |
| --- | --- |
| run | `run_ec0f0e056f47`，2026-09-19 02:45:27 → 02:55:57（**630s**），`run.status=done`、`error=null` |
| 配置 | brief「做成知乎长文，重点讲方法，不要营销腔」+ `article.variants=["xhs-author","zhihu-analyst","en-analyst"]`（3 个，未超 `MAX_VARIANTS=4`）；素材 `var/samples/deeprare.pdf` |
| 六段 | intake / understand / article / poster / video / publish **全部 done** |
| 闸门 | understand = `continue`、publish = **`draft`**（**零真实投递**） |
| 产物 | **51 件登记在同一条 run.json 里**；其中 **42 件带前端 `url`** —— 我逐条本地取回：**42/42 HTTP 200** |
| 登记 vs 磁盘 | 51/51 件按登记 `path` 都在磁盘上，**bytes 与登记值逐一相等** |
| check | **53 pass / 1 fail / 3 run**（唯一 `fail` 是「渠道状态：小红书」未登录；3 条 `run` 是英文变体的指令侧重、投递数据复盘、发布结果，都带 detail，不是假装通过） |

**6 个 Agent 在这条 run 里的实物**（逐条对应 §3 的分节）：

| # | Agent | 落点 | 实物 |
| --- | --- | --- | --- |
| 1 | 论文解读 | `understand` | `digest.json` 11,047 B：6 条贡献 / **12 条数值全部可回溯** / 选定 6 张图表；精读笔记 26,106 B |
| 2 | 可视化 | `poster` + `article` 卡片 | 4 张画布 **2304×1728 / 1080×2400 / 1600×1200 / 1920×1080**，**`overflow=[]` 4/4**、`broken_images=[]`；另 6 张 1080×1440 卡片 |
| 3 | 中文传播 | `article` | `xhs.md`（正文 **830 字** + 6 张卡片）+ `zhihu-analyst.md`（正文 **2,378 字**，96 个数字全回溯） |
| 4 | 英文传播 | `article` | `en-analyst.md` **428 词**（口径是 `styles.text_len(text,"words")`，不是 `split()`）；`1/10 … 10/10` 十条编号帖 + `## Tags`，真英文不是中文套壳 |
| 5 | 视频化 | `video` | `video.mp4` **234.263203s / 1920×1080 / h264+aac / 6,695,879 B**（ffprobe 我自己跑的）+ 竖版 234.280s；10 页分镜 / 24 条字幕 / **时长 check 这次是 pass** |
| 6 | 社区运营 | `publish` | `community.md` 19,042 B + `community.plan.json` 18,905 B：**6 个社区**（知乎 / 小红书 / B站 + Reddit r/MachineLearning / Hacker News / X，zh×3 + en×3），成稿 **8,510 字符**，社区 4 条 check 全 pass |

**这条 run 怎么配出来的（可以照抄）**：建 run 时 `variants=["xhs-author","zhihu-analyst","en-analyst"]`（`xhs` 出中文图文 + 卡片、`zhihu` 出中文长文、`en` 出英文 thread —— **三个变体是"一条 run 覆盖 6 个"的关键**，缺 `en` 就没有英文传播）、渠道保持 `["xiaohongshu","zhihu","bilibili"]`、闸门 understand 放 `continue`、publish 放 **`draft`**（§7.2 的示例 body 已按这个更新，§7.3 的警告照旧适用）。

**复核命令**（我跑过，输出与下面一致）：

```bash
R=var/runs/run_ec0f0e056f47
python3 -c "
import json
d = json.load(open('$R/run.json'))
a = [x for s in d['stages'] for x in s['artifacts']]
c = [x for s in d['stages'] for x in (s.get('checks') or [])]
print('run', d['status'], '| 6 段', [(s['id'], s['status']) for s in d['stages']])
print('登记产物', len(a), '| 带 url', sum(1 for x in a if x.get('url')))
print('check', sum(1 for x in c if x['state']=='pass'), 'pass /',
      sum(1 for x in c if x['state']=='fail'), 'fail /', sum(1 for x in c if x['state']=='run'), 'run')
"
#   run done | 6 段 [('intake','done'),('understand','done'),('article','done'),('poster','done'),('video','done'),('publish','done')]
#   登记产物 51 | 带 url 42
#   check 53 pass / 1 fail / 3 run

# 42 条 url 逐条取回（本机有 http_proxy 时务必 --noproxy）
python3 -c "
import json, subprocess
d = json.load(open('$R/run.json'))
urls = [x['url'] for s in d['stages'] for x in s['artifacts'] if x.get('url')]
bad = [u for u in urls if subprocess.run(['curl','-s','--noproxy','*','-o','/dev/null','-w','%{http_code}','-m','10','http://127.0.0.1:8000'+u],capture_output=True,text=True).stdout.strip() != '200']
print('带 url 产物', len(urls), '| 非 200:', bad or '无')
"
#   带 url 产物 42 | 非 200: 无
```

**但别把这次成功读成"从此稳定"** —— 三条限制必须一起说：

1. **不是一遍就过**：这条 run 是**第三次尝试**。前两次 `run_a4cd493515f8`（死在 `understand`）与 `run_87ff2439468a`（死在 `poster`）都被**外部重启**判成 `failed`，`error.code=INTERRUPTED`「后端进程重启，该运行已中止，产物保留在 run 目录」（我读了两条 run.json 确认原文）。新代码比旧行为诚实（不再留"永久 waiting + 假 204"的僵尸），但**在途 run 该废还是废** —— 没有恢复机制。
2. **社区运营是概率性成功，不是稳定性已解决**：同一段 `community.py` 在 `run_d76ca9da493e`（LLM 401 余额）与 `run_720e83bdae91`（输出截断成非法 JSON）都没出计划，在 `run_c5451b582400` 与这条出了。所以结论只能是"**可达**"，不是"必然"——与 §6.10 的判断一致。
3. **真实投递仍未验证**：闸门走的是 `draft`，`published=[]`；小红书渠道仍 `fail`（未登录、没扫码）。**这条 run 不能当"真投出去了"的证据用。**

**三个容易读错的数字**：

- **51 件登记 ≠ 51 件可点开**：带前端 `url` 的是 **42 件**；另外 **9 件登记了但没 url**（`digest.raw.json` / `xhs.raw.json` / `poster.spec.json` / `poster.spec.cover.json` / `video.report.json` / 3 个渠道的 `README.txt` / `community.plan.json`）—— 前端作品库里点不到。所以"dashboard 可见"的准确说法是 **42 件可点开**，不是 51 件。
- **磁盘 ≠ 登记**：该 run 目录磁盘上有 **143 个文件**，其中 **92 个未登记**（`intake/sections.json`、`intake/images/table-ed1.png`、`poster/*.html`、`*.render.json`、`video/{audio,clips,frames}/*`、各渠道 `export/*` 等）。登记的是产物的**子集**，这个子集可信（bytes 全等），但别把它读成"磁盘上有的前端都有"。
- **同一份知乎长文有三个字数**（口径不一致未修）：publish 闸门写「**3803 字**」= 全文**字符数**（我核过 `len(text)==3803`）、article check 写「**2378 字**」= **正文 CJK 字数**、`receipts.json` 的 `contentChars` 也是 3803。三个都对，混着读会以为是三个值；引用时必须写明口径。

> 本节数字的完整出处与逐条 HTTP 结果见 [`12-single-run-six-agents.md`](../apps/papercast-server/docs/12-single-run-six-agents.md) （§3 逐 Agent 证据、§6.2 51 件逐条可见性、§7 未验证清单）。**要复核这条 run，请以那篇 + `var/runs/run_ec0f0e056f47/run.json` 为准**；本文档只引用结论与关键数字。

### 6.10 社区运营能否产出取决于 LLM 配额（而它失败时不拖垮发布）

- **两类失败要分开归因**。`run_d76ca9da493e` 的社区计划失败是**环境原因、不是代码原因**：`LLMError: 401 {"type":"error","error":{"type":"CreditsError","message":"Insufficient balance"}}` —— 上游 LLM 通道**余额不足**，换任何提示词都救不回来；而 `run_720e83bdae91` 那次是**代码原因**（输出被截断成非法 JSON，跑的是修复前版本）。写结论时别把"余额不足"读成"这个模块不可靠"。
- **这一格对配额比其它模块更敏感**。它一次调用要产出 4–6 个社区各自的成稿文案 + 规矩 + 风险 + 互动口径 + 指标，输出体量在所有产物里最大：run 级那条的 `community.plan.json` 是 **21,481 B**，比同 run 的 `digest.json`（10,288 B）、`zhihu-analyst.md`（7,453 B）、`poster.spec.json`（5,392 B）都大。所以它既是**第一个撞上输出长度上限**的（截断 → 非法 JSON），也是**第一个把余额耗到 401** 的。这是"配额够不够"的问题，不是"设计对不对"的问题。
- **兜底是有效的**（两条失败 run 都能证明这一点）：社区失败时 `publish.py:395-404` 只把它记成**一条 check**，不抛给流水线。`run_720e83bdae91` 与 `run_d76ca9da493e` 两条 run 的 `run.status` 与 `publish.status` **至今都是 `done`**，10 个回执类产物照常落盘，其余渠道 check 照常逐条给出（小红书 `fail` / 知乎 `pass` / B站 `pass`）。也就是说：**社区运营挂了不会让"发布"这件事跟着挂** —— 这正是把它挂在 `publish` 尾部并做异常兜底的价值。
- **成功的样本现在有两个**：`run_c5451b582400` 与 `run_ec0f0e056f47`（§6.9）。四个样本连起来才是这条边界的完整图像：**2 成 2 败**，失败原因一个在环境（401）、一个在代码（截断）。所以"社区运营能不能出活"目前的答案仍是"**取决于配额，且带概率**"，不是"已稳定"；要提升稳定性，得从**缩小单次输出体量**或**更强的截断兜底**入手（本文档不修代码，只记现象）。

---

## 7. 复跑方法（含一条必须醒目的警告）

### 7.1 起服务

```bash
./ops/start_all.sh                 # 幂等：端口占用会跳过
curl -s http://127.0.0.1:8000/api/health
# 前端 http://127.0.0.1:5178 · 后端 :8000 · 小红书 MCP :18060
```

### 7.2 建 run（两种方式）

**方式 A · 命令行**（推荐先跑这个，每一步都看得见）：

```bash
UP=$(curl -sS -F file=@var/samples/deeprare.pdf http://127.0.0.1:8000/api/uploads \
     | python3 -c 'import json,sys; print(json.load(sys.stdin)["uploadId"])')

curl -sS -X POST http://127.0.0.1:8000/api/runs -H 'Content-Type: application/json' -d "{
  \"source\": {\"kind\": \"pdf\", \"value\": \"$UP\", \"title\": \"DeepRare\"},
  \"config\": {
    \"brief\": \"做成知乎长文，重点讲方法，不要营销腔\",
    \"article\": {\"variants\": [\"en-analyst\", \"zhihu-analyst\"]},
    \"publish\": {\"targets\": [\"xiaohongshu\", \"zhihu\", \"bilibili\"], \"autoPublish\": false}
  }
}" | python3 -m json.tool | head -20
```

（字段定义见 `apps/papercast-server/app/models.py:145-190`；变体 id 规则是 `{platform}-{voice}`，`styles.MAX_VARIANTS = 4`。想看等价的最小例子：`apps/papercast-server/scripts/smoke_test.sh`。）

> 上面这个配置就是 §6.9 说的"**单条 run 覆盖 6 个 Agent**"，而且**已经执行并成功过**：`run_ec0f0e056f47` 用的就是 `variants=["xhs-author","zhihu-analyst","en-analyst"]`（比本节示例多一个 `xhs-author`，用于出中文图文与卡片），六段全 done、51 件产物登记、42 件前端可点。**照本节这个 body 跑，等价配方也能一条覆盖 6 个**（少了 `xhs` 就没有小红书图文与卡片，其余 6 个 Agent 不受影响）——完整证据与限制见 §6.9。

**方式 B · 前端**：`http://127.0.0.1:5178` → 工作台 → 上传 PDF / 选平台与人格 → 建 run，之后看 6 段进度条。

### 7.3 两个闸门怎么点

| 闸门 | 出现在 | 选项 | 放行接口 |
| --- | --- | --- | --- |
| ① `digest`「确认论文理解层」 | `understand` 跑完、下游开始之前 | `continue` 确认并继续 / `revise` 补充要点后重跑（批注会追加进提示词） | `POST /api/runs/:id/stages/understand/gate {"optionId":"continue"}` |
| ② `publish-gate`「发布前人工闸门」 | `publish` 把素材包与渠道探测都做完之后 | `continue` **确认发布** / `draft` 仅存草稿 / `skip` 本轮不发布 | `POST /api/runs/:id/stages/publish/gate {"optionId":"draft"}` |

前端就是那两个按钮（闸门对象的 `options` 逐条渲染，见 `models.py:93-106`）；轮询或 SSE 都能等到 `run.status == "waiting"`。

> ## ⚠️ 不要给 `publish` 闸门发 `continue`
>
> `optionId: "continue"` 的字面意思是「确认发布」——**它真的会调用渠道接口把内容投出去**（`publish.py:298-300`：`confirmed = chosen not in ("draft","skip")` → `_deliver(...)`）。这个动作**不可逆**，而且有账号风险。
>
> - 只想看产物：发 `{"optionId":"draft"}`（只准备 `export/`，不调任何发布接口）；
> - 想跑脚本：用 `apps/papercast-server/scripts/smoke_test.sh`，它**发布闸门默认回 `draft`**，只有显式 `PUBLISH=1` 才真发（脚本第 34–40 行）；
> - 还有一层保险要小心：`ctx.gate()` 在拿不到选择时会退回 `options[0][0]`（`pipeline.py:143`），而 `publish-gate` 的 `options[0]` 正是 `continue`。**别为了"催一下"去乱发 gate 请求。**
> - `publish` 阶段还会检查历史投递：这个 run 已经投过时，会记一条 `check=run`「再点确认会重复投稿」（`publish.py:250-254`）。

### 7.4 复核本文档的每个数字

```bash
R=var/runs/run_720e83bdae91
python3 -c "
import json; d=json.load(open('$R/run.json'))
print('run', d['id'], d['status'], '登记产物', sum(len(s['artifacts']) for s in d['stages']))
for s in d['stages']: print(' ', s['id'], s['status'], len(s['artifacts']))
"
dump_stage understand   # §3 的通用函数；逐段换成 understand/article/poster/video/publish
find $R -type f | wc -l                              # 116（含 §3.6 直调写下的 2 个 community 产物）
ls -l $R/video/*.mp4 $R/poster/*.png $R/article/*.md
```

---

## 8. 核实清单（本文档每个数字的来源）

| 数字 / 结论 | 来源（我亲自读过或跑过） |
| --- | --- |
| `STAGE_ORDER` / `STAGE_META` / `IMPLEMENTED_STAGES` / `StageCheck` | `apps/papercast-server/app/models.py`（第 18、24–55、109–113 行） |
| 6 段 plan 与模块映射 | `apps/papercast-server/app/pipeline.py:253-260` |
| 各模块函数位置与行数 | `generate.py`（702 行）、`poster_stage.py`（380）、`poster.py`（560）、`video.py`（1438）、`community.py`（261）、`styles.py`（410）、`cards/render.py`（182） |
| `run_720e83bdae91` 的全部数字（6 段 done / 37 登记产物 / 116 个磁盘文件 / 每段 check 原文 / 每张画布的字号与 scale） | 我自己用 `python3` 读 `var/runs/run_720e83bdae91/run.json`、`video.report.json`、`poster-zhihu.render.json`，以及 `find` / `ls` 的输出 |
| `run_abb2805074e4` 的 brief 冲突两条 `fail` 与 34 个产物 | 同上，读该 run 的 `run.json` |
| video 的 ffprobe 原始数字（238.183203 / 6,255,515 / 5,794,539 / 76 个数字 / 8 条 check） | `apps/papercast-server/docs/10-module-video.md` §5.1–5.4 —— **文档转引，我没有亲自跑 ffprobe** |
| `run_720e83bdae91` 的 video 实测（269.10s / 70 个数字 / 25 条字幕 / 3 页配图） | `video/video.report.json` + 该 run 的 video checks |
| `brief_checks` 的"平台硬约束优先"新行为 | 读 `generate.py:54-117`、`prompts.py:84-101` —— **未复跑，标未验证** |
| `platform_menu()` 无生产调用方 | `grep -rn 'platform_menu' apps/ docs/ ops/` 的全部命中（定义 + 1 个单测 + 1 个手工脚本） |
| 社区运营的 **run 级**成功（6 社区 / 8,183 字 / 4 pass + 1 run / `community.md` 带前端 URL） | 我自己 `python3` 读 `var/runs/run_c5451b582400/run.json`（`publish` 段 12 个产物、逐条 artifact 的 `path`+`url`、5 条社区 check 原文）与 `publish/community{,.plan}.json`（21,454 B；6 个社区名、成稿 8,183 字） |
| 社区运营的 **模块级**证据与它"未登记"（3 社区 / 841 字） | 我自己读 `var/scratch/verify_community.py`（stub ctx 的 `check`/`artifact` 只 print）、`run_720e83bdae91/publish/community{,.plan}.json`（5,555 B / 66 行、5,246 B / 48 行），并**按 `community.py` 的同一口径自己复算**了 4 条 check（结论：社区覆盖 fail 3<4，其余 pass）；`run.json` mtime 仍是 02:00:05 证明它没被更新 |
| 社区失败是环境原因（401 余额）+ 兜底有效（不拖垮发布） | 我自己 `python3` 读 `run_d76ca9da493e/run.json` 与 `run_720e83bdae91/run.json`：两条的 `run.status` / `publish.status` 都是 `done`、`publish` 段各 10 个产物、社区那条 check 为 `fail`（detail 分别是 401 原文与非法 JSON 原文），其余渠道 check 逐条存在 |
| 社区计划是"输出体量最大的产物" | `ls -lS` 对比同 run 产物：`community.plan.json` 21,481 B > `digest.json` 10,288 B > `zhihu-analyst.md` 7,453 B > `poster.spec.json` 5,392 B |
| M1 图注失效 | `run_720e83bdae91` 的 intake check「4 张（fig 0 / table 0 / 未匹配 4）」+ `06-verification.md` §2 的 12 张对照 |

**曾经标为「未验证」、现在已验证并移出的一处**：

- ~~没有哪一条 run 单跑齐 6 个 Agent~~ → **已验证**：`run_ec0f0e056f47` 一条 run 覆盖 6 个 Agent（§6.9）。我自己复核过：51 件登记 / 42 件带 url 且 **42/42 HTTP 200** / 51 件磁盘 bytes 与登记值逐一相等 / check **53 pass · 1 fail · 3 run**。

**仍标为「未验证」的三处**：

1. brief 冲突判成 `run` 的**新**行为（`generate.py:69-77`，改动后未复跑）；
2. `pdf_parser.py` 未提交改动对图注匹配的实际效果（根因三条结论属**看板转引**，我未独立复核）；
3. 模块级直调那次的 check 状态**没有被持久化记录**——脚本只 print，所以"全 pass"这种说法无法从 run.json 复核；我按 `community.py` 的口径自行复算，得到的是 **社区覆盖 fail（3 < 4）+ 其余 3 条 pass**（与"全 pass"的转述不一致，以代码口径为准）。

另有两处**范围限制**（不是"未验证"，是"已验证但只能这么说"）：① **真实投递**在 `run_ec0f0e056f47` 上仍未验证（闸门走 `draft`、`published=[]`，小红书未登录），"6 个 Agent 覆盖"不等于"投出去了"；② 该 run 的**前端页面渲染**只验到"42 条 artifact url HTTP 200 + dashboard 页面 200"，6 张产物在 Vue 组件里长什么样没验。

另有一处**转引**：video 模块 CLI 的 ffprobe 原始输出（238.183203s 等）来自 `10-module-video.md` §5，不是我本人执行的。

---

## 9. 一页速查

| 总纲的 Agent | stage | 有真实产物？ | 一句话证据 |
| --- | --- | --- | --- |
| 论文解读 | `understand` | ✅ | 6 条贡献 / 12 条可回溯结果 / 笔记 14,023 字（`run_720e83bdae91`） |
| 可视化 | `poster`（+卡片） | ✅ | 4 张画布几何闸门 4/4 过，知乎横版自动砍 3 块；`run_abb2805074e4` 另出 4 张 3:4 卡片 |
| 中文传播 | `article` | ✅ | 知乎 2298 字 / 83 个数字可回溯；小红书 748–817 字 + 4 卡片 |
| 英文传播 | `article`（`en`） | ✅（后端） | `en-analyst.md` 443 词 / 58 个数字可回溯，2,859 B；**前端入口归前端 agent** |
| 视频化 | `video` | ✅ | 横 269.10s + 竖 269.12s + 封面 + 25 条字幕；独立实测 238.18s / 76 个数字全回溯 |
| 社区运营 | `publish` 尾部 | ✅ **run 级已跑通（验收依据）** | `run_c5451b582400`：`publish` 段 12 个产物，`community.md` **已登记且带前端 URL**；6 社区 / 8,183 字；check 4 pass + 1 run。补充证据：模块级直调（3 社区 / 841 字，未登记）；边界见 §6.7 / §6.10 |

> ✅ **一句话读法**：上表 6 行**已经由单条 run 同时满足** —— `run_ec0f0e056f47` 一条 run 里 6 个 Agent 的产物全部登记、全部落盘、**42 件前端可点开**（§6.9）。此前"两条 run 拼起来"的证据（`run_720e83bdae91` + `run_c5451b582400`）仍有效，作为对照列在 §4.3。
>
> ⚠️ 但两件事仍然成立：**社区运营是概率性成功**（同代码曾因 401 余额 / 输出截断失败过两次，§6.10），**真实投递仍未验证**（闸门走 `draft`，小红书未登录）。
