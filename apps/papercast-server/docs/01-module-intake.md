# M1 · 论文处理（intake）

**目标**：任何形态的论文输入，都归一化成同一种「机器可读 + 人可读」的中间形态 ——
**Markdown 正文 + 独立图片文件 + 结构化元数据**。下游 M2 只认这一种形态，不再关心输入是 PDF 还是 LaTeX。

## 1. 输入与通道选择

| 输入 | `SourceInput.kind` | 通道 | 说明 |
| --- | --- | --- | --- |
| 上传的 PDF | `pdf` | `pdf_parser` | 主通道，保真度最好 |
| arXiv id / URL | `arxiv` | `arxiv` → `pdf_parser`（+ 源码包） | 先下载 PDF 走 PDF 通道；同时下源码包做章节结构补强 |
| LaTeX 工程（zip 或目录） | `latex` | `latex_parser`（有 PDF 则回退 PDF 通道） | 本机没有 LaTeX 引擎，见「边界」 |

`SourceInput.value` 的归一化规则：

- arXiv：`2510.05096`、`arXiv:2510.05096`、`https://arxiv.org/abs/2510.05096`、`https://arxiv.org/pdf/2510.05096v2` 全部接受，
  统一解析成 `{arxivId, version?}`。
- LaTeX：接受 `.zip` 压缩包或已解包目录路径；入口 `.tex` 取 `main.tex`，否则取第一个含 `\documentclass` 的文件。
- PDF：`POST /api/uploads`（multipart）落盘后，把返回的 `uploadId` 作为 `value`。

## 2. PDF 通道：PyMuPDF 解析

单页处理管线（`app/intake/pdf_parser.py`）：

```text
page.get_text("dict")   → 带 bbox/字号/字体的块
  ├─ 字号阶梯 + 加粗标志    → 标题层级 H1..H4（相对正文中位字号）
  ├─ 段落块                 → 正文段落（按栏内 y 排序，处理双栏）
  ├─ page.find_tables()     → 表格 → Markdown 表格 + 表格区域裁图 PNG
  ├─ page.get_image_info()  → 位图 → images/（过滤装饰性小图）
  └─ 矢量图回退             → 图区域 clip 渲染成 PNG（保证图在 md 里"看得见"）
图注关联：正则 ^(Figure|Fig\.|Table)\s*\d+ 找到 caption 块，
          与其上下 120pt 内最近的图/表块配对 → 文件名 fig-3.png / table-2.png
```

产出：
- `content.md`：`# 标题` → `## 章节` → 正文段落，图片以 `![Figure 3: caption](images/fig-3.png)` 内联，
 表格用 Markdown 表格，公式保留为 `$...$` / `$$...$$` 文本（前端 KaTeX 渲染）。
- `images/`：`fig-*.png`（图，按 caption 编号）、`table-*.png`（表格区域高分辨率裁图）、
  `page-*.png`（兜底整页渲染，仅在局部抽取失败时生成）。
- `sections.json`：`[{level, title, anchor, page, figureIds[]}]` —— M2 的阅读地图。
- `meta.json`：标题、作者、来源类型与值、页数、字节数、`sha256`、解析引擎与耗时。

**图片质量开关**：位图优先按 `xrefs` 直抽原始流（无损、原始分辨率）；
矢量图/组合图按 `bbox` 以 `zoom=3`（约 216 dpi）渲染，保证小红书卡片不糊。

## 3. arXiv 通道

1. `GET https://export.arxiv.org/api/query?id_list=<id>` 取元数据（标题/作者/摘要/日期/分类），**不抓 HTML 页**。
2. `GET https://arxiv.org/pdf/<id>` 下载 PDF（本机实测 200 / 5.2 MB / 19 页）→ 交给 PDF 通道。
3. `GET https://arxiv.org/e-print/<id>` 下载源码包（可选，默认开）→ 解包到 `intake/latex/`，
   仅用于补强章节标题与图表 caption，解析失败不阻塞主流程。
4. 两条通道都失败时报 `arXiv_METADATA_FAILED` / `arXiv_PDF_FAILED`，阶段置 `failed` 并在日志里给出原始 URL。

不使用 `arxiv.py` 等第三方库：直接打官方 API，少一个依赖、行为可控。

## 4. LaTeX 通道

`app/intake/latex_parser.py`，一个**刻意保持简单**的转换器（不是完整 TeX 引擎）：

