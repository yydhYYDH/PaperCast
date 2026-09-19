# 10 · 视频讲解模块（digest → 真出 mp4）

> 对应 L2 生成层：`video` 阶段。**模块已完成、已接线、双路验证通过。**
> 版本：R1 · 2026-09-19 · 状态：横版 + 竖版 + 封面 + 字幕全部实测通过；本文所有数字都来自真实 run。
> 编号说明：组件内 docs 的 08 / 09 已被渠道与文风两条轨道占用，本文排到 10。

---

## 1. 一句话结论

**讲解视频不是"文生视频"，是"确定性排版 + 真 TTS + CPU 编码"。**

| 想要的东西 | 本质 | 需要 GPU / 文生视频模型吗 | 本仓库怎么出 |
| --- | --- | --- | --- |
| 论文讲解 mp4（会念、有字幕、带配图） | 分镜排版 + 语音合成 + 拼接 | ❌ 不需要 | `app/modules/video.py` |
| 视频封面 | 排版合成（PIL） | ❌ 不需要 | 同上，`render_cover()` |
| "重画一张好看的画面" | 真·文生图/文生视频 | ✅ 需要 | 不在本模块（见 07 的路线 C） |

这条分工和 07 的 ADR #5 是同一条：**论文内容用排版保证准确，创作型视觉才交给模型。**
视频里出现的每一句话、每一个数字，都来自 `understand/digest.json`（M2 已做过原文回溯校验）——
本模块只做"怎么讲"，不做"讲什么"。

## 2. 入口、读写边界与产物

**入口签名**（已接进 `app/pipeline.py` 的 plan：`("video", run_video)`）：

```python
async def run_video(ctx: StageContext) -> None
```

**读**（只有这三处，别的一律不读）：

| 来源 | 用途 |
| --- | --- |
| `<run>/understand/digest.json` | 唯一事实源（优先用 `ctx.run.digest` 内存对象，没有才回落到文件） |
| `<run>/intake/images/` | 论文原图（优先配图） |
| `<run>/article/cards/` | 小红书卡片（没有原图可选时才用） |

**写**：全部落在 `ctx.work` 里（`ctx.work` 就是 `<run>/video`，模块不自己拼 run 路径）：

```
understand/digest.json（事实源，唯一）   intake/images/（论文原图）   article/cards/（小红书卡片）
              └──────── LLM 分镜（6–12 页，逐句反幻觉校验；无 LLM 时确定性兜底；拼 config.brief）────────┘
                                       ↓
        frames/pNNN.png  ← PIL 画 1920×1080（标题 + 要点 + 配图，CJK 字体）
                                       ↓
        audio/pNNN.mp3 + audio/pNNN.srt  ← edge-tts（音色来自 config.video.voice）
                                       ↓  ffprobe 取真实时长
        clips/pNNN.mp4  ← ffmpeg -loop 1 -i frame.png -i page.mp3 -shortest（yuv420p / faststart）
                                       ↓  concat（先 stream copy，时长不符再重编码）
                                   video.mp4
                                       ↓  一次滤镜：模糊放大的原帧打底 + 居中卡片 + 白边
                              video-vertical.mp4
```

| 产物（`ctx.artifact` 的 rel 相对 `ctx.work`） | kind | 规格 |
| --- | --- | --- |
| `video.mp4` | `video` | 1920×1080 · H.264 High · AAC LC 44.1k 立体声 · faststart |
| `video-vertical.mp4` | `video` | 1080×1920 · 同上 |
| `cover.png` | `image` | 1920×1080 封面（大标题 + 论文题 + 主图） |
| `narration.json` | `json` | `{title, totalSec, slides[{index,title,bullets,narration,durationSec}]}`，与 `var/runs/run_a7b9460d3953/video/narration.json` 同构 |
| `subtitles.srt` | `text` | 句级时间戳，与配音逐句对齐 |
| `video.report.json` | `json`（`preview=False`） | 工具链版本 / ffprobe 实测 / 字体 / 丢弃记录 —— 验收证据 |

