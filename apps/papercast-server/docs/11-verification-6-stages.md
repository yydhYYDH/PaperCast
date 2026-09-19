# 11 · 六阶段端到端验证（intake → understand → article → poster → video → publish）

> 版本：R1 · 2026-09-19 · 验证时间 01:56–02:18（CST）
> 本文只写**真跑过的 run**：所有数字来自 `var/runs/<runId>/` 里的 `run.json` 与磁盘产物，
> 用本文 §10 的命令可以原样复现。**发现但没修的 bug 全部列在 §8，没有为了好看把 fail 写成 pass。**

---

## 0. 一句话结论

**6 个阶段在真实论文上全部能跑到终态，且每段都有能验的实物**：digest.json 6 条贡献 / 12 条数值全回溯、
文案 4 个变体、4 张画布几何闸门 4/4 无溢出、**真 mp4（1920×1080 h264+aac，291.38s / 7.42 MB）**、
三渠道回执 + 素材包。剩下的失败项都是**外部条件**（小红书未扫码登录）或**如实标记的偏差**
（成片时长超目标、B 站标题超 80 字），不是编造的成功。

| 阶段 | 终态 | 可复核的实物 | 一句话实测 |
| --- | --- | --- | --- |
| intake | done | `intake/content.md` `figures.json` `images/*.png` | 123k 字符 / 23 页 PDF；旧解析器 4 张（未匹配 4），新解析器 9 张（fig 8 + table 1，未匹配 0） |
| understand | done（**人工闸门**） | `understand/digest.json` `reading_note.md` | 6 条贡献 / 12 条结果全部可在原文检索 / 精读笔记 17991 字符 |
| article | done | `article/*.md` `article/export/{title,content}.txt` `cards/p*.png` | 小红书 817 字 + 4 张 1080×1440 卡片；知乎 2745 字；英文 443 词 |
| poster | done | `poster/*.png` + `*.render.json` | 4 张画布 2304×1728 / 1080×2400 / 1600×1200 / 1920×1080，溢出 0 处，panel_fill 0.946–0.980 |
| video | done（**本轮从 skipped 变真实现**） | `video/video.mp4` `video-vertical.mp4` `cover.png` `subtitles.srt` `narration.json` `video.report.json` | ffprobe：291.38s / 1920×1080 / h264 / aac 44.1k 立体声 / 213 kbps / 7.42 MB；12 页全 edge-tts 配音 |
| publish | done（**人工闸门 = draft**） | `publish/receipts.json` + 三渠道 `*/receipt.json` + `*/export/` | 三份独立回执；小红书 login_required=fail（照实）；知乎/B站 ready |

---

## 1. 验证环境与代码版本（本次有**代码漂移**，必须写在最前面）

### 1.1 环境（`GET /api/env` 实测，不是抄文档）

```text
intake   engine=pymupdf  gpu=false（NVML: GPU access blocked by the operating system）
         mineru=false  ocr=false（tesseract 未装）
latex    engine=null → mode=source-only（本机无 TeX 引擎）
llm      baseUrl=https://opencode.ai/zen/go/v1  model=deepseek-v4.1-flash  configured=true
cards    enabled=true  cjkFont=…/fonts/waic/msyh.ttc  cjkFontUsable=true
         chrome=…/ms-playwright/chromium_headless_shell-1243/…/chrome-headless-shell
publish  xiaohongshu: base=http://127.0.0.1:18060  reachable=true  loggedIn=false
dataDir  var/runs
```

视频链路的工具链（来自 `video/video.report.json.engine`）：`ffmpeg version 9.0.1`（`var/toolchains/p2b/bin/ffmpeg`）、
`ffprobe` 同目录、edge-tts 走 `var/toolchains/bili-venv/bin/python`、音色 `zh-CN-XiaoxiaoNeural`、字体 `msyh.ttc`。

### 1.2 后端进程与代码版本：**两条 run 跑在旧进程上，一条跑在新进程上**

本机后端**没有开 `--reload`**，所以「磁盘上的代码」≠「跑着的代码」。本次验证期间后端被重启过一次：

| 后端进程 | 启动时间 | 服务的 run |
| --- | --- | --- |
| pid 32262（旧） | 01:49:20 | `run_d76ca9da493e`、`run_9105dc770228`（以及 backend 轨道的 `run_720e83bdae91`） |
| pid 19167（新） | 02:07:15 | `run_c5451b582400` |

**会话期间有别的轨道在改后端代码，必须逐文件记下来**（`find -newermt '2026-09-19 01:49:30'`）：

| 文件 | 改动时间 | 改的时候我的 run 处于什么状态 |
| --- | --- | --- |
| `app/chat_api.py`、`app/main.py` | 01:52:47 | 旧进程（01:49:20）正在服 A/B —— **这两处改动没进旧进程**；C 用的新进程（02:07:15）含它 |
| `app/modules/community.py` | 02:01:29 | A/B 的 publish 段早于此；C 加载的是新版 |
| `app/intake/pdf_parser.py` | 02:12:47、02:17:39 | A/B/720 用旧解析器；**C（02:09 起）用的是修好的那版** |
| `app/modules/generate.py`、`app/modules/poster_stage.py`、`app/store.py` | **02:15:29** | **晚于 A/B/C 的 article/poster 段**（C 的 article 在 02:11:06）→ 三条 run 跑的都是 01:49:08 那版 |

sha256 两次快照（左＝我的 run 实际跑的那版，右＝02:23 复核时磁盘上的）：

