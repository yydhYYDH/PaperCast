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