> ⚠️ **产物 rel 的坑**：`StageContext.artifact(kind, label, rel)` 里的 `rel` 是**相对阶段目录**（`ctx.work`＝`<run>/video`），
> 所以本模块传的是 `"video.mp4"` / `"cover.png"`。**不要**传 `"video/video.mp4"`——那样它按 `ctx.work/video/video.mp4` 找不到文件，
> 会被判成"产物缺失"而**静默不登记**（不报错，只是前端看不到）。登记出来的 `path` 是 `.papercast/runs/<id>/video/video.mp4`，`url` 是 `/artifacts/<id>/video/video.mp4`。

## 3. 设计（以及为什么这么做）

### 3.1 反幻觉：数字必须能在 digest 里回溯

规则与 M2（`app/modules/generate.py` 的 `_drop_untraceable`）同源，直接复用它的 `numbers_in / strip_formulas`，避免两处规则漂移。区别只有两点，都是"宁可不杀"的方向：

- 多认等价形式：正文写 `57.18` 而 digest 写 `57.18%` 也算通过（反之亦然）；
- 额外认**硬表达的中文数字**：`百分之五十七点一八` → `57.18`、`三亿` → `3亿`。只有"百分比 / 带小数 / 亿·万量级 / 倍"这四类做强校验，`三个方向`这种计数不杀（避免误杀）。

处置粒度是**句**而不是整篇：一句话里有无法回溯的数字，就删掉这句；要点里有，就删掉这条；一页旁白被删到不足 20 字，就整页丢弃。
每次丢弃都写一条 `warn` 日志（说明丢了什么）并汇总进 `video.report.json` 的 `droppedTraceability`。
成片定稿后还会再跑一次 `residual_violations()` 复核——**check 的 pass/fail 看的是复核结果，不是"有没有丢过"**。

### 3.2 分镜：LLM 主路 + 确定性兜底 + config.brief

`ctx.llm.chat_json` 一次调用产出 6–12 页：每页标题、2–4 条要点（≤22 字）、40–120 字口语化旁白、可选配图 id。
提示词里写死了"只用 digest 的事实""数字用阿拉伯数字写""不要公式 / markdown / 指向原文的指引""没有合适的图就填 null"。

`config.brief`（用户自由文本指令）非空时，用项目统一的 `prompts.brief_block(brief, stage="视频分镜：侧重与口吻")`
拼进分镜 user prompt —— 它自带 `BRIEF_RULES`（只影响风格/体裁/篇幅/侧重，**不得越过事实源**），
所以"用户要求"既被满足又不会污染事实层；末尾还会再过一遍数字回溯校验，双保险。

兜底（`fallback_storyboard`）：LLM 没凭据、报错、或返回结构不合法时，**不静默失败**——
按 digest 的摘要 / 贡献 / 方法 / 结果 / 局限逐条拼出分镜（句子逐字取自 digest，数字天然可回溯），并记 `warn`；
此时如果 `config.brief` 非空，会额外记一条 `warn` 说明"brief 本次未生效"（确定性兜底不经过 LLM，无法体现口吻）。

### 3.3 画帧：PIL，不引浏览器

和卡片同一条路线（07 的路线 B）：版式固定，PIL 直接画，少一个 headless Chrome 进程、在只有 CPU 的服务器上更稳。
中文字体走 `config.find_cjk_font()` + `has_cjk_glyphs()`：**缺字形直接报错中止**，绝不产出满屏方块。

横版版式（1920×1080）：顶部强调条 → 系列名 / 页码 → 标题（68px，最多 2 行）→ 分隔线 → 左要点 + 右配图卡片 → 页脚来源。
要点会按可用高度**自动降字号**（46→30px）并在最坏情况下截断，保证不会压到页脚；配图等比缩放（最多放大 1.6×，论文原图 4000px 宽先降采样再进缓存）。
没有合适图的页面就走**纯文字版式**（要点字号放大到 54px、整行铺满），不硬凑图。