```text
models.py                6c21c180…              modules/video.py        d09c47b2…   （未变）
pipeline.py              3a8f4677…              modules/publish.py      93015f64…   （未变）
main.py                  0d5d1f23…              modules/community.py    a05ffcf5…   （未变）
modules/generate.py      99466d5d…  →  0b4d00b5…   (02:15:29 重写)
modules/poster_stage.py  10d4032a…  →  3bda5315…   (02:15:29 重写)
intake/pdf_parser.py     0e9ecdc7…  →  d331886a…   (02:17:39 重写)
```

本文 §4 / §5 / §8-B3/B4/B6 的结论对应 **generate.py @ 99466d5d** 那版；02:23 复核时**同样的逻辑仍在**
（出口兜底与 `words=styles.cjk_len` 都还在，只是行号从 461–481 漂到 466–486），所以结论仍成立 ——
但要复核请先比 hash：这个工作区里「最新代码」不等于「我跑过的代码」。

**这条漂移直接影响 intake 的结论**：旧解析器把 4 张大图当「未匹配」存成 `img-p17-1.png`…，
新解析器给出 `fig-1..fig-5` + `fig-ed1..ed3` + `table-ed1`（图注匹配上，未匹配 0）。
所以 §3.1 与 §8-B5 里两条结论都成立、但适用版本不同，看的时候别混。

### 1.3 三条 run 的归属

| run | 变体 | brief | 谁跑的 |
| --- | --- | --- | --- |
| `run_d76ca9da493e` | xhs-author, zhihu-analyst | 「做成知乎长文，重点讲方法，不要营销腔」 | **本文（验证轨道 A）** |
| `run_9105dc770228` | en-analyst, zhihu-analyst | 无 | **本文（验证轨道 A）** |
| `run_c5451b582400` | zhihu-analyst | 「做成知乎长文，800 字以内，重点讲方法，不要营销腔」 | **本文（验证轨道 A）** |
| `run_720e83bdae91` | en-analyst, zhihu-analyst | 同第 1 条 | backend 轨道（本文只读复核，作为交叉证据） |
| `run_abb2805074e4` | zhihu-analyst, xhs-author | 「…800 字以内…避免颠覆式表达」 | backend 轨道（旧代码，用作 §4.2 对照） |

素材统一是 `var/samples/deeprare.pdf`（9,891,107 B / 23 页，罕见病诊断论文；PDF 里的图是矢量图 + 未编号大图）。

---

## 2. 六段总表（阶段推进 = 要验的第 1 条）

**结论：6 段都能从 pending 走到 done**；本轮 `video` 不再是 skipped，是真出片。
（历史 run `run_abb2805074e4` / `run_d5cd057bab48` 的 `video:skipped` 是旧代码里 `SKIPPED_STAGES` 的遗留，
现版本 `models.py` 的 `SKIPPED_STAGES` 已为空集。）

| run | intake | understand | article | poster | video | publish | 产物数 | 非 pass 的 check |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `run_d76ca9da493e` | done 53.3s | done 87.0s | done 53.0s | done 54.8s | **done 280.3s** | done 3.8s | **42** | 4（见 §7） |
| `run_9105dc770228` | done 54.3s | done 89.5s | done 189.8s | done 34.6s | **done 218.6s** | **waiting（卡死）** | 27 | 2 |
| `run_c5451b582400` | done 24.4s | done 77.3s | done 19.7s | done 60.6s | **done 199.3s** | done | **42** | 4 |
| `run_720e83bdae91`（交叉） | done 39.8s | done 95.5s | done 121.0s | done 78.0s | **done 241.4s** | done 57.4s | 37 | 5 |

产物数按段拆（`run_d76ca9da493e`）：intake 8 / understand 3 / article 9 / poster 6 / video 6 / publish 10。
磁盘上逐文件核对：`ls var/runs/run_d76ca9da493e/{intake,understand,article,poster,video,publish}/`。

> ⚠️ `run_9105dc770228` 的 publish 卡在 waiting 是**真 bug**（§8-B1），不是我把闸门忘了 —— 详见那一节。

---

## 3. 逐段的真实产物与尺寸

### 3.1 intake（PDF → md + 图）

| 产物 | 值 |
| --- | --- |
| `intake/paper.pdf` | 9,891,107 B，meta `{"pages": 23}` |
| `intake/content.md` | 124,060 B（旧解析器）/ 125,310 B（新解析器）；check：`正文抽取 pass 123k 字符 / 6 个标题` |
| `intake/images/*` | 旧：`img-p17-1.png` 4335×3931 / `img-p18-1` 4335×3237 / `img-p19-1` 4335×4594 / `img-p20-1` 4335×1428（4 张，**未匹配 4**）；新（`run_c5451b582400`）：`fig-1` 1184×1304、`fig-2` 585×199、`fig-3` 1181×1195、`fig-4` 1261×905、`fig-5` 627×941、`fig-ed1` 3251×2948、`fig-ed2` 3251×2427、`fig-ed3` 3251×3445、`table-ed1`（9 张，**未匹配 0**） |
| `intake/figures.json` | 1,150 B（旧，无 caption 匹配）/ 5,202 B（新，含 caption、bbox、page） |
| checks | `正文抽取 pass` / `图片抽取 pass` / `元数据 pass`（标题与 PDF 首行一致）/ `图片引用 pass`（全部图片文件存在） |

### 3.2 understand（LLM 事实源 + 精读笔记，**有闸门**）

闸门：`stage.gate = {id:"digest", label:"确认论文理解层", options:[continue, revise]}`，
detail「下游小红书图文的数字与结论全部由这份事实源派生，确认贡献点与关键数据无误后再放行。」
放行方式 `POST /api/runs/{id}/stages/understand/gate {"optionId":"continue"}` → 204。

