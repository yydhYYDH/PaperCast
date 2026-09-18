# 07 · 海报与卡片出图（A/B/C 三条路）

> 对应 L2 生成层：海报（`poster` 阶段，本轮从 `skipped` 变成可跑）、小红书 3:4 卡片（`article/cards`）。
> 版本：R1.5 · 2026-09-19 · 状态：A/B 已跑通真数据，C（AI 出图主视觉）待 `DASHSCOPE_API_KEY`

---

## 1. 一句话结论

**论文"出图"是两件不同的事，别混在一起：**

| 想要的图 | 本质 | 需要文生图模型吗 | 本仓库怎么出 |
| --- | --- | --- | --- |
| 会议海报、信息图、小红书长图/卡片 | 排版合成（HTML/CSS 或 PIL） | ❌ 不需要 | `app/modules/poster.py` · `app/cards/render.py` |
| 论文原图（teaser / 方法图 / 实验图） | 从 PDF/LaTeX 里抠 | ❌ 不需要 | `app/intake/latex_parser.py`（PyMuPDF 3x 渲染） |
| 封面、主视觉、"重画一张好看的" | 真·文生图 | ✅ 需要 | `ops/imagegen.sh`（baoyu-image-gen，千问等） |

这条分工是 ADR #5「确定性排版优先于 AI 出图」的落地：**论文内容用排版保证准确，创作型视觉才交给模型。**

## 1.5 画布矩阵：一张图放哪里、放多大

**48×36 英寸那张是印刷件，不是投放件。** 我们的渠道全是数字屏，各渠道要各自的像素画布；窄画布上必须**减内容**，不是把字缩小。

| 渠道 / 用途 | 预设 | 像素 | 栏数 | 目标正文 | 谁用 |
| --- | --- | --- | --- | --- | --- |
| 会议海报 / 打印 / 存档 | `conf` | 2304×1728（48×36in@48dpi） | 3 | 18px≈27pt | 组会、答辩、会议墙报 |
| 知乎 · 公众号正文横版图 | `zhihu` | 1600×1200（4:3） | 3 | 16.5–22px | 文章内嵌，可点开放大 |
| B 站/知乎横版**信息图** | `bili` | 1920×1080（16:9） | 3 | 17px | 一屏讲清方法的横图 |
| 小红书首图（封面） | `xhs` | 1080×1440（3:4） | 1 | 26–30px | 组图第 1 张，只放 hero + 几句话 |
| 小红书/知乎 竖长图（信息图） | `xhs-long` | 1080×2400（3:4 长） | 1 | 23–26px | 一图讲完整篇论文 |
| 小红书正文卡片 | （`app/cards/render.py`） | 1080×1440 ×N | — | PIL 固定版式 | 组图第 2..N 张 |
| B 站视频封面 | `bili-cover` | 1920×1080（16:9） | cover 版式 | 标题 212px | 视频封面：暗底 + 大标题 + 主视觉 |

> 公众号封面（900×383）按 2026-09-19 的决定**不做**；`wechat` 预设已从代码里移除。

**为什么必须按渠道重排而不是缩放**：CSS 尺寸用 `cqw`（相对画布宽度），同一份 CSS 放到 1080 宽的画布上，正文字号就只有 2304 宽时的 47% —— 会掉到 10px 左右，手机上完全看不清。
所以 `poster.py` 按 `body_px`（目标正文像素）反推基础倍率，并设 `LEGIBILITY_FLOOR=0.75`：字号最多缩到目标值的 75%，再小就**判失败**，提示去减内容或换更大的画布。

实测（arXiv 2510.05096）：

| 预设 | 结果 |
| --- | --- |
| `conf` 2304×1728 | ✅ body 18px / `panel_fill` 0.979 |
| `zhihu` 1600×1200（用 `poster.spec.wide.json`） | ✅ body 16.5px（刚好在下限） |
| `bili` 1920×1080（用 `poster.spec.wide.json`） | ✅ body 17.2px |
| `bili-cover` 1920×1080（用 `poster.spec.bili-cover.json`） | ✅ **标题 212px**（占宽 11%，视频封面量级） |
| `xhs` 1080×1440（用 `poster.spec.cover.json`） | ✅ body 25.7px |
| `xhs-long` 1080×2400（用主 spec） | ✅ body 22.8px / fill 0.944 |
| `zhihu` + 主 spec（8 个块塞 4:3） | ❌ 装不下 —— 这就是"必须按渠道砍内容"的证据 |
| `xhs` + 主 spec | ❌ 同上（21 条 bullet 塞不进 3:4 一栏） |

同一份内容预算下，**竖长图（1080×2400）是唯一能装下"论文全貌信息图"的数字画布**；首图和横版都必须砍到 3 个块左右。窄画布用 `items_tall` 提供更短的条目、用 `sizes: ["wide"]` 把次要块排除。