- 结构：`\section`/`\subsection`/`\subsubsection` → `##`/`###`/`####`；`\title`/`\author`/`\begin{abstract}` → 文档头。
- 正文：`\input`/`\include` 递归展开；`\textbf`/`\emph` 映射；`% 注释` 剥离；`\cite` 保留为 `[\cite{...}]` 可读标记。
- 公式：`equation`/`align` 环境 → `$$...$$`，行内 `$...$` 原样保留。
- 图：`\includegraphics{fig/x.pdf}` → 用 PyMuPDF 把 PDF/EPS 图转 PNG 存入 `images/` 并内联；
  `\caption{}` 作为 alt 文本。找不到文件时保留占位并记 `warn`（不静默丢图）。
- 表：`table`/`tabular` 环境尽量抽成 Markdown 表格；结构过于复杂时保留为代码块并记 `warn`。

## 5. 阶段校验（`stage.checks`，前端会显示）

| check | 通过条件 |
| --- | --- |
| 正文抽取 | `content.md` 字数 ≥ 1500 且含 ≥ 3 个章节标题 |
| 图片抽取 | `images/` ≥ 1 张，且 md 中每个 `![]()` 路径都真实存在 |
| 元数据 | 标题非空（arXiv 通道必须与 API 返回一致） |
| 图片引用 | md 中引用的图全部能在 `sections.json` 找到归属章节 |

任何 check `fail` 不阻塞 M2（小红书文案容得下缺图），但会在 `run.stages[0].checks` 里如实标红。

## 6. 边界与已知限制

- **没有 LaTeX 引擎**：本机无 `pdflatex`/`xelatex`/`latexmk`，LaTeX 输入不能编译成 PDF，
  只能走源码解析通道，所以排版信息（分栏、浮动体位置）会丢失。装上 TeX Live 后可开启「源码 → 编译 PDF → PDF 通道」，
  在 `config` 里把 `latex.compile` 打开即可，代码路径已预留。
- **扫描件无 OCR**：本机无 `tesseract`。纯扫描 PDF 抽不到文字时，阶段转 `failed` 并提示
  「需要 OCR 依赖（tesseract-ocr / PaddleOCR）」，不会假装成功。
- **复杂表格**：`find_tables()` 对跨页表、无框线表会漏；此时退回区域裁图 + 原文 caption，数字仍可从正文读到。
- 不抓 HTML 版论文页（易被反爬且结构漂移），只走 PDF/源码两条官方通道。

## 7. 图注匹配失效与修复：Nature/Springer 排版（2026-09-19）

**症状**：`var/samples/deeprare.pdf`（Nature，doi:10.1038/s41586-025-10097-9）跑出来是
「4 张图（fig 0 / table 0 / 未匹配 4）」，4 张的 caption 全是占位符、kind 全是 `img`。
同一套代码对 `var/samples/paper2video.pdf`（arXiv:2510.05096）是正确的（fig 8 / table 4）。

### 7.1 证据（先量了再改）

把 23 页的文本块、位图块、矢量块坐标（`get_text("dict")` / `get_image_info()` / `get_drawings()`）
全打出来之后，事实是：

| 观测 | 数值 |
| --- | --- |
| 文字层 | 有：正文页每页 3.6k~8.8k 字符，**不是扫描件**（这条假设被排除） |
| `CAP_RE` 在 23 页的命中数 | **0** —— 图注驱动一张都没抽到，只剩兜底路径的 4 张内嵌位图 |
| 该刊图注首行 | `Fig. 2 \| HPO-wise cross-dataset evaluation …`、`Extended Data Fig. 1 \| Overview …`、`Extended Data Table 1 \| Multi-center …`：**分隔符是竖线 `\|`，不是 `:` 或 `.`** |
| 图注与图的相对位置 | 正常（图在上、图注在下）：p17 位图 bbox `(40,49,561,521)`、图注首行 `(39.7,524.4,295.9,533.1)`，间隔 3.7pt |
| 跨栏整幅图 | 图注只占左栏（x 39.7~295.9），图占满两栏（x 40.4~560.6） |
| 纯矢量图 | p5 的 Fig. 2 是柱状图，352 条 drawing 里**过得了 `w>12pt` 过滤的是 0 条**（窄柱实测 10.7pt 宽）→ 视觉元素集合为空 → 带扩展没有锚点 |
| 同页多图注 | p8 一页有 4 条图注（Table 2 / Figure 6 / Table 3 / Table 4） |

被排除的其他假设：①「扫描件没有文字层」——每页都有完整文字层；
②「图注写在正文段落里而不是紧邻图」——图注是独立的一行（p17 y=524.4），与图只差 3.7pt；
③「Fig. 与 Figure 混用」——`CAP_RE` 本来就同时接受两者；
④「编号格式 `Fig. 1a`」——正文里的 `Figure 1c presents …` / `Table 1, our study uses …`
是交叉引用，本来就不该当图注（修复后仍不当图注，见 7.5 末条）。