| 指标 | `run_d76ca9da493e` | `run_720e83bdae91` | `run_c5451b582400` |
| --- | --- | --- | --- |
| `digest.json` | 8,759 B | （37 产物 run） | 10,288 B |
| contributions | **6** | 6 | 6 |
| results（数值回溯条数） | **12 条，全部能在原文检索到**（check `数值可回溯 pass`） | 12 条全过 | 12 条全过 |
| figures | 4 | 4 | 6 |
| keywords / limitations | 8 / 5 | 8 / 6 | 7 / 6 |
| method 字数 | 999 字 | 697 字 | 841 字 |
| 精读笔记 | `reading_note.md` 33,146 B / 17,991 字符（7,404 中文字） | — | 38,034 B / 18,300 字符 |

前 3 条贡献（`run_d76ca9da493e` 原文）：① DeepRare 三层多智能体系统，整合 40+ 专业工具与最新知识源；
② MCP 启发的三层架构（记忆库宿主 / 专门 agent server / 外部医学资源）；
③ 自反思循环 + 参考链接有效性校验以压制过度诊断与幻觉。
数值例（全部可在 `content.md` 检索到）：HPO 任务平均 Recall@1 = **57.18%**、Recall@3 = 65.25%、
多模态 Xinhua 168 例 Recall@1 = **69.1%**（Exomiser 55.9%）、推理链医师核验准确率 = **95.4%**。

### 3.3 article（平台 × 人格变体）

`run_d76ca9da493e`（xhs-author + zhihu-analyst）：

| 变体 | 产物 | 尺寸 | checks |
| --- | --- | --- | --- |
| 小红书 × 作者自述 | `article/xhs.md` 3,488 B + `xhs.raw.json` 4,247 B | 正文 **817 字**（≤1000） | 标题计重 **34**（上限 38）/ 无公式 pass / 标签 **12** 个（8-12）/ 卡片渲染 pass |
| 小红书卡片 | `article/cards/p1..p4.png` | **4 张 1080×1440**（442,826 / 215,943 / 348,531 / 160,214 B） | — |
| 知乎 × 技术解读 | `article/zhihu-analyst.md` 9,810 B | 正文 **2745 字**（2000-4000） | 标题 18 字（≤40）/ 标签 6 / 数字可回溯 **82 个** |
| 出口兜底 | `article/export/title.txt` 47 B + `content.txt` 2,203 B | 标题「DeepRare：多智能体怎么做罕见病诊断」 | §5 解释它取自哪个变体 |

`run_720e83bdae91`（en-analyst + zhihu-analyst）：`en-analyst.md` 的 check 是 `正文长度 pass 443 词（要求 320-850）`、
知乎 2298 字、`数字可回溯 83 个`。`run_c5451b582400`（zhihu only）：2117 字、标题 20 字、`数字可回溯 70 个`。

### 3.4 poster（LLM 写 spec → chrome 渲染 4 张画布）

4 张画布全部 `overflow=[]`、`broken_images=[]`、`ok=true`（`poster/*.render.json`，几何自检原文）：

| 预设 | 像素 | scale | 正文 px | `panel_fill` | 二分尝试（tries） |
| --- | --- | --- | --- | --- | --- |
| `conf` 会议海报 | **2304×1728** | 0.99 | 22.1 | 0.9758 | 1.0739✗(溢出115) → 0.8054✓ → 0.9397✓ → 1.0068✗(11) → 0.9732✓ → 0.99✓ |
| `xhs-long` 竖长图 | **1080×2400** | 1.9196 | 20.1 | 0.9463 | 2.4819✗(299) → 1.8614✓ → 2.1717✗(128) → 2.0166✗(57) → 1.939✗(16) → 1.9002✓ → 1.9196✓ |
| `zhihu` 横版 | **1600×1200** | 1.1849 | 18.4 | 0.9801 | 1.4175✗(225) → 1.0631✓ → 1.2403✗(37) → 1.1517✓ → 1.196✗(12) → 1.1738✓ → 1.1849✓ |
| `bili-cover` 视频封面 | **1920×1080** | 2.6 | h1 **212px** | null（cover 版式无正文栏） | 首轮 2.6 直接通过（cover 是「能放多大放多大」） |

文件大小：poster.png 927,987 B / poster-xhs-long.png 725,029 B / poster-zhihu.png 544,034 B / poster-bili-cover.png 961,828 B。
知乎横版**触发了自动减块**：磁盘上留下 `poster.spec.zhihu.trim1/2/3.json`（blocks 2+2+1 → 2+2 → 2+1），
最终 `已按优先级砍掉 3 个次要块` 并以 `overflow=[]` 通过 —— 这是「窄画布必须减内容」的落地，不是静默降级。
段内 checks：`画布 · ×4 pass` / `几何闸门 4/4 张画布无溢出` / `图片引用 pass` / `数字可回溯 pass`。
交叉 run `run_720e83bdae91` 同样是 4/4 无溢出（scale 0.9229 / 2.0747 / 1.2513 / 2.6，panel_fill 0.9799 / 0.9431 / 0.981）。

### 3.5 video（真 mp4，ffprobe 原文）

`run_d76ca9da493e` 的两份成片（我单独用 ffprobe 复读了一遍，与 `video.report.json` 一致）：

```text
$ ffprobe -v error -show_entries format=duration,size,bit_rate,format_name \
          -show_entries stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels \
          -of default=noprint_wrappers=1 var/runs/run_d76ca9da493e/video/video.mp4
index=0      codec_name=h264  codec_type=video  width=1920  height=1080  r_frame_rate=25/1
index=1      codec_name=aac   codec_type=audio  sample_rate=44100  channels=2
format_name=mov,mp4,m4a,3gp,3g2,mj2
duration=291.383203   size=7783858   bit_rate=213707

$ 同上 video-vertical.mp4
index=0      codec_name=h264  codec_type=video  width=1080  height=1920  r_frame_rate=25/1
index=1      codec_name=aac   codec_type=audio  sample_rate=44100  channels=2
duration=291.400000   size=7197331   bit_rate=197593
```