### cover 版式（视频封面）

封面不是"缩小版海报"，是另一种版式：spec 里写 `"layout": "cover"`（不需要 `columns`），渲染成**暗底渐变 + 左侧大标题/副标题/标签 + 右侧主视觉卡片**。
字号比海报大一个量级（`h1` 用 4.25cqw 而不是 3.0cqw），并且这类内容很少，所以预设用 `scale_start` **从大倍率往下二分**（`bili-cover` 从 2.6 起），求"能放多大放多大"—— 而不是海报那种"刚好不溢出"。
主视觉位（`.art`）就是路线 C 的 AI 生图落点：把 `fig-1-teaser.png` 换成千问出的 hero 即可。

### 落到 run 目录的哪里

```
var/runs/<runId>/
├── article/cards/p1..pN.png        ← 小红书组图（3:4，1080×1440）
├── poster/poster.png               ← 会议海报（打印/存档）
├── poster/poster-xhs-long.png      ← 小红书/知乎竖长图
├── poster/poster-zhihu.png         ← 知乎正文横版
├── poster/poster-bili.png          ← B 站封面
├── poster/poster.spec*.json        ← 版面描述（可复现、可换后端重排）
└── publish/export/                 ← 投放兜底：title/content/首图
```

---

## 2. 路线 A · 会议海报（`app/modules/poster.py`）

### 设计

```
digest.json / 论文原文
      ↓ （人/Agent 写成 poster.spec.json：标题、作者、栏目、引用哪些图）
poster.py: spec → poster.html（cqw 版式，与像素无关）
      ↓ ops/shot/render.mjs（chrome-headless-shell，横切 B 渲染底座）
      ↓ 二分字号 --s：从 1.0 往下找到「不溢出的最大字号」
poster.png（默认 48x36 in @ 48dpi = 2304x1728）+ poster.render.json（几何自检）
```

- **内容与版式分离**：`poster.spec.json` 只描述"放什么"，`poster.py` 决定"怎么排"。换一篇论文只需要换 spec。
- **字号自适应**：全篇字号/间距都乘一个统一变量 `--s`，二分求"不溢出的最大字号"。这是 Paper2Poster 的 Painter-Commentor 循环的机械化版本 —— 不需要视觉模型，结果可复现。
- **几何闸门**：渲染时用 DOM 实测每个 `[data-panel]` 的 `scrollHeight/clientHeight`，溢出即失败；`panel_fill`（正文面板面积 / 三栏面积）反映"栏内是否留大片空白"。

### 命令

```bash
cd apps/papercast-server
.venv/bin/python -m app.modules.poster \
  --spec   "$WS/var/samples/papercast-lab/paper2video/poster/poster.spec.json" \
  --out-dir "$WS/var/samples/papercast-lab/paper2video/poster" \
  --figures-dir "$WS/var/samples/papercast-lab/paper2video/intake/images" \
  --size 48x36 --dpi 48
# 数字渠道用 preset（像素画布 + 目标字号 + 栏数），例如：
#   --preset xhs-long --out-name poster-xhs-long
#   python -m app.modules.poster --list-presets
```

打印的 JSON 就是验收口径：`ok` / `overflow` / `broken_images` / `panel_fill` / `scale`。退出码 3 表示几何闸门不过。

### 实测（arXiv 2510.05096 Paper2Video）

`scale=0.81`（即字号是设计值的 81%）、8 个面板、`overflow=[]`、`broken_images=[]`、`panel_fill=0.9786`、`ok=true`。
二分过程：`1.0 溢出 307px → 0.45 通过 → 0.725 通过 → 0.8625 溢出 106px → 0.7937 溢出 31px → 0.7593 通过 → 0.7765 溢出 5px`，7 次尝试收敛。

---

## 3. 路线 B · 小红书 3:4 卡片（`app/cards/render.py` + `scripts/make_cards.py`）

卡片渲染本来就是确定性的（PIL 直接画，1080x1440），本轮补的只是**入口**：把 digest 的中文图注与 M1 intake 的图片文件对上。

⚠️ digest 里的 `figureId`（`fig1..fig4`，来自 LLM 摘要）与 intake 里的文件名（`fig-1-teaser.png`，来自 `\includegraphics`）不是一套编号，**必须显式给映射，不允许猜**：

```bash
cd apps/papercast-server
.venv/bin/python scripts/make_cards.py \
  --digest       "$WS/apps/papercast/public/samples/digest.json" \
  --figures-dir  "$WS/var/samples/papercast-lab/paper2video/intake/images" \
  --out-dir      "$WS/var/samples/papercast-lab/paper2video/article/cards" \
  --map fig1=fig-1-teaser.png --map fig2=fig-3-method.png \
  --map fig3=fig-2-eval.png  --map fig4=fig-4-vis.png
```

