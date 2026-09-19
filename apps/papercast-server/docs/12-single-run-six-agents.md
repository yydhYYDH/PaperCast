# 12 · 一条 run 覆盖全部 6 个 Agent（run_ec0f0e056f47）

> 版本：R1 · 2026-09-19 · 跑测时间 02:45:27–02:55:57（CST，630s）
> 目的：补上 `docs/02-six-agents-coverage.md` §6.9 里标为「未验证」的那一格 —— **让总纲的 6 个 Agent 在同一条 run 里全部产出、全部登记、前端可见**。
> 本文只写这条真跑过的 run，所有数字来自 `var/runs/run_ec0f0e056f47/run.json` 与磁盘产物（§8 给原样复现命令）。
> **两次被外部重启杀死的失败尝试照实记在 §1.3**，没有为了好看把失败写成成功。

---

## 0. 一句话结论

**`run_ec0f0e056f47` 一条 run 就把 6 个 Agent 全覆盖了**：6 段全部 `done`（630s），**51 件产物登记在同一条 run 的 `run.json` 里**，其中 42 件带前端 `url` 且逐条返回 **HTTP 200**；不只是「登记」，磁盘上也都真在（51/51 件 bytes 与登记值逐一相等，§6.1）。

| # | Agent | 落在哪段 | 这条 run 里的实物（一句话） |
| --- | --- | --- | --- |
| 1 | 论文解读 | `understand` | `digest.json` 11,047 B：6 条贡献 / 12 条数值 **全部**可在原文检索 / 6 张图表选择 |
| 2 | 可视化 | `poster` + `article` 尾部 | 4 张画布 **2304×1728 / 1080×2400 / 1600×1200 / 1920×1080**，`overflow=[]` 4/4；另有 6 张 1080×1440 卡片 |
| 3 | 中文传播 | `article` | `xhs.md`（正文 830 字）+ `zhihu-analyst.md`（正文 2,378 字，96 个数字全回溯） |
| 4 | 英文传播 | `article` | `en-analyst.md` **428 词真英文 thread**（`1/10…10/10` + `## Tags`） |
| 5 | 视频化 | `video` | `video.mp4` **234.26s / 1920×1080 / h264+aac / 6,695,879 B**（+ 竖版 1080×1920 234.28s） |
| 6 | 社区运营 | `publish` | `community.md` 19,042 B + `community.plan.json` 18,905 B：**6 个社区**（zh×3 + en×3，含学术社区），成稿 **8,510 字符** |

**但有三件事必须一起说清**：① publish 段仍有 **1 条 fail**（小红书未登录，环境问题）与 **2 条 run**；② 社区运营是 **LLM 生成，成功带概率**（本文这次成功，历史上有同代码失败，见 §7.2）；③ 为了拿到这条 run，**前两次尝试被外部重启杀死了**（§1.3），这是 B1 的现场复现，不是配置错误。

---

## 1. run id 与配置

### 1.1 请求原样（建 run 的 body，与文档里的复现命令一字不差）

```http
POST /api/uploads  (multipart, 字段名 file)      -> 200 {"uploadId":"up_96c58bfae000","bytes":9891107,"sha256":...}
POST /api/runs
{
  "source": {"kind": "pdf", "value": "up_96c58bfae000", "title": "六 Agent 单 run 覆盖验证 deeprare"},
  "config": {
    "brief": "做成知乎长文，重点讲方法，不要营销腔",
    "article": {"variants": ["xhs-author", "zhihu-analyst", "en-analyst"]}
  }
}
```

服务端落下来的完整 config（`GET /api/runs/run_ec0f0e056f47` 的 `config` 字段，其余是默认值）：

```json
{"brief": "做成知乎长文，重点讲方法，不要营销腔",
 "article": {"variants": ["xhs-author", "zhihu-analyst", "en-analyst"]},
 "poster":  {"size": "36x48", "venue": "arXiv", "theme": "default", "lang": "zh"},
 "video":   {"durationSec": 180, "voice": "zh-CN-XiaoxiaoNeural", "aspect": "9:16", "narration": ""},
 "publish": {"targets": ["xiaohongshu", "zhihu", "bilibili"], "autoPublish": false}}
```

- 素材：`var/samples/deeprare.pdf`（9,891,107 B / 23 页 / sha256 前缀 `6bfc8640b11f24f8`）。
- 变体 3 个（`app/styles.py` 的 `MAX_VARIANTS = 4`，没超上限）：`xhs-author` = 中文传播 + 6 张卡片、`zhihu-analyst` = 中文长文、`en-analyst` = 英文 thread。**三个变体是「一条 run 跑齐 6 个 Agent」的关键**：没有 en 就没有英文传播，没有 zhihu/xhs 就没有中文传播。
- 闸门：`understand` 发 `{"optionId":"continue"}`（HTTP 204），`publish` 发 `{"optionId":"draft"}`（HTTP 204）。**全程没有对 publish 发过 `continue`，没有任何真实投递。**

### 1.2 服务与代码版本

| 事实 | 值 |
| --- | --- |
| 后端进程 | pid **10223**，启动 **02:42:23**（`Started server process [10223]`，`var/logs/backend.log` 第 1 行） |
| 我这条 run 的窗口 | 02:45:27 → 02:55:57，**进程全程没换过**（驱动的 uptime 采样一直单调增长，没有触发 `BACKEND-RESTART` 判定；跑完时 `/api/health` 的 `uptimeSec=929.7`） |
| `Exception in ASGI application`（B2） | `grep` 结果 **0 处**（02:41 之后的 `main.py` 已改成 `Response(status_code=204)`） |

**代码漂移（必须写在最前面，理由同 文档 11 §1.2）**：本机后端没有 `--reload`，「磁盘上的代码」≠「跑着的代码」。