| run | 横版 mp4 | 竖版 mp4 | 时长 | 页数 | 字幕 | 数字回溯 | 封面 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `run_d76ca9da493e` | 7,783,858 B / 7.42 MB / 213,707 bps | 7,197,331 B / 6.86 MB / 197,593 bps | 291.38s（旁白 1492 字） | 12（4 页配图） | 28 条，末条 289.47s，偏差 1.91s | 66 个数字全回溯，residual=[] | cover.png 383,955 B 1920×1080 |
| `run_9105dc770228` | 6,070,424 B / 215,317 bps | 5,533,884 B | 225.54s（旁白 1027 字） | 10（4 页配图） | 27 条，末条 223.71s，偏差 1.83s | 58 个全回溯 | 372,844 B |
| `run_c5451b582400` | 6,492,560 B / 230,249 bps | 5,732,011 B | 225.58s（旁白 1041 字） | 9（4 页配图） | 25 条，末条 223.81s，偏差 1.77s | 48 个全回溯 | 326,030 B |
| `run_720e83bdae91`（交叉） | 7,262,980 B / 215,916 bps | 6,585,382 B | 269.10s | 11（3 页配图） | 25 条，偏差 1.79s | 70 个全回溯 | 370,082 B |

工程指标（`video.report.json`）：`ttsMode=edge-tts`（12/12 页真配音，无降级）、`plannedSec=291.36 → totalSec=291.38`
（分段之和与拼接实测一致）、`cueDriftSec=1.91`、`storyboard=llm`、`elapsedSec=280.3`。
分镜前 3 页（`narration.json`）：①「为什么需要它」18.76s ②「DeepRare 是什么」21.96s ③「三层架构」24.92s。
段内 checks：`视频可解码（横版/竖版）pass`、`分镜数 pass`（12 页，要求 6–12）、`数字可回溯 pass`、
`字幕与音轨对齐 pass`、`配音（TTS）pass`、`封面 pass`，**`时长` 是 run**（291.4s vs 目标 180s，见 §7.3）。

### 3.6 publish（多渠道 preflight + 闸门 + 回执）

闸门原文（`run_d76ca9da493e`，`optionId=draft`，**没有对 publish 发过 continue**）：

```text
本次发布计划（每个渠道相互独立，一个失败不影响其它）：
· 小红书：投不了（login_required）—— MCP 在线，但当前未登录（或登录已失效）
· 知乎：将投递 长文（921 字 + 4 张配图）；视频通道未接，只投文字与配图，账号 YYDH
· B站：将投递 视频投稿（video-vertical.mp4 / 封面 有 / 1 个标签），账号 YYDH54
所有渠道的素材包都已落在 publish/<渠道>/export/，即使全部投递失败也能手动发布。
```

`publish/receipts.json`（总表）+ 三份 `publish/<渠道>/receipt.json`（每份含 `state` 探测结果、`exportDir`、`at`）：

```json
{"optionId":"draft","status":"draft",
 "material":{"title":"DeepRare：多智能体怎么做罕见病诊断","contentChars":921,"imageCount":4,
             "video":"video-vertical.mp4","tags":["鉴别诊断"]},
 "channels":{"xiaohongshu":{"status":"draft","state":{"state":"login_required","reachable":true}},
             "zhihu":{"status":"draft","state":{"state":"ready","account":"YYDH"}},
             "bilibili":{"status":"draft","state":{"state":"ready","account":"YYDH54"}}},
 "published":[],"failed":[],"blocked":[]}
```

素材包：每渠道 6–7 个文件（`title.txt` / `content.txt` / 图片 / `README.txt` 手动发布指引），
naming 一致（`publish/<渠道>/export/`），这也是「服务全挂还能手动发」的兜底。
段内 checks（12 条）：`素材适配：小红书 pass（视频笔记）`、`渠道状态：小红书 fail`、
`素材适配：知乎 pass`、`渠道状态：知乎 pass`、`素材适配：B站 pass（视频投稿）`（**有了 video 之后 B 站素材适配从 fail 变 pass**）、
`可投递渠道 pass（知乎、B站）`、`发布结果 run（仅存草稿）`。B 站这条变化是本轮 video 落地的直接收益：
`run_abb2805074e4`（video 被跳过）里它还是 `缺视频：B 站是视频投稿…` 的 fail。

---

## 4. 带 brief 的运行：`指令遵从度` 系列 check 逐条解释

brief 的机检口径写在 `app/modules/generate.py` 的 `brief_checks()`（`BRIEF_WORD_LIMIT / BRIEF_FORBID / BRIEF_MUST`
三个正则），只检查「能落到可判定事实」的三类约束，抽不到的部分一律记 `run`（待人工复核），不假装检查过。

### 4.1 `run_d76ca9da493e`：brief =「做成知乎长文，重点讲方法，不要营销腔」

| 变体 | check | state | 为什么是这个 state |
| --- | --- | --- | --- |
| 小红书 × 作者自述 | `指令遵从度 · 禁用表达` | **pass** | `BRIEF_FORBID` 从「不要营销腔」抽出词 `营销腔`，正文与标题里 0 次命中 → 合规 |
| 小红书 × 作者自述 | `指令遵从度 · 侧重` | **pass** | `BRIEF_MUST` 从「重点讲方法」抽出 `方法`，正文命中 → 合规 |
| 知乎 × 技术解读 | `指令遵从度 · 禁用表达` | **pass** | 同上，知乎长文 2745 字里也没有「营销腔」 |
| 知乎 × 技术解读 | `指令遵从度 · 侧重` | **pass** | 同上，`方法` 命中 |
| —（**没有** `字数上限` 那条） | — | — | 这条 brief **不含数字约束**，`BRIEF_WORD_LIMIT` 匹配不到 → 按设计不生成该 check。**没有 = 没这约束，不是漏检。** |