### 3.4 配音：edge-tts（在 bili-venv 里，不在后端 venv）

`edge_tts` 只装在 `<WS>/var/toolchains/bili-venv/bin/python`，所以模块**专门探一个解释器**（`PAPERCAST_TTS_PYTHON` 可覆盖），
不会去 import 它，也不会污染后端 venv 的依赖。

关键收益：`edge-tts --write-subtitles` 会给出**真实的句级时间戳**（微软服务的 WordBoundary），
所以 `subtitles.srt` 是"配音怎么说、字幕就怎么走"，不是按字数比例猜的。没有它（无声降级）才回退到按字数切。

TTS 失败：同一页重试 1 次；仍失败则该页降级成无声片段（时长按 4.6 字/秒估算，**绝不会产出 0 秒片段**），
记 `err` 日志 + `check=配音（TTS）=fail` + 原始报错进 `video.report.json`。

### 3.5 合成：每页一段，先 copy 再校验

每页 `ffmpeg -loop 1 -framerate 25 -i frame.png -i page.mp3 -shortest -c:v libx264 -preset veryfast -crf 20 -tune stillimage -pix_fmt yuv420p -c:a aac -b:a 160k -ar 44100 -ac 2 -movflags +faststart`。
拼接用 concat demuxer：先 `-c copy`（快），**然后用 ffprobe 实测总时长与分段合计比对**，偏差 > 0.5s 就退回滤镜重编码拼接（准）。
实测这一路都是 copy 成功（分段合计 238.16s vs 成片 238.18s，差 0.02s），所以默认路径很快。

### 3.6 竖版：一次滤镜过完整段

竖版不是"每页再画一套帧"，而是拿成品横版过一遍 `filter_complex`：`split → 背景 scale+crop 到 1080×1920 → gblur(sigma=42) + 压暗 → 前景 scale=980 加白边 → overlay 居中`。
理由：内容是静态帧，一次成型的成本远低于"再编码 N 页 + 再拼一次"，而且保证了横竖两版**逐帧同源**。
代价见 §6 的已知限制（居中卡片里的小字在手机上偏小）。

### 3.7 并发与进度

画帧 / TTS / ffmpeg 全是阻塞活，统一 `asyncio.to_thread`；事件循环只负责编排、`ctx.progress()`（3% → 12% → 每页递增 → 86% 横版 → 92% 竖版 → 100%）和 `ctx.log()`。

### 3.8 `config.video` 四个字段怎么用（用不上的一定在日志里说明）

启动时会打一条日志把用法讲清楚，不让人猜：

| 字段 | 用法 |
| --- | --- |
| `voice` | 配音音色，直接传给 edge-tts；`PAPERCAST_TTS_VOICE` 环境变量优先，覆盖时日志会写明 |
| `durationSec` | 目标时长：折算成旁白字数预算（≈4.6 字/秒）写进分镜提示词，并作为 `check=时长` 的容差基准 |
| `narration` | 非空时作为"作者额外要求"拼进分镜 user prompt |
| `aspect` | **不改变产出**（横竖两版都会出），只用它决定哪一版**先登记为主版本**；日志里明确写了这一点，避免被当成未实现 |

### 3.9 失败语义

| 错误码 | 触发条件 | 行为 |
| --- | --- | --- |
| `DIGEST_MISSING` | 没有 `understand/digest.json` | 阶段失败 |
| `FFMPEG_MISSING` | 找不到 ffmpeg/ffprobe | 阶段失败（提示 `PAPERCAST_FFMPEG`/`PAPERCAST_FFPROBE`） |
| `FONT_MISSING` / `FONT_NO_GLYPH` | 没有中文字体 / 字体不含中文字形 | 阶段失败（不产出方块片） |
| `NO_SLIDES` | 分镜清洗后一页不剩 | 阶段失败 |
| `CLIP_ENCODE_FAILED` / `CONCAT_FAILED` / `VERTICAL_FAILED` | ffmpeg 失败 | 阶段失败，stderr 截断进 message |
| 单页 TTS 失败 | edge-tts 报错 / 时长读不出来 | **降级**：该页无声，记 `check=fail`，其余页照常 |