| 文件 | 最后修改 | 相对我的 run（02:45:27 起） | 我的 run 跑的是哪版 |
| --- | --- | --- | --- |
| `app/main.py` | 02:37:05 | 早于 run | 就是这版（S1 的 B2 修复） |
| `app/pipeline.py` | 02:37:25 | 早于 run | 就是这版（S1 的 B1 fail-closed 修复） |
| `app/modules/publish.py` | 02:41:45 | 早于 run | 就是这版（S2 的 B3–B6 按渠道分发物料） |
| `app/modules/generate.py` | 02:35:54 | 早于 run | 就是这版（B6 的 words 按 unit 取口径） |
| `app/store.py` | **02:46:03** | **run 进行中** | **不是这版**：进程 02:42:23 启动，加载的是 02:38:30 那版；02:46:03 的改动**没进我的 run**（而且没有重启，所以也没杀掉它） |

sha256 快照（2026-09-19 02:58 复核时磁盘上的版本，前 16 位）：

```text
pipeline.py              a90f201e230dff59
modules/publish.py       6ab16a4676099b01
modules/generate.py      ce03917d43cadff6
modules/community.py     a05ffcf54d30e0ea
main.py                  5ba3c28323d26122
```

> 也就是说：这条 run 是**修完 B1/B2/B3–B6 之后**跑的（这是它比 文档 11 那三条 run 更「新」的地方），但 `store.py` 在 run 中途被改过而没生效 —— 复核时请先比 hash。

### 1.3 三次尝试：前两次被**外部重启**杀死（照实记，不美化）

这条 run 是第三次尝试。前两次都死在「别人重启后端」上（B1 的现场）：

| # | run id | 起跑 | 死在哪 | 死因原文 | 留下的产物 |
| --- | --- | --- | --- | --- | --- |
| 1 | `run_a4cd493515f8` | 02:33:35 | understand | `{"code":"INTERRUPTED","message":"后端进程重启，该运行已中止（产物保留在 run 目录）"}` | intake done（12 件）+ understand 有 2 件、3 条 check 已 pass 但没走完 |
| 2 | `run_87ff2439468a` | 02:36:36 | poster | 同上（一字不差的 INTERRUPTED） | intake done(12) / understand done(3) / article **done(12)** / poster failed(1) |
| 3 | **`run_ec0f0e056f47`** | 02:45:27 | —— | —— | **全 6 段 done，51 件登记产物** |

重启时刻（我的驱动抓到的原始记录）：`02:35:18`（pid 30886 → 6779）、`02:40:2x`（`uptimeSec 297.8 -> 5.3`）、`02:42:23`（→ pid 10223）。前两次重启发生在 S1/S2 两条修复轨道落地 B1/B2/B3–B6 的过程中，属于开发节奏，不是误操作；但代价是两条 run 全废（我按约定在看板喊过两次「请勿重启」，master 也在 02:41 复述过）。

**新代码的表现值得单独记一句**：重启不再把 run 变成 文档 11 §8-B1 那种「永久 waiting + 假成功 204 僵尸」，而是在启动时把在途 run 显式判成 `failed / INTERRUPTED`。**fail-closed 取代了 fail-open**：更诚实，但在途任务仍然全废（只是不再骗人）。

---

## 2. 六段总表（终态 + 产物 + check 分布）

**结论：6 段全部从 pending 走到 done，没有 skipped、没有 waiting 残留。**

| 阶段 | 终态 | 用时 | 登记产物 | 其中带 url | check pass/fail/run |
| --- | --- | --- | --- | --- | --- |
| intake | done | 17.6s | 12 | 12 | 4 / 0 / 0 |
| understand | done（**闸门 continue**） | 82.5s | 3 | 2 | 4 / 0 / 0 |
| article | done | 99.4s | 12 | 11 | 20 / 0 / 1 |
| poster | done | 59.8s | 6 | 4 | 7 / 0 / 0 |
| video | done | 165.8s | 6 | 5 | 8 / 0 / 0 |
| publish | done（**闸门 draft**） | 199.0s | 12 | 8 | 10 / 1 / 2 |
| **合计** | `run.status=done`，`error=null` | **630s** | **51** | **42** | **53 / 1 / 3** |

- 闸门原文：`understand` `askedAt=1789757223609` → `resolved="continue"`；`publish` `askedAt=1789757561354` → `resolved="draft"`。
- 唯一的 1 条 `fail` 是「渠道状态：小红书」（未登录，§7.3）；3 条 `run` 是「英文变体的指令侧重」「投递数据复盘」「发布结果（仅存草稿）」，都带 detail 说明，没有假装通过。
- 阶段推进的原始时间线（驱动日志 `var/scratch/verify6/verify6_verify6c.log` 第 6–21 行）：intake 20s → understand waiting@100s → done@110s → article done@200s → poster done@260s → video done@430s → publish waiting@440s → **done@630s**。

---

## 3. 6 个 Agent 的逐条证据

> 每一节都按同一口径给三列：**run.json 登记**（`stages[].artifacts[]`，前端读的就是它）、**磁盘存在**（登记 `path` 形如 `.papercast/runs/<id>/…`，实际落盘是 `var/runs/<id>/…`）、**原始字段**（尺寸/字数/几何闸门原文）。
> 「登记 ≠ 磁盘」这件事我单独核过：**51 件登记产物在磁盘上全部存在，且 bytes 与登记值逐一相等**（§6 的 51 行里带 `OK` 标记的都是这个结论）。

### 3.1 Agent 1 · 论文解读（`understand`）

闸门：`{"id":"digest","label":"确认论文理解层","options":["continue","revise"]}`，detail「下游小红书图文的数字与结论全部由这份事实源派生，确认贡献点与关键数据无误后再放行。」→ **continue**。