「做成知乎长文」这个体裁要求同样**不机检**（只有一条机检约束都抽不出时才会落一条 `run` 让人复核；这里已被后两条覆盖）。
想看「体裁有没有被执行」就直接看产物：知乎变体确实写成 2745 字、含 `##` 小节的知乎长文
（`article/zhihu-analyst.md` 首行 `# DeepRare：多智能体罕见病诊断系统，HPO 任务平均 Recall@1 为 57.18%`），
而小红书变体是 817 字图文帖 —— 体裁是分开的。**但知乎那次实际投递用的是小红书文案，见 §8-B3**（这是本文发现的最大功能性问题）。

### 4.2 brief 字数与平台硬约束冲突：**应为 run，不是 fail —— 已按新代码验证通过**

用 `run_c5451b582400`（variants 只有 zhihu-analyst，brief =「…800 字以内…」）专门验这条：

```text
article  run | 知乎 × 技术解读 · 指令遵从度 · 字数上限 800 |
  指令要 ≤800 字，但该平台正文下限是 2000 字 —— 按「平台硬约束 > 用户指令」以平台为准
  （实际 3211 字）；想真正压到 800 字请换短体裁平台
```

对照**旧代码**的同 brief run `run_abb2805074e4`（01:42，早于 generate.py 的 01:49 改动）：

```text
article  fail | 知乎 × 技术解读 · 指令遵从度 · 字数上限 800 | 实际 3491 字，超出 2691 字
```

两条 run 的差别就是这次修复：冲突场景下报 `fail` 会把「平台约束优先」这个**预期中的裁决**误报成执行失败，
现在报 `run` 并在 detail 里说清冲突与建议（换短体裁平台），平台侧该过的 check 仍然是 pass
（`正文长度 pass 2117 字（要求 2000-4000）`）。同一 run 里另外两条：`禁用表达 pass`、`侧重 pass（已体现：方法）`。

> 注：本次三条 run 的 brief 都要求知乎长文，所以**没有**出现「指令上限比平台上限还宽」那条分支
> （limit > `body_max` 时同样报 run）—— 那个分支只在代码层面确认过，未做端到端实测（见 §9）。

---

## 5. 不含小红书变体的 run 能不能走到 publish：**能，且已定位出口标题来自哪个变体**

**根因回顾**：`publish` 只读 `article/export/{title,content}.txt`，而 `export/` 历史上**只由小红书（JSON 输出）分支**
在 `_gen_xhs_variant(export=True)` 里写。只选 `en-analyst` / `zhihu-analyst` 的 run 就没有 `title.txt` →
`collect_materials()` 抛 `TITLE_MISSING: 标题为空，拒绝发布（先把 M2 的 export/title.txt 修好）` → **整条 run failed**。
旧证据：`run_fd06c795207e`（en+zhihu，01:48）`status=failed, error={"code":"TITLE_MISSING"}`，publish 段 `art=0 checks=0`。

**修复**：`app/modules/generate.py:461-481`（02:23 复核时漂到 466-486，逻辑未变）的「出口兜底」——没有 xhs 变体时，从**第一个能取到一级标题的 markdown 变体**
（`sort(ctx.work.glob(f"{art.id.split('-')[0]}*.md"))` → `re ^#\s+(.+)$`）取标题与正文写进 `export/`。

本次两条**不含小红书**的 run 都跑到了 publish：

| run | 段日志 | `article/export/title.txt` | 出口来自哪个变体 |
| --- | --- | --- | --- |
| `run_9105dc770228` | `本 run 没有小红书变体，已从「英文传播（X / LinkedIn） × 技术解读」取出口标题与正文（publish 需要）` | 84 B：`DeepRare: an agentic LLM system for rare disease diagnosis with traceable reasoning` | **en-analyst**（变体列表第一个） |
| `run_720e83bdae91` | 同上（一字不差） | 76 B：`DeepRare: a three-layer agentic system for traceable rare disease diagnosis` | **en-analyst** |

也就是说：**现在的出口标题取自「变体列表里第一个 markdown 变体」，en 在前就是英文标题。** 副作用有两条，都实测到了：

1. `run_9105dc770228` 里 B 站因为 `标题 83 字 > 80 字（B 站上限）` 被**素材不适配**跳过；同一 run 的 `zhihu`
   素材适配却说 `长文（2662 字，无配图）` —— 那 2662 字其实是**英文 thread**。
2. `run_720e83bdae91` 里 B 站通过了素材适配（标题 76 字符 < 80），但知乎要投的仍然是英文 thread。

所以「不含小红书能否走到 publish」= **修好了（能走到终态）**，但「走到 publish 之后投出去的是不是该平台该有的文案」
= **还有问题**（§8-B3/B4）。这两件事别混为一谈。

---

## 6. en 变体：确实是英文 thread，平台校验按词数口径 pass

`run_9105dc770228` 的 `article/en-analyst.md`（2,678 B），前 3 条原文：

```text
# DeepRare: an agentic LLM system for rare disease diagnosis with traceable reasoning

1/10 DeepRare, a multi-agent LLM system, ranked rare disease diagnoses across 2,919 diseases and 6,401 cases,
reaching 57.18% average Recall@1 on HPO tasks — 23.79% above the next best method. Its reasoning chains link
to verifiable evidence.

2/10 The paper frames the problem: rare disease patients face a diagnostic odyssey of over 5 years, with
repeated referrals, misdiagnoses and unnecessary interventions that delay treatment. Rare diseases affect
more than 300 million people worldwide.

3/10 DeepRare uses an MCP-inspired three-layer architecture: an LLM host (default local DeepSeek-V3) with
memory, specialised agent servers, and external data sources. Its 40-plus tools cover phenotype extraction,
disease normalisation, literature search and variant analysis.
```