所有失败都会 `ctx.check("视频合成", "fail", "[CODE] 原因")` 后抛出，`pipeline` 会把它记成 `run.error`。

## 4. 命令

接进流水线后由 pipeline 调用；**同一份代码也能脱离 FastAPI 单独跑**（验收与调试用）：

```bash
cd apps/papercast-server

# 常规：用 run id（在 PAPERCAST_DATA_DIR / <WS>/var/runs 下找）
.venv/bin/python -m app.modules.video --run run_d5cd057bab48 --json

# 直接用 run 目录
.venv/bin/python -m app.modules.video --run-dir "$WS/var/runs/run_d5cd057bab48"

# 调试：不走 LLM（确定性分镜）/ 不走 TTS（无声，验证降级路径）
.venv/bin/python -m app.modules.video --run-dir <run目录> --no-llm --skip-tts

# 换音色 / 换目标时长
.venv/bin/python -m app.modules.video --run <runId> --voice zh-CN-YunxiNeural --target-sec 240
```

| 参数 | 说明 |
| --- | --- |
| `--run` / `--run-dir` | 二选一（必填）：run id 或 run 目录 |
| `--voice` | edge-tts 音色，覆盖 `config.video.voice` |
| `--target-sec` | 覆盖 `config.video.durationSec` |
| `--no-llm` | 强制确定性分镜 |
| `--skip-tts` | 强制无声（验证降级） |
| `--json` | 结尾多打一行机器可读汇总（产物 + check） |

环境变量（都有默认值，默认按工作区推导，不写死路径）：`PAPERCAST_FFMPEG`、`PAPERCAST_FFPROBE`、`PAPERCAST_TTS_PYTHON`、`PAPERCAST_TTS_VOICE`。

## 5. 实测（run_d5cd057bab48 · An agentic system for rare disease diagnosis with traceable reasoning）

跑法：`.venv/bin/python -m app.modules.video --run run_d5cd057bab48 --json`，耗时 **258s**（10 页 / LLM 分镜 / 真 TTS）。

### 5.1 ffprobe 原始输出

```console
$ ffprobe -v error -show_entries format=format_name,duration,size,bit_rate \
    -show_entries stream=index,codec_type,codec_name,profile,width,height,pix_fmt,r_frame_rate,sample_rate,channels \
    -of default=noprint_wrappers=1 video/video.mp4
index=0
codec_name=h264
profile=High
codec_type=video
width=1920
height=1080
pix_fmt=yuv420p
r_frame_rate=25/1
index=1
codec_name=aac
profile=LC
codec_type=audio
sample_rate=44100
channels=2
r_frame_rate=0/0
format_name=mov,mp4,m4a,3gp,3g2,mj2
duration=238.183203
size=6255515
bit_rate=210107

$ ffprobe ... video/video-vertical.mp4
index=0
codec_name=h264
profile=High
codec_type=video
width=1080
height=1920
pix_fmt=yuv420p
r_frame_rate=25/1
index=1
codec_name=aac
profile=LC
codec_type=audio
sample_rate=44100
channels=2
format_name=mov,mp4,m4a,3gp,3g2,mj2
duration=238.200000
size=5794539
bit_rate=194610
```

**时长 > 0 且可解码：横版 238.18s / 竖版 238.20s**（不是"文件存在就算过"）。

### 5.2 文件大小