| 登记产物 | kind | 磁盘 | 原始字段 |
| --- | --- | --- | --- |
| `understand/digest.json`「digest.json（事实源）」 | json | 11,047 B == 登记值 | 贡献 **6** 条 / 结果 **12** 条 / 图表 **6** / 关键词 8 / 局限 6 / method 890 字 / abstractCn 489 字符 |
| `understand/digest.raw.json`「模型原始输出」 | json | 9,448 B == 登记值 | 无 url（前端不可见，见 §6） |
| `understand/reading_note.md`「中文精读笔记」 | markdown | 26,106 B == 登记值 | 13,389 字符 / 5,589 中文字 |

4 条 check 全 pass（原文）：

```text
pass | 事实源结构 | 6 条贡献 / 890 字方法说明
pass | 数值可回溯 | 12 条结果全部能在原文中检索到
pass | 图表选择   | 选定 6 张：fig-1, fig-2, fig-3, fig-5, fig-4, fig-ed1
pass | 精读笔记   | 13389 字
```

digest 第 1 条贡献原文：「提出DeepRare——一个由大语言模型驱动、专为罕见病鉴别诊断决策支持设计的多智能体系统，整合40多个专用工具与最新知识源。」

### 3.2 Agent 2 · 可视化（`poster` + `article` 的卡片）

**4 张画布 + 6 张卡片，全部登记。** 几何闸门原文（check 与 `*.render.json` 里的 `report` 一致）：

| 画布 | 像素 | 正文 px | scale | panel_fill | 溢出 | 文件 |
| --- | --- | --- | --- | --- | --- | --- |
| 会议海报 48×36in | **2304×1728** | 20.3 | 0.9061 | 0.9801 | `[]` | `poster.png` 1,026,451 B |
| 小红书/知乎竖长图 | **1080×2400** | 20.3 | 1.939 | 0.9444 | `[]` | `poster-xhs-long.png` 741,825 B |
| 知乎正文横版 | **1600×1200** | 18.2 | 1.1738 | 0.9792 | `[]` | `poster-zhihu.png` 611,446 B |
| B 站视频封面 | **1920×1080** | 41.2 | 2.2117 | null（cover 无正文栏） | `[]` | `poster-bili-cover.png` 938,456 B |

- 像素不是抄的：我用 PIL 直接读的 PNG 尺寸（2304×1728 / 1080×2400 / 1600×1200 / 1920×1080），与 `report.width/height` 一致。
- `overflow=[]` 也是双份证据：`*.render.json` 的顶层 `overflow` 与 `report.overflow` 都是 `[]`，`broken_images=[]`，**4/4 张 ok=true**。
- 知乎横版是**硬挤出来的**：`poster.spec.zhihu.trim1/2/3.json` 三个中间文件在磁盘上，check 原文「已按优先级砍掉 3 个次要块」；tries 序列 `1.4175✗(353) → 1.0631✓ → 1.2403✗(81) → 1.1517✓ → 1.196✗(35) → 1.1738✓ → 1.1849✗(3)`。
- B 站封面走的是「能放多大放多大」：`tries` 首轮 2.6 判 `ok=false (max_overflow=0)`（不是溢出，是 fit 判据），最后取 2.2117 ✓，h1 180px。
- 卡片：`article/cards/p1..p6.png` **6 张 1080×1440**（369,962 / 440,923 / 212,247 / 274,982 / 298,085 / 397,728 B），check `小红书 × 作者自述 · 卡片渲染 pass 6 张 3:4 卡片`。
- 未登记但落盘：`poster/*.html`（4 个渲染源）、`poster/*.render.json`（4 个几何自检）、`poster/figures/*.png`（2 张引用副本）—— 登记口径是「产物」，这些是中间物。

### 3.3 Agent 3 · 中文传播（`article`）

| 变体 | 登记产物 | 磁盘 | 正文字数（check 口径） | 其他 check |
| --- | --- | --- | --- | --- |
| 小红书 × 作者自述 | `article/xhs.md`（+ `xhs.raw.json`） | 3,783 B / 4,732 B，均等于登记值 | **830 字**（上限 1000） | 标题计重 **33**（上限 38）/ 无公式 pass / 标签 **12** 个 / 禁用表达 pass（未见「营销腔」）/ 侧重 pass（已体现：方法）/ 卡片渲染 pass |
| 知乎 × 技术解读 | `article/zhihu-analyst.md` | 8,563 B == 登记值 | **2,378 字**（要求 2000-4000） | 标题 13 字（≤40）/ 公式策略 pass / 标签 6 个 / 禁用表达 pass / 侧重 pass / **数字可回溯 96 个全过** |

出口物料也登记了：`article/export/title.txt` 45 B（`DeepRare 罕见病诊断智能体方法拆解`）+ `article/export/content.txt` 2,134 B。

> 口径提示（B8 未修，见 §7.5）：`xhs.md` 整文件是 1,935 字符（912 中文字），`zhihu-analyst.md` 整文件是 **3,803 字符**（2,378 中文字）。check 里的「830 字 / 2378 字」只算**正文**，publish 闸门里写的「3803 字」是**全文字符数**。三个数字指的不是同一件事。

### 3.4 Agent 4 · 英文传播（`article`）

`article/en-analyst.md` 2,702 B == 登记值，是真英文 thread（原文前 5 行，来自磁盘）：

```text
# DeepRare: an agentic LLM system for rare disease diagnosis, 57.18% mean Recall@1

1/10 DeepRare is a multi-agent LLM system that turns free text, HPO terms and VCFs into ranked rare-disease
diagnoses with cited reasoning. On HPO tasks it averages 57.18% Recall@1 across nine datasets, 23.79% above
the next best method.

2/10 Rare diseases affect over 300 million people worldwide. Diagnosis often takes more than 5 years...
```