**是真英文、真是 thread 结构**（`1/10 … 10/10` 编号帖 + `## Tags` 英文标签），不是中文套壳。
校验口径与结果：`en` 平台的 `PlatformSpec.unit="words"`，check 走 `styles.text_len` 而不是 `cjk_len`：

| run | `正文长度` | `标题`（字符） | `标签数量` | `无公式` | `数字可回溯` |
| --- | --- | --- | --- | --- | --- |
| `run_9105dc770228` | **pass 421 词（要求 320-850）** | pass 83 字符（≤90） | pass 5 个（3-6） | pass | pass 70 个 |
| `run_720e83bdae91` | **pass 443 词（要求 320-850）** | pass 75 字符（≤90） | pass 5 个 | pass | pass 58 个 |

⚠️ 但 `run.articles` 里英文变体的 `words` 字段是 **0**（`{"id":"en-analyst","words":0}`，`run_720e83bdae91`），
因为登记时用了 `styles.cjk_len()`（纯英文自然得 0）—— 校验用的是对的 `text_len()`，**只有给前端的这个数字是错的**（§8-B6）。
另外文件名叫 `en-analyst.md`，不是 `PlatformSpec.file` 声明的 `en-thread.md`（§8-B7）。

---

## 7. 已知会失败的项（照实写，没有美化）

### 7.1 小红书：未登录（fail，需要人工扫码，本文无法自证修复）

```text
$ curl -s --noproxy '*' http://127.0.0.1:8000/api/platforms/xhs
{"state":"login_required","account":"","detail":"MCP 在线，但当前未登录（或登录已失效）",
 "endpoint":"http://127.0.0.1:18060"}
$ curl -s --noproxy '*' http://127.0.0.1:18060/api/v1/login/status
{"success":true,"data":{"is_logged_in":false}}      # MCP 本身 healthy
$ curl -s --noproxy '*' http://127.0.0.1:18060/health
{"status":"healthy","version":"dev"}
```

四条 run 的 `渠道状态：小红书` 全是 **fail**（detail 相同）。登录二维码入口是
`GET /api/platforms/xhs/login/qrcode`，扫码是人工动作 —— **本文没有登录过小红书，也没有投递过任何内容**。
注意「素材适配：小红书」在有了视频之后是 **pass（视频笔记）**：这条是素材适配，与登录态是两条独立 check，
不要把它读成「小红书能用」。

### 7.2 社区运营模块偶发失败（LLM 侧，非确定性）

同一段代码在同一份物料上：`run_d76ca9da493e` → `社区投放计划 **fail**：LLMError: 401 {"type":"error","error":{"type":"CreditsError","message":"Insufficient balance…"}}`；
`run_720e83bdae91` → fail（`模型输出不是合法 JSON`，输出被截断）；`run_c5451b582400` → **pass**
（`社区覆盖 pass 6 个社区（语言 en/zh）`、`草稿可用 pass`、`社区规矩 pass`、`数字可回溯 pass`，
产出 `publish/community.md` 21,454 B + `community.plan.json`）。失败时**只标 check，不影响发布结果**
（设计如此），本文如实记为「偶发、不确定」。另：401 之后我用同一个 LLM 客户端发过一次最小请求是成功的，
所以这不是长期余额耗尽，也不像是代码 bug。

### 7.3 video 时长：`run`（不是 fail），超目标 62%

`时长 pass if |成片 − 目标| ≤ max(45, 0.35×目标)`。实测：291.4s / 269.1s / 225.5s / 225.6s（目标 180s），
只有 `run_9105dc770228`（差 45.5s）与 `run_c5451b582400`（差 45.6s）卡在阈值内 → pass。
`run_d76ca9da493e` 差 111s → **run**，detail：`成片 291.4s / 目标 180s（旁白合计 1492 字）`。
即 `durationSec=180` 只是「旁白字数预算 + 目标」，**LLM 分镜的篇幅波动会突破它**；这是如实标注，不是隐藏。

### 7.4 知乎正文长度 fail（旧 run，新代码未复现）

`run_abb2805074e4`：`知乎 · 正文长度 fail 1930 字（要求 2000-4000）`。
本次三条新 run 的知乎正文分别是 2745 / 2891 / 2117 字，都在区间内 → pass。属于 LLM 偶发越界，如实记录。

### 7.5 B 站标题上限

`run_9105dc770228` 的 `素材适配：B站 **fail** —— 标题 83 字 > 80 字（B 站上限）`（因为出口标题是英文那 83 字符，§5）。

---

## 8. 发现但**没有修**的 bug（按严重度排序，附复现与证据）

> 按任务约定：本文只记录，不改 `app/` 代码。下面每条都能按「复现」独立验证。

### B1（高）后端重启后，进行中的 run 会永久卡在 waiting，且闸门放行**假成功**

- **现象**：`run_9105dc770228` 6 段里前 5 段 done（含真视频），`publish` 一直 `waiting`：
  `run.json` 里 `stage.gate.resolved="draft"`（已放行）、`run.status="waiting"`，但**没有任何协程在跑**，
  产物永远停在「素材包已落盘、回执未生成」（`publish` 段 `artifacts=[]`，磁盘上 `publish/<渠道>/export/` 每渠道 7 个文件、共 21 个：`title.txt` `content.txt` `tags.txt` `cover.png` `video.mp4` `publish_request.json` `README.txt`）。
- **复现**：建一条 run → 等它走到 `publish` 闸门（`status=waiting`）→ `./ops/stop_all.sh backend && ./ops/start_all.sh backend`
  → 再 `POST /api/runs/{id}/stages/publish/gate {"optionId":"draft"}`：**返回 204**，但 run 永远不动。