中文字体走 `config.find_cjk_font`（白名单 + `fc-list :lang=zh`），本机命中 `~/.local/share/fonts/waic/msyh.ttc`，不会出豆腐块。缺字体会直接返回错误而不是静默出方块。

---

## 4. 路线 C · 需要 AI 出图的主视觉（待千问 key）

**只用于创作型视觉**：海报 hero 图、小红书封面。论文里的图一律不重画。

```bash
# 1) 出图前先把完整 prompt 落盘（可复现、可换后端）—— baoyu 的硬规则
#    prompts/01-hero.md（海报主视觉 16:9）、prompts/02-xhs-cover.md（封面 3:4）已写好
# 2) 把 key 写进 var/secrets/imagegen.env（gitignored，chmod 600）
#    DASHSCOPE_API_KEY=sk-xxx
# 3) 出图
ops/imagegen.sh --prompt-file var/samples/papercast-lab/paper2video/poster/prompts/01-hero.md \
  --image var/samples/papercast-lab/paper2video/poster/hero.png --ar 16:9 --quality 2k
# 4) 用 hero 版 spec 重排海报（主视觉换成生图，其余版面不变）
.venv/bin/python -m app.modules.poster \
  --spec var/samples/papercast-lab/paper2video/poster/poster.spec.hero.json \
  --out-dir var/samples/papercast-lab/paper2video/poster \
  --figures-dir "var/samples/papercast-lab/paper2video/poster:var/samples/papercast-lab/paper2video/intake/images"
```

- `--figures-dir` 支持 `:` 分隔多目录：先找 `poster/`（生成的 hero.png），再找 `intake/images/`（论文原图）。
- 默认后端 `dashscope / qwen-image-2.0-pro`；换后端用 `IMAGEGEN_PROVIDER=google IMAGEGEN_MODEL=gemini-3-pro-image ops/imagegen.sh ...`。
- 千问接的是 `POST /api/v1/services/aigc/multimodal-generation/generation`（同步返回图 URL），支持 `--ref` 的只有 `wan2.7-image-pro` / `wan2.7-image`。

---

## 5. 环境事实（踩过的坑）

| 事实 | 影响 |
| --- | --- |
| `npx -y bun` 在本沙箱直接失败（`~/.npm` 只读） | 必须把 `npm_config_cache` / `npm_config_tmp` 指到 `var/cache/npm`、`var/npm-tmp`；`ops/imagegen.sh` 已内置 |
| `codex` CLI 在本沙箱不可用 | ① 它要写 `~/.codex`（只读）；② 它配置的上游 `http://123.60.91.241:9002` 返回 503。所以 `codex-cli` 文生图后端在本机暂时走不通，**出图只能走 API key 后端** |
| 完整 chrome 起不来（crashpad `--database is required`） | `ops/shot/render.mjs` 优先选 `chrome-headless-shell`；可用 `SHOT_CHROME` 覆盖 |
| 本机没有 poppler / ImageMagick / LaTeX | PDF 出图只能走 PyMuPDF；海报不能走 LaTeX/Beamer，只能走 HTML 渲染 |
| 中文字体只命中 `~/.local/share/fonts/waic/msyh.ttc` | 卡片与海报都用它；换机器要装 `fonts-noto-cjk` |

---

## 6. 待办

0. **已完成（2026-09-19 R1.5）**：A 会议海报、B 小红书卡片、五个数字渠道画布（conf/zhihu/bili/xhs/xhs-long/bili-cover）、cover 版式、可读性闸门、`ops/imagegen.sh` 出图入口。公众号封面不做。
1. **接进流水线**：`poster` 阶段目前仍是 `skipped`。要变成实现，需要在 `app/modules/` 加 `run_poster(ctx)`（照 `run_article` 的写法：读 `understand/digest.json` + `intake/images`，写 `poster/poster.png`，用 `ctx.check()` 报几何闸门），并在阶段表里把 poster 从 skipped 放开。
2. **spec 的生成**：现在 `poster.spec.json` 是手写的。要让 M2 自动产出，需要一段 LLM 步骤（digest → spec），并且 spec 里的每条事实都要能回溯到 digest（沿用 `verify_digest()` 的思路）。
3. **路线 C 实测**：拿到 `DASHSCOPE_API_KEY` 后跑 `ops/imagegen.sh`，出 hero 图 → `poster.spec.hero.json` 重排。
4. **视觉自检**：几何闸门只能保证"不溢出、不空"，不能保证"好看"。Paper2Poster 用 VLM 读图打分；本机没有 VLM key，可用千问多模态或 codex（当前不可用）补这一步。