结构核过：编号帖 `1/10 … 10/10` 十条齐全，且有 `## Tags` 英文标签段 —— **不是中文套壳**。

| check | state | detail |
| --- | --- | --- |
| 标题 | pass | 「DeepRare: an agentic LLM syste」= **80 字符**（上限 90） |
| 正文长度 | pass | **428 词**（要求 320-850，按 `words` 口径，不是 cjk_len） |
| 无公式 | pass | 未出现 LaTeX 表达 |
| 标签数量 | pass | 5 个（要求 3-6） |
| 指令遵从度 · 禁用表达 | pass | 未见 营销腔 |
| 指令遵从度 · 侧重 | **run** | 指令要求侧重「方法」，正文里未出现该词（可能换了说法，需人工看一眼） |
| 数字可回溯 | pass | 72 个数字全部可在事实源中回溯 |

**B6 已修的直接证据**：`run.json` 的 `articles` 里英文变体现在登记的是 `{"id":"en-analyst","platform":"en","voice":"analyst","words":428}`（文档 11 §8-B6 那条「英文恒为 0」在这条 run 上**已经不复现**）。

### 3.5 Agent 5 · 视频化（`video`）

6 件登记产物，全部磁盘对得上：`video-vertical.mp4` 5,882,820 B / `video.mp4` 6,695,879 B / `cover.png` 319,782 B / `narration.json` 5,414 B / `subtitles.srt` 3,265 B / `video.report.json` 1,385 B。ffprobe 真数字见 §5。

8 条 check 全 pass：横版/竖版可解码、**分镜数 10 页（要求 6–12，来源 llm，4 页配图）**、数字可回溯 57 个、字幕与音轨对齐（**24 条字幕，末条 232.51s / 视频 234.26s，偏差 1.75s**）、配音（10 页全用 `zh-CN-XiaoxiaoNeural` 真 TTS）、**时长 pass 234.3s（目标 180s，旁白 1,166 字）**（这条在文档 11 的 run 里是 run/fail，这次落在阈值内）、封面 1920×1080 312 KB。

`video.report.json` 原始字段：`ttsMode="edge-tts"`、`plannedSec=234.24 → totalSec=234.26`（分段之和与拼接实测一致）、`slides=10`、`pagesWithFigure=4`、`storyboard="llm"`、`ffmpeg version 9.0.1`（`var/toolchains/p2b/bin/ffmpeg`）。

### 3.6 Agent 6 · 社区运营（`publish` 尾部）

这一格就是本文要补的「未验证」：**它在同一条 run 里真的跑出来了**。

| 登记产物 | 磁盘 | 原始字段 | 前端 |
| --- | --- | --- | --- |
| `publish/community.md`「社区投放计划（含每个社区的成稿文案）」 | 19,042 B == 登记值 | 11,789 字符 / 3,609 中文字 / 8 个 @@BT##@@ 小节 | `url=/artifacts/run_ec0f0e056f47/publish/community.md` → **HTTP 200** |
| `publish/community.plan.json`「社区投放计划（结构化）」 | 18,905 B == 登记值 | 顶层键 `["communities","interaction"]` | **无 url**（后端没暴露，见 §7.7） |

`community.md` 的 8 个小节标题（原文）：`## 1. 知乎（中文社区 · zh）` / `## 2. 小红书（社交平台 · zh）` / `## 3. B站（中文社区 · zh）` / `## 4. Reddit r/MachineLearning（学术社区 · en）` / `## 5. Hacker News（垂直社区 · en）` / `## 6. X（社交平台 · en）` / `## 互动与复盘` / `## 已发布数据（真实回执，取不到就说取不到）`。

**社区数与成稿字数（从 `community.plan.json` 逐社区复算，不是抄 check）**：

| 社区 | 类型 | 语言 | 成稿 draftBody | draftTitle |
| --- | --- | --- | --- | --- |
| 知乎 | 中文社区 | zh | 2,371 字符 / 1,230 中文字 | DeepRare：用多智能体+可追溯推理做罕见病诊断，HPO 任务平均 Recall@1 57.18% |
| 小红书 | 社交平台 | zh | 504 字符 / 263 中文字 | 罕见病诊断 AI 论文拆解：多智能体+可追溯推理 |
| B站 | 中文社区 | zh | 533 字符 / 250 中文字 | DeepRare 论文拆解：多智能体如何做罕见病诊断 |
| Reddit r/MachineLearning | 学术社区 | en | 2,950 字符 / 0 中文字 | [R] DeepRare: An agentic system for rare disease diagnosis with traceable reasoning (arXiv preprint) |
| Hacker News | 垂直社区 | en | 753 字符 / 0 中文字 | DeepRare: An agentic system for rare disease diagnosis with traceable reasoning |
| X | 社交平台 | en | 1,399 字符 / 0 中文字 | DeepRare: agentic system for rare disease diagnosis |
| **合计** | | zh×3 + en×3 | **8,510 字符 / 1,743 中文字** | 每个社区另有 `rules`（软性规矩，46–64 字符）、`bestTime`、`risk` 三段 |

### 3.7 顺带核到的 publish 物料分发（B3–B6 修复在真实 run 上的效果）

闸门 detail 原文（我按 `draft` 放行前抓的，一字未改）：

```text
本次发布计划（每个渠道相互独立，一个失败不影响其它）：
· 小红书：投不了（login_required）—— MCP 在线，但当前未登录（或登录已失效）；文案「DeepRare 罕见病诊断智能体方法拆解」[变体 xhs]
· 知乎：将投递 长文（3803 字 + 6 张配图）；视频通道未接，只投文字与配图，账号 YYDH；文案「DeepRare：多智能体系统将HPO诊断Recall@1提升至57.18%」[变体 zhihu-analyst]
· B站：将投递 视频投稿（video-vertical.mp4 / 封面 有 / 12 个标签），账号 YYDH54；文案「DeepRare 罕见病诊断智能体方法拆解」[兜底变体 xhs（B站 没有专属变体）]
所有渠道的素材包都已落在 publish/<渠道>/export/，即使全部投递失败也能手动发布。
```