### 7.2 根因与改法（`app/intake/pdf_parser.py`）

| # | 根因 | 改法 |
| --- | --- | --- |
| 1（主因） | `CAP_RE` 只认 `Figure/Fig./Table` + 编号 + `[:.]`，认不出出版社排版用的竖线分隔符，也认不出 `Extended Data`/`Supplementary` 前缀 → 全文 0 命中 | 正则加可选前缀与 `\|` 分隔符；`kind` 改从**匹配到的关键字**取（原先按整行开头判，`Extended Data Table 1 \| …` 会被误判成 `fig`） |
| 2 | 跨栏整幅图按图注所在栏的宽度裁，只得到左半张（`_best_raster` 覆盖率 0.51 < 0.65，连位图直抽也退化成渲染半张图） | 新增 `_x_extent()`：裁剪框横向 = 图注所在栏 ∪ **纵向落在带内的视觉元素的横向并集**；纯文本块不参与并集，避免把邻栏正文并进来。横向变宽后用新宽度重扫纵向带（≤3 轮，只做并集、不收缩） |
| 3 | 柱状图的窄柱被 `w>12pt` 整类滤掉，纯矢量图视觉元素集合为空 | 视觉元素判据改成「有实体面积」（`w,h > 3pt` 且面积 > 60）；与图注列的横向重叠门槛对视觉元素放宽到 1pt（文本块仍是 12pt） |
| 4 | 带扩展的间距容忍是 16pt，而该刊图与图注、图内多面板之间的留白实测 20~60pt，会在图中间截断 | `_band()` 候选分四类：**visual** 放宽到 `GAP_TOL_VIS=96pt`；**para（正文段落）与 cap（另一条图注）是硬边界**；label（图内短标签）够不着就跳过而不是中断（原来一个离得稍远的刻度标签就会把带切在图中间） |
| 5 | `Extended Data Fig. 1` 与正文 `Fig. 1` 编号相撞，会互相覆盖 `fig-1.png` | Extended Data / Supplementary 的图注 id 加 `ed` 中缀（`fig-ed1.png`、`table-ed1.png`） |

裁剪框的留白（图：上边 `-4` / 图注底 `+2`；表：图注顶 `-3` / 下边 `+4`）**刻意保持原值**：
这类「修一类排版」的改动最容易顺手改掉所有已能用的样本的裁剪像素。

### 7.3 两样本对比（同一份代码、同一次运行）