| 文件 | 字节 | 说明 |
| --- | --- | --- |
| `video.mp4` | 6,255,515（5.97 MB） | 10 页 / 238.18s / 210 kbps |
| `video-vertical.mp4` | 5,794,539（5.53 MB） | 1080×1920 |
| `cover.png` | 370,530 | 1920×1080 |
| `narration.json` | 5,022 | 10 页 |
| `subtitles.srt` | 3,287 | 23 条 |
| `video.report.json` | 1,383 | — |
| `frames/` `audio/` `clips/` | 1.5M / 1.4M / 6.1M | 10 帧 / 20 个音频文件 / 10 段片段 |

### 5.3 narration.json 前两页

```json
{
 "title": "An agentic system for rare disease diagnosis with traceable reasoning（arXiv preprint）",
 "totalSec": 238.18,
 "slides": [
  {
   "index": 1,
   "title": "罕见病的诊断困境",
   "bullets": ["罕见病影响全球逾3亿人", "诊断之旅常超过5年", "反复转诊、误诊与不必要的干预"],
   "narration": "罕见病影响全球逾3亿人，但及时准确的诊断一直很难。患者往往要经历长达5年以上的诊断奥德赛，反复转诊、被误诊、接受不必要的干预，治疗被耽误，还要背负沉重的情绪与经济负担。这篇论文要解决的，就是这个困境。",
   "durationSec": 23.0
  },
  {
   "index": 2,
   "title": "DeepRare 是什么",
   "bullets": ["大语言模型驱动的多智能体系统", "整合40多种专用工具", "用于罕见病鉴别诊断决策支持"],
   "narration": "研究团队提出了 DeepRare，一个由大语言模型驱动的多智能体系统，用于罕见病鉴别诊断的决策支持。它整合了40多种专用工具与最新知识源，整体架构受到模型上下文协议的启发。",
   "durationSec": 18.92
  }
 ]
}
```

对应字幕（`subtitles.srt`，时间戳就是 edge-tts 的真时间轴）：

```
1
00:00:00,100 --> 00:00:05,787
罕见病影响全球逾3亿人，但及时准确的诊断一直很难。

2
00:00:05,787 --> 00:00:17,737
患者往往要经历长达5年以上的诊断奥德赛，反复转诊、被误诊、接受不必要的干预，治疗被耽误，还要背负沉重的情绪与经济负担。
```

### 5.4 八条 check（`--json` 里原样可见）

| check | state | detail（原文） |
| --- | --- | --- |
| 视频可解码（横版） | pass | 1920×1080 h264 + aac 44100Hz/2ch；ffprobe 时长 238.18s（>0） |
| 视频可解码（竖版） | pass | 1080×1920 h264 + aac 44100Hz/2ch；时长 238.20s |
| 分镜数 | pass | 10 页（要求 6–12）；分镜来源 llm；3 页配图 |
| 数字可回溯 | pass | 成片文本里的 76 个数字全部可在 digest.json 中回溯 |
| 字幕与音轨对齐 | pass | 23 条字幕，末条结束 236.30s / 视频 238.18s，偏差 1.89s |
| 配音（TTS） | pass | 10 页全部用 zh-CN-XiaoxiaoNeural 配音（edge-tts） |
| 时长 | pass | 成片 238.2s / 目标 180s（旁白合计 1089 字） |
| 封面 | pass | cover.png 1920×1080，361 KB |

「字幕偏差 1.89s」不是错位：句级字幕的最后一条在幻灯片收尾留白前就结束了，字幕**不做**"拖到片尾"的填充。
每条 cue 的起点都是"本页起点 + edge-tts 给的句内偏移"，逐页累加，天然与音轨同源。

### 5.5 版式自检（本会话读图工具不可用，改用像素检查）

ffprobe 只能证明"能播"，证明不了"没糊"。所以另外做了程序化检查（`PIL` 逐帧算墨迹包围盒与非白像素占比）：