`publish/receipts.json` 里逐渠道的 `variant` 字段（这是 文档 11 §8-B3「知乎拿到小红书文案」修好后的样子）：

```text
material : variant=xhs  contentChars=830  imageCount=6  video=video-vertical.mp4
xiaohongshu: variant=xhs            contentChars=830   （= xhs 正文）
zhihu      : variant=zhihu-analyst  contentChars=3803  （= 知乎长文全文，不再是 921 字的小红书文案）
bilibili   : variant=xhs（兜底）     contentChars=830
published=[]  failed=[]  blocked=[]      <- 没有任何真实投递
```

磁盘上每个渠道各自一份素材包（`publish/<渠道>/export/` 13 个文件/渠道：`title.txt content.txt tags.txt cover.png p1..p6.png video.mp4 publish_request.json README.txt`），知乎那份还额外同步了一份到 `var/artifacts/zhihu/export/run_ec0f0e056f47/`（`exports.json` 的 `remote.ok=true`）。

---

## 4. 社区运营在这一条 run 里的 check 原文（逐条 label / state / detail）

出处：`run.json` → `stages[publish].checks`，13 条全列，社区相关的 4 条在最后（前面是投递侧，为完整起见一起给）：

```text
[pass] 素材适配：小红书 | 视频笔记
[fail] 渠道状态：小红书 | MCP 在线，但当前未登录（或登录已失效）
[pass] 素材适配：知乎   | 长文（3803 字 + 6 张配图）；视频通道未接，只投文字与配图
[pass] 渠道状态：知乎   | 账号 YYDH（通道在线，已登录：YYDH（yydh-75））
[pass] 素材适配：B站    | 视频投稿（video-vertical.mp4 / 封面 有 / 12 个标签）
[pass] 渠道状态：B站    | 账号 YYDH54（通道在线，已登录：YYDH54（biliup=.../bili-venv/bin/biliup））
[pass] 可投递渠道       | 知乎、B站
[pass] 社区覆盖         | 6 个社区（语言 en/zh）；是否含学术社区：True
[pass] 草稿可用         | 6 份草稿都可直接发布
[pass] 社区规矩         | 每个社区都写清了该社区的投放规矩
[pass] 数字可回溯       | 社区文案里的数字都能在事实源里找到
[run ] 投递数据复盘     | 暂无可读回数据：渠道接口没有返回任何已投递条目（可能还没投过东西）
[run ] 发布结果         | 仅存草稿（素材包已就绪）
```

- **社区覆盖 pass = 6 个社区（语言 en/zh）+ 含学术社区 True**；我另外从 `community.plan.json` 复算：6 个社区、成稿合计 **8,510 字符 / 1,743 中文字**（§3.6 表）。
- **草稿可用 pass = 6 份草稿都可直接发布**；**社区规矩 pass**；**数字可回溯 pass**。
- 两条 `run` 都不是失败：`投递数据复盘` 取不到回执数据（因为没真投），`发布结果` 明确写「仅存草稿」—— 这是 **draft 闸门的预期状态**，不是隐瞒。
- 与前序 run 的对照：同代码下 `run_d76ca9da493e`（LLM 401 余额）与 `run_720e83bdae91`（模型输出截断成非法 JSON）都**没出社区计划**，`run_c5451b582400` 出了。这次也出了 —— **结论只能是「这次成功」，不能说「必然成功」**。

---

## 5. 二进制真数字（ffprobe / 画布像素 / overflow）

### 5.1 ffprobe（我自己又跑了一遍 ffprobe，不是读 `video.report.json`）

```text
$ var/toolchains/p2b/bin/ffprobe -v error -show_entries format=duration,size,bit_rate,format_name \
    -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels \
    -of default=noprint_wrappers=1 var/runs/run_ec0f0e056f47/video/video.mp4
codec_name=h264  codec_type=video  width=1920  height=1080  r_frame_rate=25/1
codec_name=aac   codec_type=audio  sample_rate=44100  channels=2
format_name=mov,mp4,m4a,3gp,3g2,mj2
duration=234.263203   size=6695879   bit_rate=228661

$ 同上 var/runs/run_ec0f0e056f47/video/video-vertical.mp4
codec_name=h264  codec_type=video  width=1080  height=1920  r_frame_rate=25/1
codec_name=aac   codec_type=audio  sample_rate=44100  channels=2
duration=234.280000   size=5882820   bit_rate=200881
```

| 文件 | 分辨率 | 时长 | 编码 | 码率 | 大小 |
| --- | --- | --- | --- | --- | --- |
| `video/video.mp4` | 1920×1080 @25fps | **234.263203s** | h264 + aac 44.1kHz 立体声 | 228,661 bps | 6,695,879 B / 6.39 MB |
| `video/video-vertical.mp4` | 1080×1920 @25fps | **234.280000s** | h264 + aac 44.1kHz 立体声 | 200,881 bps | 5,882,820 B / 5.61 MB |

### 5.2 poster 四张画布的像素与 overflow（PIL 读像素 + render.json 读几何）