| 样本 | 图数 | fig | table | img（未匹配） | 说明 |
| --- | --- | --- | --- | --- | --- |
| deeprare.pdf 修复前 | 4 | 0 | 0 | 4 | caption 全是「（第 N 页内嵌图像 i，未匹配到图注）」 |
| **deeprare.pdf 修复后** | **9** | **8** | **1** | **0** | 9 张全部带真图注 |
| paper2video.pdf 修复前 | 12 | 8 | 4 | 0 |  |
| **paper2video.pdf 修复后** | 12 | 8 | 4 | 0 | 产物**逐字节相同**（content.md / figures.json / sections.json / images/*.png；只有 meta.json 的 `elapsedSec` 变） |

deeprare 修复后逐张（caption 前 40 字）：

| id | 页 | source | 尺寸(px) | caption |
| --- | --- | --- | --- | --- |
| fig-1 | 3 | render | 1184x1302 | `Fig. 1 \| DeepRare: an agentic framework for rare` |
| fig-2 | 5 | render | 1156x936 | `Fig. 2 \| HPO-wise cross-dataset evaluation and c` |
| fig-3 | 6 | render | 1182x1437 | `Fig. 3 \| DeepRare diagnostic performance. a, Com` |
| fig-4 | 7 | render | 1261x903 | `Fig. 4 \| Human expert validation of traceable re` |
| fig-5 | 8 | render | 1182x939 | `Fig. 5 \| Ablation study of the DeepRare system.` |
| fig-ed1 | 17 | raster | 3251x2948 | `Extended Data Fig. 1 \| Overview of the DeepRare` |
| fig-ed2 | 18 | raster | 3251x2427 | `Extended Data Fig. 2 \| Cohort curation pipeline` |
| fig-ed3 | 19 | raster | 3251x3445 | `Extended Data Fig. 3 \| The five-stage DeepRare` |
| table-ed1 | 20 | raster | 3251x1071 | `Extended Data Table 1 \| Multi-center benchmark` |

fig-ed1/2/3 与 table-ed1 走 `source=raster`（整张位图无损直抽），裁剪框覆盖整张位图（覆盖率 > 0.65）。
另外还做了一组负向对照：3 份非论文类 PDF（Anthropic / Apple 的技术文档、一份 slides 模板）
修复前后的图数完全一致（8 / 47 / 0），没有出现"正则放宽后到处误报图注"。

### 7.4 无文字图注时的降级语义

单张图确实拿不到文字图注时（图注本身就是图片、整页扫描、或图元离任何文字都很远），
仍按位置兜底：`kind="img"`、`number=""`、caption 写
`（第 N 页内嵌图像 i：无文字图注，按位置归类）`，并打一条 `warn`：

> 兜底按位置补抽 N 张内嵌图像：这些页没有可识别的文字图注（图注本身是图片、或整页是扫描图），kind=img、无 caption，仅按页面位置归类

即：**归类为图（`img`），不再表述成「未匹配」**；下游按 kind 分流时不会把它当成空白，
但也不要指望它有 caption。

### 7.5 仍未解决 / 适用边界

- **图注紧贴整幅宽长文本块的表格仍抽不出**：paper2video 第 8 页
  「Table 3: Generation cost for each method.」的图注底（y 572.9）下 1pt 就是一个整幅宽、
  行长 ≥55 的文本块（y 573.9~686.5，它同时含 Table 4 的行），被判成「正文段落」硬边界，
  于是该表继续只留图注文字 + 一条 warn。修复前后**行为一致**（都是 12 张、1 条 warn），
  要修得先区分「表格行」与「正文段落」，不在本次范围。
- **整页排版图**：deeprare fig-4（p7）的图元铺满整页，裁剪框取到 `y=0`（内容从 y≈5 起）；
  图内自带的长文本（例如参考链接列表）会被算进裁剪框，肉眼看着像正文 —— 这是整页图的固有形态，
  不是把正文误吃进来（该页真正的正文段落各自成块，都在框外）。
- **判定依赖「正文段落」这条硬边界**：若某份 PDF 的正文不成块（整页排成极少数大块），
  带扩展仍可能过量，表现是裁剪框偏大（多含空白/邻栏），不会变成语义错误。
- 该刊正文的 Table 1 在这份 PDF 里**没有图注行**（只有 p2 正文里的交叉引用句子
  `Table 1, our study uses …`），所以修复后也不会凭空多出一张 Table 1：
  交叉引用被 `REF_RE` 与「编号后必须紧跟 `[:.\|]`」两重条件挡住。

### 7.6 对下游的影响（poster / video）

- 修复前 deeprare 的 4 张全是 `kind="img"`、caption 是占位符：check 显示「未匹配 4」，
  而 `app/modules/video.py:489` 的分镜配图逻辑专门为这种图写了降级说明
  （"标了「未匹配到图注」的原图"）。修复后这 4 张变成带图注的 fig/table，
  **video 分镜挑图时能按 fig/table 语义命中**，poster 的图表版式也有真正的 fig/table 可用。
- deeprare 还多出 5 张此前**完全没被抽出**的矢量图（fig-1~fig-5，此前只有 4 张内嵌位图）：
  图片总量 4 → 9，`content.md` 多出 9 处 `![]()` 内联（+1368 字符）。
- 归类口径变化只影响 `figures.json` 的 `kind`/`number`/`caption`/`id` 与新增的图片文件；
  `fig-*` / `table-*` 的命名约定不变，`sections.json` 的 `figureIds` 仍是这些文件名。

### 7.7 复现（不需要起 FastAPI）

```bash
# 直接跑解析 + 对比表（脚本在 var/scratch，属一次性产物）
apps/papercast-server/.venv/bin/python var/scratch/intake_figcheck.py \
    var/samples/deeprare.pdf var/samples/paper2video.pdf --out /tmp/intake-check
# 图注分类 / 无文字层降级的边界用例（14 条分类 + 1 条降级路径）
apps/papercast-server/.venv/bin/python var/scratch/intake_edgecheck.py
# 后端单测（纯函数/契约，不联网）
cd apps/papercast-server && .venv/bin/python -m pytest -q
```

不起服务、只 import 模块的最小复现：

```python
import sys; sys.path.insert(0, "apps/papercast-server")
from pathlib import Path
from app.intake.pdf_parser import parse_pdf
res = parse_pdf(Path("var/samples/deeprare.pdf"), Path("/tmp/intake-out"), log=print)
print(len(res.figures), [f.kind for f in res.figures])
```