- **证据**：`var/logs/backend.log` 第 1 行 `Started server process [19167]`（02:07:15），
  闸门 `askedAt` = 1789754786310（02:06:26）；闸门 POST 出现在**重启之后**的日志里（第 247 行，`204 No Content`）。
  根因：`pipeline._tasks` 只在内存里，`store.load_all()` 只恢复数据不恢复任务；
  `Pipeline.resolve_gate()` 对「没有等待协程」的闸门照样置 `resolved` 并返回成功。
- **影响**：只要重启过后端（`start_all.sh`、运维重启、崩溃），所有在跑的 run 都变成永久僵尸，
  前端一直显示「等待确认」，而用户点「放行」得到 204 却毫无变化 —— 静默失败。

### B2（高）闸门/取消接口用 `JSONResponse(status_code=204, content=None)`，每次放行都在服务端抛异常

- **现象**：每一次成功的闸门放行，uvicorn 都会打一条 `ERROR: Exception in ASGI application`：
  `RuntimeError: Response content longer than Content-Length`（客户端仍收到 204，所以从 API 侧看不出来）。
- **复现**：`grep -n 'Exception in ASGI application' var/logs/backend.log` → 两处，**前一行都是闸门 POST 的 204**：
  248 行前是 `POST /api/runs/run_9105dc770228/stages/publish/gate → 204`；
  529 行前是 `POST /api/runs/run_c5451b582400/stages/understand/gate → 204`。
- **位置**：`app/main.py` 的 `resolve_gate`（以及同写法的 `cancel_run`）：204 不能带 body，
  但 JSONResponse 会渲染出 `null` 并带上自己的 Content-Length。
- **影响**：功能上没坏（闸门状态确实落盘了），但每条 run 每次放行都在日志里留一个假异常，会掩盖真异常（见 B1 的排查）。

### B3（高）多渠道共用**一份** `article/export/` 物料 → 知乎拿到的是小红书文案（或英文 thread）

- **现象**：`publish` 的 `collect_materials()` 读的是唯一一份 `article/export/{title,content}.txt`，
  三个渠道共用。于是：
  - `run_d76ca9da493e`：知乎长文 2745 字就在磁盘上（`article/zhihu-analyst.md`），
    但回执里 `zhihu.contentChars=921`、闸门写「知乎：将投递 **长文（921 字** + 4 张配图）」—— 921 字是**小红书**正文。
  - `run_9105dc770228` / `run_720e83bdae91`：出口是英文 thread → 知乎要投的是**英文**（2662 / 2848 字符）。
- **证据**：`run_d76ca9da493e/publish/receipts.json` 的 `material.contentChars=921` +
  同 run `article/zhihu-analyst.md` 的 `正文长度 pass 2745 字`；`run_c5451b582400` 对照：
  只有知乎变体时 `material.contentChars=3203`（= 知乎正文），说明取的就是「唯一那份 export」。
- **影响**：知乎这类长文平台实际拿到的是为小红书写的短文案；反过来，只选英文+知乎时知乎拿到英文。
  这是「一份物料投多渠道」的设计债，不是配置问题。

### B4（中）`export/` 兜底取「变体列表第一个 markdown 变体」，en 在前就用英文标题（并可能触发 B 站标题上限）

- **现象**：`generate.py` 的出口兜底（我跑的版本 461-481 / 当前 466-486）按 `ctx.run.articles` 顺序找第一个有 `# 一级标题` 的 `{platform}*.md`，
  en 变体排在前面时出口就是英文；`run_9105dc770228` 因此 `B站 素材适配 fail：标题 83 字 > 80`。
- **复现**：`variants=["en-analyst","zhihu-analyst"]` 建 run → `cat var/runs/<id>/article/export/title.txt` = 英文；
  把顺序换成 `["zhihu-analyst","en-analyst"]` 则出口变中文。合理的做法是优先选与发布目标同语种的变体（或让每个渠道各取所需，见 B3）。
- **证据**：两条 no-xhs run 的段日志都写着「已从「英文传播（X / LinkedIn） × 技术解读」取出口标题与正文」。

### B5（中）publish 找图片只认 `article/cards/p*.png` 与 `intake/images/fig-*.png`

- **现象**：`_pick_media()` 的兜底 glob 写死 `fig-*.png`。旧解析器把 4 张大图存成 `img-pXX-N.png` →
  `imageCount=0`，知乎适配变成「长文（2848 字，**无配图**）」（`run_720e83bdae91`）；
  新解析器改成 `fig-N.png` 后（`run_c5451b582400`）立刻变成「长文（3203 字 + **6 张配图**）」。
- **复现**：`ls var/runs/run_720e83bdae91/intake/images/`（`img-p17-1.png`…）对比
  `ls var/runs/run_c5451b582400/intake/images/`（`fig-1.png`…），再看两份 `publish/receipts.json` 的 `imageCount`（0 vs 6）。
- **影响**：图片是否被投出去**取决于 intake 的命名约定**，跨模块耦合在一行 glob 上；换解析器/换命名就会静默丢图。

### B6（低）`run.articles[].words` 对英文变体恒为 0

- **现象**：`generate.py` 登记 `words=styles.cjk_len(text)`，纯英文得 0 → 前端变体卡片会显示「0 字」。
- **证据**：`run_720e83bdae91/run.json` 的 `articles[0] = {"id":"en-analyst","words":0}`，
  而同 run 的 check 是 `正文长度 pass 443 词`。正确口径已在同文件 `styles.text_len(text, spec.unit)` 里，只是登记时没用。

### B7（低）`PlatformSpec.file` 是死字段：声明 `en-thread.md`，实际写 `en-analyst.md`