```text
poster/poster.png             PIL=2304x1728  preset=conf        ok=True overflow=[] overflow(report)=[] broken_images=[] panels=7  fill=0.9801 scale=0.9061 body=20.3px
poster/poster-xhs-long.png    PIL=1080x2400  preset=xhs-long    ok=True overflow=[] overflow(report)=[] broken_images=[] panels=6  fill=0.9444 scale=1.939  body=20.3px
poster/poster-zhihu.png       PIL=1600x1200  preset=zhihu       ok=True overflow=[] overflow(report)=[] broken_images=[] panels=4  fill=0.9792 scale=1.1738 body=18.2px（已砍 3 个次要块）
poster/poster-bili-cover.png  PIL=1920x1080  preset=bili-cover  ok=True overflow=[] overflow(report)=[] broken_images=[] panels=2  fill=null   scale=2.2117 h1=180px
```

=> **4/4 张 `overflow=[]`、`broken_images=[]`、`ok=true`**，与段内 check「几何闸门 pass 4/4 张画布无溢出」一致。

---

## 6. 前端可见性（逐条 HTTP + 六段状态 + 产物总数）

**口径**：与 dashboard 同源的后端 API（`GET /api/runs/{id}` 拿到的 `url`），逐条本地取回（本机设了 `http_proxy`，等价于 `curl --noproxy '*'`）。

### 6.1 总账

| 项 | 值 |
| --- | --- |
| 六段状态 | `intake:done understand:done article:done poster:done video:done publish:done`（`run.status=done`，`error=null`） |
| 产物总数 | **登记 51 件**（`stages[].artifacts[]`），其中**带 url 42 件** |
| HTTP 结果 | 42/42 全 **200**，content-type 与扩展名语义一致（`image/png` / `text/markdown` / `application/json` / `application/octet-stream` 给 mp4/pdf/srt） |
| 磁盘一致性 | 51/51 件按登记 `path` 在磁盘上存在，bytes 与登记值**逐一相等** |
| 无 url 的 9 件（含 2 个 spec） | 后端未暴露 url（`digest.raw.json / xhs.raw.json / poster.spec.json / poster.spec.cover.json / video.report.json / 3×README.txt / community.plan.json`）—— **这些在前端作品库里点不到**（§7.7） |
| dashboard 入口 | `GET http://127.0.0.1:5178/` → **HTTP 200 text/html**；`GET http://127.0.0.1:5178/api/runs/run_ec0f0e056f47`（Vite 代理到后端）→ **HTTP 200** |

### 6.2 逐条结果（51 件全列，`200` 是带 url 的、`--` 是后端没给 url 的）

```text
  200  | application/octet-stream         |   9891107 | /artifacts/run_ec0f0e056f47/intake/paper.pdf
  200  | text/markdown; charset=utf-8     |    125310 | /artifacts/run_ec0f0e056f47/intake/content.md
  200  | application/json; charset=utf-8  |       456 | /artifacts/run_ec0f0e056f47/intake/meta.json
  200  | application/json; charset=utf-8  |      5202 | /artifacts/run_ec0f0e056f47/intake/figures.json
  200  | image/png                        |    465971 | /artifacts/run_ec0f0e056f47/intake/images/fig-1.png
  200  | image/png                        |    203835 | /artifacts/run_ec0f0e056f47/intake/images/fig-2.png
  200  | image/png                        |    434925 | /artifacts/run_ec0f0e056f47/intake/images/fig-3.png
  200  | image/png                        |    317044 | /artifacts/run_ec0f0e056f47/intake/images/fig-4.png
  200  | image/png                        |    215072 | /artifacts/run_ec0f0e056f47/intake/images/fig-5.png
  200  | image/png                        |   3773853 | /artifacts/run_ec0f0e056f47/intake/images/fig-ed1.png
  200  | image/png                        |    394268 | /artifacts/run_ec0f0e056f47/intake/images/fig-ed2.png
  200  | image/png                        |    949350 | /artifacts/run_ec0f0e056f47/intake/images/fig-ed3.png
  200  | application/json; charset=utf-8  |     11047 | /artifacts/run_ec0f0e056f47/understand/digest.json
  --   (无 url) | 模型原始输出 digest.raw.json                 | .papercast/runs/run_ec0f0e056f47/understand/digest.raw.json
  200  | text/markdown; charset=utf-8     |     26106 | /artifacts/run_ec0f0e056f47/understand/reading_note.md
  200  | text/markdown; charset=utf-8     |      3783 | /artifacts/run_ec0f0e056f47/article/xhs.md
  --   (无 url) | 小红书 × 作者自述 文案原始输出                      | .papercast/runs/run_ec0f0e056f47/article/xhs.raw.json
  200  | text/plain; charset=utf-8        |        45 | /artifacts/run_ec0f0e056f47/article/export/title.txt
  200  | text/plain; charset=utf-8        |      2134 | /artifacts/run_ec0f0e056f47/article/export/content.txt
  200  | image/png                        |    369962 | /artifacts/run_ec0f0e056f47/article/cards/p1.png
  200  | image/png                        |    440923 | /artifacts/run_ec0f0e056f47/article/cards/p2.png
  200  | image/png                        |    212247 | /artifacts/run_ec0f0e056f47/article/cards/p3.png
  200  | image/png                        |    274982 | /artifacts/run_ec0f0e056f47/article/cards/p4.png
  200  | image/png                        |    298085 | /artifacts/run_ec0f0e056f47/article/cards/p5.png
  200  | image/png                        |    397728 | /artifacts/run_ec0f0e056f47/article/cards/p6.png
  200  | text/markdown; charset=utf-8     |      8563 | /artifacts/run_ec0f0e056f47/article/zhihu-analyst.md
  200  | text/markdown; charset=utf-8     |      2702 | /artifacts/run_ec0f0e056f47/article/en-analyst.md
  200  | image/png                        |   1026451 | /artifacts/run_ec0f0e056f47/poster/poster.png
  200  | image/png                        |    741825 | /artifacts/run_ec0f0e056f47/poster/poster-xhs-long.png
  200  | image/png                        |    611446 | /artifacts/run_ec0f0e056f47/poster/poster-zhihu.png
  200  | image/png                        |    938456 | /artifacts/run_ec0f0e056f47/poster/poster-bili-cover.png
  --   (无 url) | 版面描述 poster.spec.json（可复现、可换后端重排）      | .papercast/runs/run_ec0f0e056f47/poster/poster.spec.json
  --   (无 url) | 封面版面描述                                 | .papercast/runs/run_ec0f0e056f47/poster/poster.spec.cover.json
  200  | application/octet-stream         |   5882820 | /artifacts/run_ec0f0e056f47/video/video-vertical.mp4
  200  | application/octet-stream         |   6695879 | /artifacts/run_ec0f0e056f47/video/video.mp4
  200  | image/png                        |    319782 | /artifacts/run_ec0f0e056f47/video/cover.png
  200  | application/json; charset=utf-8  |      5414 | /artifacts/run_ec0f0e056f47/video/narration.json
  200  | application/octet-stream         |      3265 | /artifacts/run_ec0f0e056f47/video/subtitles.srt
  --   (无 url) | 合成报告 video.report.json                 | .papercast/runs/run_ec0f0e056f47/video/video.report.json
  200  | application/json; charset=utf-8  |       982 | /artifacts/run_ec0f0e056f47/publish/xiaohongshu/receipt.json
  200  | text/plain; charset=utf-8        |        46 | /artifacts/run_ec0f0e056f47/publish/xiaohongshu/export/title.txt
  --   (无 url) | 小红书 · 手动发布指引                           | .papercast/runs/run_ec0f0e056f47/publish/xiaohongshu/export/README.txt
  200  | application/json; charset=utf-8  |       785 | /artifacts/run_ec0f0e056f47/publish/zhihu/receipt.json
  200  | text/plain; charset=utf-8        |        65 | /artifacts/run_ec0f0e056f47/publish/zhihu/export/title.txt
  --   (无 url) | 知乎 · 手动发布指引                            | .papercast/runs/run_ec0f0e056f47/publish/zhihu/export/README.txt
  200  | application/json; charset=utf-8  |       907 | /artifacts/run_ec0f0e056f47/publish/bilibili/receipt.json
  200  | text/plain; charset=utf-8        |        46 | /artifacts/run_ec0f0e056f47/publish/bilibili/export/title.txt
  --   (无 url) | B站 · 手动发布指引                            | .papercast/runs/run_ec0f0e056f47/publish/bilibili/export/README.txt
  200  | application/json; charset=utf-8  |      3480 | /artifacts/run_ec0f0e056f47/publish/receipts.json
  200  | text/markdown; charset=utf-8     |     19042 | /artifacts/run_ec0f0e056f47/publish/community.md
  --   (无 url) | 社区投放计划（结构化）                            | .papercast/runs/run_ec0f0e056f47/publish/community.plan.json
```

