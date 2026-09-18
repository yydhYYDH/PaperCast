# paper-share-skills 实跑笔记（Paper2Video / arXiv 2510.05096）

> 2026-09-19 · 视频分享 agent · 结论来自一次**真实跑通并投稿成功**的完整链路
> 上游：`reference/upstream/paper-share-skills`（commit `bd2f48a`，Apache-2.0）+ `reference/upstream/sustech-slides-template`（`55147b3`）
> 成片：[BV1DveU6GEPR](https://www.bilibili.com/video/BV1DveU6GEPR)（1920×1200，4 分 20 秒，34 页，中文旁白）

## 1. 一次跑通的命令序列（本机已验证）

```bash
# 工具链（都在 var/ 内，不装到系统）
#   var/toolchains/p2b          conda-forge: ffmpeg / poppler(+poppler-data) / tectonic
#   var/toolchains/bili-venv    venv: edge-tts / pdf2image / pillow / pymupdf / requests / biliup / psutil
WS=$(pwd)                                   # 工作区根
SK=$WS/reference/upstream/paper-share-skills
PP=$WS/var/runs/<runId>/video/论文分享/arXiv 2025 - PAPER2VIDEO
mkdir -p "$PP/slides-beamer" "$PP/video"

# 1) 模板 + 扩展主题（必须先替换打包版 sty，见 sustech-beamer-theme-fix）
cp -r $SK/paper-to-beamer/templates/sustech/. "$PP/slides-beamer/"
mv "$PP/slides-beamer/main_template.tex" "$PP/slides-beamer/main.tex"
cp $WS/reference/upstream/sustech-slides-template/sustech-theme/*.sty "$PP/slides-beamer/sustech-theme/"
cp "$PP/slides-beamer/sustech-theme/"*.sty "$PP/slides-beamer/"   # tectonic 不认 TEXINPUTS，主题 sty 要放到主文件同目录

# 2) 编译（tectonic 会把需要的宏包拉进 TECTONIC_CACHE_DIR）
export PATH=$WS/var/toolchains/p2b/bin:$PATH
export XDG_CACHE_HOME=$WS/var/cache TECTONIC_CACHE_DIR=$WS/var/cache/tectonic
cd "$PP/slides-beamer" && tectonic main.tex

# 3) 逐页旁白 → 视频（render → narrations → tts → assemble → cover → metadata）
export POPPLER_DIR=$WS/var/toolchains/p2b/bin
export FFMPEG=$WS/var/toolchains/p2b/bin/ffmpeg FFPROBE=$WS/var/toolchains/p2b/bin/ffprobe
export EDGE_TTS_VOICE=zh-CN-XiaoxiaoNeural EDGE_TTS_RATE=+15%
$WS/var/toolchains/bili-venv/bin/python $SK/paper-slides-to-video/scripts/slides_to_video.py \
  full "$PP" --annotated-tex video/main_with_narration.tex

# 4) 投稿（dry-run 先看，再真投）
export HOME=$WS/var/home USERPROFILE=$WS/var/home    # cookie 落 var/home/.bilibili/cookies.json
$WS/var/toolchains/bili-venv/bin/python $SK/paper-bilibili-uploader/scripts/upload.py "$PP" --series --dry-run
$WS/var/toolchains/bili-venv/bin/python $SK/paper-bilibili-uploader/scripts/upload.py "$PP" --series

# 5) 转成 PaperCast 的 D1 契约
$WS/var/toolchains/bili-venv/bin/python $WS/ops/make_run_video_artifacts.py --paper-dir "$PP" --run-dir $WS/var/runs/<runId>
```

## 2. 踩过的坑（都是本机真实报错）

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `File 'beamerthemesustech.sty' not found` | tectonic **不读 `latexmkrc`**，也不认 `TEXINPUTS=./sustech-theme//` | 把三个 `.sty` 复制到 `main.tex` 同目录（`sustech-theme/` 仍保留，主题里的 assets 按相对路径找） |
| `Missing language pack for Adobe-GB1`（pdftoppm） | poppler 缺 `poppler-data` | 装 `poppler-data` 到 `var/toolchains/p2b` 并设 `POPPLER_DIR`；实测只是告警，渲染内容与 pymupdf 抽页一致（墨迹覆盖率对比差 <5pp） |
| `Missing character ... in font nullfont` | 主题标题页模板里少数数字走在无字体上下文 | 只出现在日志，PDF 文本抽取显示数字完整；无 Overfull/Underfull |
| `biliup login` 报 `IO error: not a terminal` | biliup 的登录菜单需要 TTY | 用 `pty.fork()` 驱动：读到「扫码登录」后发 `\x1b[B\r`；二维码 PNG 在 CWD 生成，脚本 CWD 放到 `var/home`，避免污染工作区根目录 |
| 投稿返回 `21005 Tag不能为空，总数量不能超过12个，并且单个不能超过20个字` | 元数据把 `arXiv 2510.05096 · NeurIPS 2025 SEA Workshop` 当标签，**43 字 > 20 字上限** | 标签改短（`arXiv 2510.05096`）；dry-run 只校验「非空」，**不校验 B站的长度限制**，必须真投才知道 |
| 真投回执不见了 | series 模式的回执写在 `bilibili-series/video/upload_result.json` | 归档时同时拷到 `var/runs/<runId>/video/upload_result.json` |

## 2.5 中文渲染事故（2026-09-19，已修）：poppler 渲染不了 fandol

**症状**：成片里大量中文「整段空白」——纯中文 span 全丢，含英文/数字的 span 正常（例如一行只剩
`PaperTalker 101 0.842`，中文全不见）。PDF 用浏览器看是正常的，**只有 poppler 渲染出的帧有问题**。

**定位方法**（可复用）：把 PDF 的文本层与渲染图像按 span 对齐 —— 逐 span 取 bbox，
在渲染图里量该 bbox 的墨迹比例，比例≈0 就是「文本层有字、实际没画出来」：

```bash
# 见 var/scratch/check_invisible.py：pdf span bbox × 渲染 PNG -> 墨迹比例
python check_invisible.py <slides-beamer 目录>        # 输出 "invisible spans: N"
```

- 用 conda 版 poppler 渲染：**上百个 span 渲染为空**，全部是 `FandolHei-Regular/Bold`（ctex 默认字体）；
- 同一 PDF 用 PyMuPDF 渲染：**0 个**（说明 PDF 本身没问题）；
- 同一页墨迹覆盖率：poppler 明显低于 PyMuPDF，差值就是丢失的中文。

**根因**：ctex 默认字体集 `fandol` 生成 Type0/Identity-H 的 CJK 子集，
本机 conda 版 poppler 解析不了，报 `Missing language pack for 'Adobe-GB1' mapping` /
`Unknown font tag 'F1'` / `No font in show/space`，于是整段中文不画。装 `poppler-data` +
设 `POPPLER_DATADIR` `POPPLER_DIR` **都不能解决**（试过）。

**修复（已采用）**：把 deck 的中文字体换成系统 TTF —— 在 `main.tex` 导言区加

```latex
\setCJKsansfont{Microsoft YaHei}
\setCJKmainfont{Microsoft YaHei}
\setCJKmonofont{Microsoft YaHei}
```

（本机字体来自 `~/.local/share/fonts/waic/msyh.ttc`，`fc-list :lang=zh` 可见。）
换完后同一条流水线：poppler / PyMuPDF / 浏览器 渲染一致，校验 **invisible spans: 0**，
封面与 34 页帧全部完整。

**备选（未采用但可用）**：`var/toolchains/pdfshim/` 提供 `pdftoppm`/`pdfinfo` 兼容外壳（PyMuPDF 后端），
流水线支持 `PDFTOPPM=<目录>/pdftoppm` 覆盖渲染器，两种输出方式（写文件 / 写 stdout 的 PPM）都已实现并实测。
遇到别的 PDF 渲染器搞不定的字体时可以用它兜底；`PDFSHIM_DPI_SCALE=1.6` 还能提高渲染分辨率。

## 2.6 小红书竖版（自己补的，上游没分发）

上游 README 里的 `rednote-video-uploader`（"竖版视频 + 小红书发布"）属于**私有配套技能，不随仓库分发**，
所以竖版这条链路是我们自己补的：`ops/make_portrait_video.py`。

```bash
python ops/make_portrait_video.py \
  --video-dir <run>/video \
  --slides-tex <run>/video/main_with_narration.tex \
  --slides-pdf <run>/slides-beamer/main.pdf \
  --speed 1.25                     # 1.0 = 自然语速（成片会更长）
```

产物在 `<run>/video/xiaohongshu/`：

| 文件 | 说明 |
| --- | --- |
| `xhs_vertical.mp4` | 1080×1920 竖版成片（模糊背景 + 卡片幻灯片 + 烧入字幕 + 序号/页脚/进度条） |
| `cover_xhs.png` | 1080×1440（3:4）封面 |
| `xiaohongshu_meta.json` | 标题/正文/话题标签/时长/分辨率 |
| `frames_portrait/`、`subtitles/` | 逐页版式图与逐页 ASS 字幕（可复用、可手改） |

实现要点：

- **字幕在提速之前烧入**：每页用自然语速时间轴生成 ASS，滤镜链 `subtitles → setpts=PTS/1.25`，
  音频 `atempo=1.25`，这样字幕跟着画面一起提速，**只需一次编码**（逐页编码后 `concat -c copy`）。
- 字幕切句按标点切 + 按字符数比例分配时间（edge-tts 语速恒定，误差 <0.3s）；
  段内首尾的静音（分片 = 配音 + 约 1.0s 尾部 pad）已计入。
- 每页标题**优先从 deck 源码还原**（`\section{}` → 分隔页、`\begin{frame}{}` → 内容页，顺序与 PDF 一致，
  34 页对得上），空标题再用 PDF 启发式兜底。
- 字体经 `fc-match` 解析（不写死路径）；ffmpeg/ffprobe 先查 PATH，再回落 `var/toolchains/p2b/bin`。
- 版式：顶部序号胶囊 + 标题（≤2 行），中部 16:10 白色圆角卡片，字幕区在 y≈1440–1560，底部页脚 + 进度条。

## 3. 契约与产物

- 旁白 gate：`main_with_narration.tex` 里 `% NARRATION:` 注释条数必须**等于物理页数**（含 `\section` 自动生成的章节分隔页），脚本按源码顺序对页，多一条少一条都 fail-closed。
- 生成器 `ops/make_narration_tex.py`（本次用的就是它）：按 `\renewcommand{\secblurb}` → 分隔页、`\begin{frame}` → 内容页的顺序注入旁白，输入是 34 条中文口播。
- 成片时长：per-slide 片段 `slide_NNN_final.mp4` 之和 ÷ `speed`(1.25) ≈ 259.8s，与 mp4 实测 260.6s 一致；`ops/make_run_video_artifacts.py` 用同一换算写进 `narration.json.durationSec`。
- 横屏 vs 竖屏：竖屏要非公开的 `rednote-video-uploader/scripts/portrait_video.py`，本机没有 → 走 uploader 的 `--series` 通道（只投横屏、无需 P2）。