- **现象**：`_gen_markdown_variant()` 用 `stem = spec.id if voice == DEFAULT_VOICE else f"{spec.id}-{voice}"` 命名，
  全仓库没有一处读 `spec.file`。
- **证据**：`article/` 里实际是 `en-analyst.md` / `zhihu-analyst.md`；`styles.py` 里 `file="en-thread.md"`。

### B8（低）两处「字」的口径不一致

- `精读笔记` 的 detail 写「17991 字」，实际是**字符数**（`len(text)`），中文字只有 7404；
- `article` 产物 meta 的 `{"words": 2676}`（英文字符数）与 `run.articles[].words`（0）不同源。
  不影响判定，但会让人对不上数。

### B9（低）小红书渠道的 `needs` 文案与真实拦截口径不一致

- `GET /api/platforms` 返回 `needs:["扫码登录","6 张卡片图","标题 ≤ 20 字"]`，而代码里的硬约束是
  **计重 ≤ 38**（`TITLE_WEIGHT_LIMIT=38`，中文按 2 计）。实测标题「DeepRare：多智能体怎么做罕见病诊断」计重 34 通过、
  长度早就超过 20 个字 —— 展示给用户的规则比真实规则更严，容易误导。

### B10（提示）后端没有 `--reload`，进程里跑的是「启动那一刻」的代码

不是 bug 而是流程事实，但它直接造成了本次验证的版本漂移（§1.2）与 §8-B1 的僵尸 run：
改完代码不重启，跑着的服务一切照旧。建议至少把「进程启动时间 + 关键模块 sha256」暴露到 `/api/env`，
否则任何一次「我改了怎么没生效」的排查都要靠 `ps -o lstart`。

---

## 9. 没能验证的东西（不含糊其辞）

1. **真实投递**：全部 run 的 publish 闸门都只发过 `draft`，从未发 `continue`。
   所以「知乎/B 站真的能投出去」这件事，本文**没有验证**，也不要当成验证过。
2. **小红书登录态与图文/视频笔记投稿**：需要人工扫码，本文没有登录。
3. **`指令遵从度` 的另一条分支**（指令上限 > 平台上限 → run）与「一条机检约束都抽不出」的 `run` 分支：
   只在代码层确认，没有构造对应 brief 做端到端实测。
4. **LaTeX / arXiv 通道**：本机无 TeX 引擎（`latex.mode=source-only`），三条 run 都是 PDF。
5. **扫描件 OCR**：本机无 tesseract（`ocr=false`）。
6. **前端表现**：本文只验后端 API 与磁盘产物；前端是否把 4 张画布/两条视频/回执正确渲染不在本文范围。
7. **`run_9105dc770228` 的 publish 终态**：因为 §8-B1 卡死，没有回执总表可核对（其余三份 run 有）。
8. **多 run 并发下的资源争用**：本次最多 3 条 run 同时在跑（含 backend 轨道那条），未做压力验证；
   LLM 侧未出现明显并发限流（唯一失败是 §7.2 的社区步骤），但样本太少。
9. **模板里声明未使用的 `PlatformSpec.file` / 视频旁白 hint（`config.video.narration`）**：本次 run 都是空串，
   没验过非空行为。

---

## 10. 复现方式

```bash
# 1) 起后端（幂等；已占用会跳过）。注意本机设了 http_proxy，所有 localhost 调用都要 --noproxy
./ops/start_all.sh backend
curl -s --noproxy '*' http://127.0.0.1:8000/api/health

# 2) 跑一条完整 run（会自动放行 understand=continue、publish=draft；绝不发 continue 给 publish）
apps/papercast-server/.venv/bin/python var/scratch/verify6_e2e.py \
  var/samples/deeprare.pdf "xhs-author,zhihu-analyst" "做成知乎长文，重点讲方法，不要营销腔" runA
# 日志： var/scratch/verify6/runA.log   （每段状态变化 + 每次闸门放行 + 每条 check + 产物清单）

# 3) 复核任何一条 run 的全部数字（只读，不写 run 目录）
apps/papercast-server/.venv/bin/python var/scratch/verify6/collect.py run_d76ca9da493e

# 4) 视频自己再 ffprobe 一遍
var/toolchains/p2b/bin/ffprobe -v error -show_entries format=duration,size,bit_rate \
  -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels \
  -of default=noprint_wrappers=1 var/runs/run_d76ca9da493e/video/video.mp4
```

> 两个脚本都在 `var/scratch/verify6*`（运行态，不入库）：`verify6_e2e.py` 是驱动，
> `verify6/collect.py` 是证据收集器（阶段状态 / 每条 check / digest 统计 / 文案字数 / 海报几何 / ffprobe / 回执）。
> backend 轨道那份 `var/scratch/e2e_compact.py` 没有被改动。

### 产物路径速查（`<runId>` = §1.3 里的任意一条）

```text
var/runs/<runId>/run.json                      六段状态 + checks + 闸门 + 产物登记（唯一事实源）
var/runs/<runId>/intake/{paper.pdf,content.md,meta.json,figures.json,images/}
var/runs/<runId>/understand/{digest.json,digest.raw.json,reading_note.md}
var/runs/<runId>/article/{xhs.md,xhs.raw.json,<平台>-<人格>.md,export/{title,content}.txt,cards/p*.png}
var/runs/<runId>/poster/{poster.png,poster-xhs-long.png,poster-zhihu.png,poster-bili-cover.png,
                          poster.spec.json,poster.spec.cover.json,*.render.json}
var/runs/<runId>/video/{video.mp4,video-vertical.mp4,cover.png,narration.json,subtitles.srt,video.report.json}
var/runs/<runId>/publish/{receipts.json,<渠道>/receipt.json,<渠道>/export/*,community.md}
```