---

## 7. 不准 / 没验 / 照实写的问题

### 7.1（已复现，非本 run 的 bug）两次尝试被外部重启杀掉

见 §1.3。B1（`pipeline._tasks` 只在内存里）**仍然存在**：重启后没有任何恢复机制能把在途 run 接回去。新代码把结果从「永久 waiting 假成功」改成「显式 failed / INTERRUPTED」，比原来诚实，但**在途任务该废还是废**。这条 run 能成功，一部分原因是运气（第三跑时上游修复轨道刚好停手）。

### 7.2 社区运营是**概率性**的，不能说「稳定可用」

同一段 `community.py`（`a05ffcf5`）、同一份厚素材，历史上 `run_d76ca9da493e` 与 `run_720e83bdae91` 都没出计划（LLM 401 / 输出被截断成非法 JSON），`run_c5451b582400` 与本文这条出了。本文只能下这个结论：**「一条 run 里跑齐 6 个 Agent」现在是被证明可达的，不是每次必然**。

### 7.3 小红书渠道仍然 fail（环境，不是代码）

`渠道状态：小红书 fail = MCP 在线，但当前未登录（或登录已失效）`。本文**没有登录小红书、没有点过二维码、没有发过 `continue`**。注意别把「素材适配：小红书 pass（视频笔记）」读成「小红书能用」—— 那是素材适配，与登录态是两条独立 check。

### 7.4 publish 段 2 条 `run`

「投递数据复盘」「发布结果（仅存草稿）」按设计就是 `run`（draft 闸门没真投）。**这不影响 6 个 Agent 的产物结论**，但也**不构成「真投递成功」的证据**。

### 7.5 字数口径不一致（B8 未修）：同一个产物三个数字

- publish 闸门：「知乎：将投递 长文（**3803 字** + 6 张配图）」
- article check：「知乎 × 技术解读 · 正文长度 **2378 字**（要求 2000-4000）」
- `receipts.json`：`zhihu.contentChars=3803`

3803 是 `article/zhihu-analyst.md` 的**全文字符数**，2378 是**正文字数（cjk 口径）**。三个数字都对，但混着读会得出「同一件事三个值」的错觉。文档 11 §8-B8 已记过这类口径不一致，**这条 run 上仍未修**。

### 7.6 「登记 ≠ 磁盘」的真实边界

- 登记 51 件 → 磁盘上全在，bytes 全等（**登记的子集是可信的**）。
- 但磁盘上有 **143 个文件**，即 **92 个文件没登记**：`intake/sections.json`、`intake/images/table-ed1.png`（intake check 说抽了 9 张图，只登记了 8 张，table-ed1 在磁盘、不在 `artifacts`）、`poster/*.html` 与 `*.render.json`、`poster/figures/*`、`video/{audio,clips,frames}/*`（10 页的 mp3/srt/clip/帧共 43 个）、`publish/<渠道>/export/*`（39 个）。
- 也就是说：**「前端可见」= 那 42 件**，不是磁盘上的全部。