| 检查 | 结果 |
| --- | --- |
| 10 帧内容区墨迹包围盒 | 全部落在 `x∈[71,1846]`、`y∈[51,926]`，**越界 0 帧**（未压页脚、未出血） |
| 有图页 vs 纯文字页的右栏非白像素 | 有图页 39.7%，前 4 页纯文字页 0.0%（图确实贴上了，且没有硬凑的面板） |
| 封面右侧主图卡片 | 非白占比 50.4% |
| 竖版居中卡片区域（y 660–1260） | 非白占比 94.5%（卡片确实居中铺满该区域） |

### 5.6 降级路径实测（`--no-llm --skip-tts`，在 run 的副本上跑，不动验收产物）

| 项 | 结果 |
| --- | --- |
| 分镜来源 | `fallback`（确定性：摘要/贡献/方法/结果/局限逐条取 digest） |
| 页数 | 11 页，8 页配图（按 digest.figures 顺序补图） |
| 数字可回溯 | 37 个数字全部可回溯，`residualViolations=[]`、丢弃 0 处 |
| 配音 | 11/11 页无声降级 → `check=配音（TTS）=fail`，detail 列出页码 |
| 视频 | 仍产出合法 mp4：1920×1080 h264 + **aac 无声轨** 219.42s / 1.94 MB；竖版 219.41s |
| 字幕 | 由旁白按字数比例切（17 条），`cueDriftSec=0.02` |
| 耗时 | 132s |

即：**降级不等于静默**——片子照出，但"没有配音"这件事在 check 里是 fail，报表里有原始原因。

### 5.7 没有配图的论文（单测，不起 ffmpeg）

把 digest 的 `figures` 清空后直接调 `load_inputs → sanitize_storyboard → render_frame → render_cover`：
可用图片 0 张 → 11 页**全部纯文字版式**、丢弃 0 处、帧 1920×1080 正常产出（67,744 B）；
封面退化成暗底 + 大标题（平均亮度 19.1、高亮像素 55,106），不崩、不空。

### 5.8 真实 StageContext 接线验证

除了 CLI，另起一个进程用**真实的 `RunStore` + `Pipeline` + `StageContext`** 调 `run_video(ctx)`
（fixture 拷到临时 run 根目录，避免污染 `var/runs`），并设上 `config.brief` 与 `config.video` 四字段：

- `ctx.work == <run>/video` → **True**；
- 登记 6 个产物，路径全部正确：`.papercast/runs/<id>/video/video.mp4`，`url=/artifacts/<id>/video/video.mp4`；
- 因为 `aspect="9:16"`，**竖版排在了横版前面**（主版本顺序生效）；
- 8 条 check 全部写进 `stage.checks`，`stage.progress == 1.0`，`run.json` 正常落盘；
- 日志里能看到 `config.video 用法：…aspect=9:16（横竖两版都会产出，这里只用它决定哪一版先登记为主版本）` 与 `config.brief：希望更口语一点，多讲临床落地场景，控制在 8 页以内`；
- 该次跑出 8 页 / 219.5s / 4 页配图 / 55 个数字全回溯，8 条 check 全 pass。

## 6. 已知限制

1. **画面是静态帧**：没有动画、转场、光标、数字人。这是"确定性排版 + CPU 编码"的代价，也是它的可靠性来源。
2. **配图靠启发式**：本次 digest 的图注全是"（第 N 页内嵌图像，未匹配到图注）"，模型只能按"讲数据/结果的页可以配图"来挑；
   10 页里 3 页配图。图注可靠时（LaTeX 抽取的 `fig-1-teaser.png` 那种）判断会好得多。