### 7.7 9 件已登记产物没有 url

`digest.raw.json`、`xhs.raw.json`、`poster.spec.json`、`poster.spec.cover.json`、`video.report.json`、三个渠道的 `README.txt`、`community.plan.json`。后端对 `url` 的暴露是有选择的（JSON 中间物多数不给），所以「登记了」不等于「前端点得到」。

### 7.8 版本漂移（本次没有毁掉结论，但必须记）

`app/store.py` 在 **02:46:03**（我的 run 进行中）被改过，进程没重启 → **我的 run 跑的是 02:38:30 那版 store.py**。其余关键模块（`main.py 02:37:05 / pipeline.py 02:37:25 / publish.py 02:41:45 / generate.py 02:35:54`）都早于进程启动（02:42:23），所以跑的就是磁盘上那版。复核请用 §1.2 的 sha256 前缀比对。

### 7.9 未验证清单（不含糊其辞）

1. **真实投递**：全程只发 `draft`，`published=[]`。知乎/B 站「真能投出去」**没有验证**，也不要当成验证过。
2. **小红书登录与投稿**：需要人工扫码，本文没做。
3. **前端页面渲染**：只验了「artifact url HTTP 200」与「dashboard 页面 200 + Vite 代理 API 200」；6 条产物在 Vue 组件里渲染成什么样（海报真图、视频播放器）不在本文范围。
4. **社区运营的稳定性**：见 §7.2，单次成功不构成稳定性证据。
5. **并发压力**：本次跑期间工作区还有别的 track 在跑（02:38 master 报「5 条 running」），但未做资源争用压测；LLM 侧这次没遇到限流。
6. **LaTeX / OCR 通道**：本机无 TeX 引擎、无 tesseract，这条 run 是 PDF 通道。
7. **卡片数量不是固定契约**：这条 run 的 xhs 卡片是 **6 张**，文档 11 记的同类 run 是 4 张（由 LLM 决定篇幅）。别把 4 当契约。

---

## 8. 复现方式

```bash
# 1) 起后端（幂等）。注意本机设了 http_proxy，所有 localhost 调用都要 --noproxy
./ops/start_all.sh backend
curl -s --noproxy '*' http://127.0.0.1:8000/api/health

# 2) 跑这条 run（自动放行 understand=continue、publish=draft；绝不发 continue 给 publish）
#    驱动是我自己的副本，不改别人文件：var/scratch/verify6/run6_single.py
python3 -u var/scratch/verify6/run6_single.py var/samples/deeprare.pdf \
  "xhs-author,zhihu-analyst,en-analyst" "做成知乎长文，重点讲方法，不要营销腔" verify6c
#    日志： var/scratch/verify6/verify6_verify6c.log（状态变化 + 闸门 askedAt/options/detail + 每条 check + 产物清单）
#    快照： var/scratch/verify6/snapshots/*.json（每次状态变化一份 run.json）

# 3) 复核全部数字（只读；自己写的收集器，不改别人的 collect.py）
python3 var/scratch/verify6/evidence6.py run_ec0f0e056f47
#    输出 6 节：§A 六段终态 / §B 6 Agent 登记 vs 磁盘 / §C 逐条前端可见性 / §D ffprobe 与像素 / §E 逐段 check 原文 / §F 社区统计
#    落盘： var/scratch/verify6/evidence_run_ec0f0e056f47.txt

# 4) 自己再 ffprobe 一遍
var/toolchains/p2b/bin/ffprobe -v error -show_entries format=duration,size,bit_rate \
  -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels \
  -of default=noprint_wrappers=1 var/runs/run_ec0f0e056f47/video/video.mp4
```

### 产物路径速查（`<runId>` = `run_ec0f0e056f47`）

```text
var/runs/<runId>/run.json                         六段状态 + checks + 闸门 + 51 件产物登记（唯一事实源）
var/runs/<runId>/understand/{digest.json,digest.raw.json,reading_note.md}        <- Agent 1
var/runs/<runId>/poster/{poster,xhs-long,zhihu,bili-cover}.png + *.render.json   <- Agent 2
var/runs/<runId>/article/{xhs.md,xhs.raw.json,cards/p1..p6.png}                  <- Agent 3（小红书）
var/runs/<runId>/article/zhihu-analyst.md                                        <- Agent 3（知乎）
var/runs/<runId>/article/en-analyst.md                                           <- Agent 4
var/runs/<runId>/video/{video.mp4,video-vertical.mp4,cover.png,narration.json,subtitles.srt,video.report.json}  <- Agent 5
var/runs/<runId>/publish/{community.md,community.plan.json}                      <- Agent 6
var/runs/<runId>/publish/{receipts.json,exports.json,<渠道>/receipt.json,<渠道>/export/*}
```

---

## 9. 与相邻文档的关系（一处更正）

- `docs/02-six-agents-coverage.md` §6.9 说「没有哪一条 run 单跑齐 6 个 Agent，合并跑（variants 同时放 en-analyst + zhihu-analyst）我没执行，标未验证」—— **本文把这一格补上了**：`run_ec0f0e056f47` 一条 run 里 6 个 Agent 的产物全部登记、全部落盘、42 件前端可点。
- 本文不替代 `apps/papercast-server/docs/11-verification-6-stages.md`：那篇验的是「6 个阶段能否跑到终态 + 已知 bug 清单」，本文只回答「6 个 Agent 能否在同一条 run 里全部出活」。两篇的 run 清单不重叠。
- 本文**没有改任何 `app/` 代码**（只写了这一份文档 + 自己名下的 `var/scratch/verify6/` 脚本），发现的问题（§7）只记录、不修。