3. **`config.brief` 在确定性兜底路径下不生效**（不走 LLM 就没有口吻可言）——这种情况会记 `warn`，不是静默忽略。
4. **`config.video.aspect` 不改变产出**：横竖两版恒定都出，它只决定主版本登记顺序（日志已说明）。
5. **字幕是句级的，不是词级高亮**：edge-tts 给的是句边界；要做卡拉OK式逐词高亮需要把 WordBoundary 全量接出来（`edge_tts` 的 Python API 有，CLI 不给）。
6. **时长只能"接近"目标**：总时长 = 各页配音时长之和，靠"旁白字数 ≈ 4.6 字/秒 × 目标"来逼近；
   本次目标 180s、成片 238.2s（+32%，仍在 check 的 ±35% 容差内，但已经接近上限）。要精确控制需要"按目标时长裁旁白 + 变速"。
   LLM 分镜的篇幅波动是主因：同一篇论文两次跑分别出过 8 页 194s 和 10 页 238s。
7. **中文数字只做强校验的子集**：`百分之五十七点一八`/`三亿` 会查，`三个方向`这种计数不查（否则误杀太多）。
   提示词里要求数字写阿拉伯数字，所以真正靠中文数字漏过去的概率很低——但不是 0。
8. **竖版的小字**：居中卡片是把 1920×1080 缩到 980 宽，正文小字在手机上偏小；小红书场景可考虑竖版另画一套版式（成本：每页两套帧）。
9. **封面依赖主图**：没有可用图时封面退化成"暗底 + 文字"，排版仍然成立，但不好看。
10. **无背景音乐 / 无音量归一化**：edge-tts 输出直连，没有 loudnorm。
11. **分镜不可复现**（LLM 采样）：同样的 digest 两次跑出的分镜不同。要复现得用 `config.video.narration` 锁要求，或走 `--no-llm`。
12. **本会话没能"用眼睛看"**：读图工具（modlens）在本会话报错，所以版式只能靠 §5.5 的像素检查 + 版式代码审阅确认。
    已经抽好 4 张供人工目视：`var/tmp/vinspect-final/`（封面、横版第 1 页、横版有配图页、竖版同页）；
    自己再抽别的时间点：`ffmpeg -ss <秒> -i video/video.mp4 -frames:v 1 x.png`。
13. **长任务与取消**：单次跑 2–4 分钟，全部阻塞活在 `to_thread` 里，`asyncio` 取消**不会**打断已经在跑的 ffmpeg 子进程；
    若在流水线里点"取消"，可能要等当前页编码完（最多几十秒）。

## 7. 接线状态

已在 `app/pipeline.py` 的 plan 中接线：

```python
from .modules.video import run_video

plan = [("intake", run_intake), ("understand", run_understand), ("article", run_article),
        ("poster", run_poster), ("video", run_video), ("publish", run_publish)]
```

配套要确认的两处（不在本模块的交付范围）：

1. `app/models.py`：`SKIPPED_STAGES` 里去掉 `"video"`、`IMPLEMENTED_STAGES` 加上 `"video"`（否则阶段会被标成 skipped，pipeline 直接跳过）；
2. `app/models.py` 的 `STAGE_META["video"]["hint"]` 现在还是"尚未接入本后端"，应改成真实描述
   （例如"digest → 中文分镜 → PIL 帧 + edge-tts 配音 → ffmpeg 出横竖两版 mp4，数字可回溯校验"）。

本模块**不依赖** `ctx.shared`（CLI 里 `shared={}` 照样跑通），所以接线时不需要额外往 shared 里塞东西。

## 8. 后续可做（未做）

1. **词级字幕/卡拉OK高亮**：改用 `edge_tts` 的 Python API 收 WordBoundary。
2. **时长精确控制**：按 `durationSec` 反推每页旁白上限，超了就压缩（或给 TTS 传 `--rate`）。
3. **竖版独立版式**：现在竖版是横版帧缩放到 980 宽，小字偏小；另画一套 1080×1920 版式更合适。
4. **章节与转场**：把 6–12 页分成 3–4 个章节，章节页用不同底色，加硬切/淡入。
5. **背景音乐**：TTS 音轨 + 低音量 BGM 混音（`amix` + `loudnorm`），体积与版权都要考虑。
