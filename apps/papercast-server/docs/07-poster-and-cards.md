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
| 小红书首图（封面版式） | `xhs-cover` | 1080×1440（3:4） | cover 版式 | 标题 ≥4% 画布宽 | **信息流首图**：大标题 + 一句钩子 + 论文主图 + 标签条 |
| 小红书单栏卡（正文版式） | `xhs` | 1080×1440（3:4） | 1 | 26–30px | 单栏正文卡（与 `cards/render.py` 的组图并存） |
| 小红书/知乎 竖长图（信息图） | `xhs-long` | 1080×2400（3:4 长） | 1 | 23–26px | 一图讲完整篇论文 |
| 小红书正文卡片 | （`app/cards/render.py`） | 1080×1440 ×N | — | PIL 固定版式 | 组图第 2..N 张 |
| 小红书 **3:4 组图**（技能版式） | `guizang-deck` | 1080×1440 ×N（`--scale 2` → 2160×2880） | 技能版式（M01 封面 / M08 台账 / 图卡 / M07 结尾） | 由技能的 QA 门守着 | **信息流图文**：同一份 spec 用 guizang 技能重排，见 §3.5 |
| B 站视频封面 | `bili-cover` | 1920×1080（16:9） | cover 版式 | 标题 ≥4% 画布宽 | 视频封面：左大标题 + 右主视觉（横竖两种封面排法见 §2.4） |

> 公众号封面（900×383）按 2026-09-19 的决定**不做**；`wechat` 预设已从代码里移除。

**为什么必须按渠道重排而不是缩放**：CSS 尺寸用 `cqw`（相对画布宽度），同一份 CSS 放到 1080 宽的画布上，正文字号就只有 2304 宽时的 47% —— 会掉到 10px 左右，手机上完全看不清。
所以 `poster.py` 按 `body_px`（目标正文像素）反推基础倍率，并设 `LEGIBILITY_FLOOR=0.75`：字号最多缩到目标值的 75%，再小就**判失败**，提示去减内容或换更大的画布。

实测（2026-09-19 换纸面编辑风之后，DeepRare 真 run `run_36997981259d` 的 spec/原图，`var/scratch/poster-review/stage/`）：

| 预设 | 结果 |
| --- | --- |
| `xhs-cover` 1080×1440 | ✅ 标题 79px（占宽 7.3%）· 无溢出 |
| `xhs-long` 1080×2400 | ✅ body 21.5px / `panel_fill` 0.930 |
| `zhihu` 1600×1200 | ✅（第 3 次尝试：**砍掉 2 个次要块**后通过）body 16.5px / fill 0.730 |
| `bili-cover` 1920×1080 | ✅ 标题 98px（占宽 5.1%） |
| `conf` 2304×1728 | ✅ body 21.4px / fill 0.835 |

**`zhihu` 那条就是「必须按渠道砍内容」的活证据**：8 个块塞 4:3 时正文会被压到下限以下还溢出，`poster_stage._render_with_budget` 按优先级砍到第 2 块才过，日志里如实写「装不下，砍掉 2 个次要块后通过」。
（换风格前这条是 ❌ 且不砍块也"通过"—— 那是**闸门瞎了**，见 §2.3。）

同一份内容预算下，**竖长图（1080×2400）是唯一能装下"论文全貌信息图"的数字画布**；首图和横版都必须砍到 3 个块左右。窄画布用 `items_tall` 提供更短的条目、用 `sizes: ["wide"]` 把次要块排除。

### cover 版式（小红书首图 / 视频封面）

封面不是"缩小版海报"，是另一种版式：spec 里写 `"layout": "cover"`（不需要 `columns`），
渲染成**纸面上的大标题 + 一句钩子 + 论文主图 + 标签条**（横画布左右分栏、竖画布上下堆叠，见 §2.2）。
这类内容很少，所以预设用 `scale_start` 从一个大倍率往下二分，求"能放多大放多大"；因为封面的
判据是标题字号（`h1_pct ≥ 4%`），起点不能太高 —— 旧版从 2.6 起会把中文标题挤成**一个字一行**。
主视觉位（`.art`）就是路线 C 的 AI 生图落点：把 `fig-1.png` 换成千问出的 hero 即可。

### 落到 run 目录的哪里

```
var/runs/<runId>/
├── article/cards/p1..pN.png        ← 小红书组图（3:4，1080×1440）
├── poster/poster-xhs-cover.png     ← 小红书首图（3:4 封面版式，信息流第一张）
├── poster/poster-xhs-long.png      ← 小红书/知乎竖长图
├── poster/poster-zhihu.png         ← 知乎正文横版
├── poster/poster-bili-cover.png    ← B 站视频封面
├── poster/poster.png               ← 会议海报（打印/存档；掉档顺序里排最后）
├── poster/poster.spec*.json        ← 版面描述（可复现、可换后端重排）
└── publish/export/                 ← 投放兜底：title/content/首图
```

---

## 2. 路线 A · 确定性排版（`app/modules/poster.py` 机制 + `poster_theme.py` 长相）

### 设计

```
digest.json / 论文原文
      ↓ （M2 写成 poster.spec.json：标题、作者、栏目、引用哪些图）
poster.py:  spec → build_html()（cqw 版式，与像素无关）+ 二分 --s + 几何闸门 + 渠道预设
      ↓ ops/shot/render.mjs（chrome-headless-shell，横切 B 渲染底座）
poster-*.png + poster.render.json（自检：溢出 / 缺图 / 填充率 / 字号）
```

**两个文件的分工**：`poster.py` 是引擎（二分字号、闸门、预设、出图，`make_poster` 是唯一入口）；
`poster_theme.py` 是**视觉系统**（CSS + 两套版式）。换风格只动 `poster_theme.py`，引擎契约不变。

- **内容与版式分离**：`poster.spec.json` 只描述"放什么"，版式决定"怎么排"。换一篇论文只需要换 spec。
- **字号自适应**：全篇字号/间距都乘一个统一变量 `--s`，二分求"不溢出的最大字号"。这是 Paper2Poster 的 Painter-Commentor 循环的机械化版本 —— 不需要视觉模型，结果可复现。

### 2.1 视觉系统：纸面编辑风（2026-09-19 换掉旧版暗底墙报）

面向**信息流**而不是论文墙报，三条判据（写在 `poster_theme.py` 的模块 docstring 里）：

| 判据 | 做法 | 反面（旧版） |
| --- | --- | --- |
| 像一篇文章，不像一块展板 | 暖白纸面 `#f7f6f3` + 近黑 `#1a1918` + 1px 发丝线；层次靠字号对比与留白 | 深蓝黑渐变抬头 + 蓝色卡片 + 投影 |
| 一个强调色 | 朱红 `#c8362a` 只出现在栏目标题序号（01/02）与 kicker 短杠 | 蓝/红/绿三色混用 |
| 外框固定、字随内容二分 | 外边距用**不乘 `--s`** 的 cqw（每条渠道都留够安全边），内部字号乘 `--s` | 无 |

配色不是新造的：`--paper` 就是前端 `src/style.css` 的 `--bg`，所以海报和产品界面是同一套语言。

**不复制 AGPL 代码**：版式规则（安全边、封面结构、栏目序号化）参考了
`reference/upstream/guizang-social-card-skill`（AGPL-3.0，只读）。CSS 与模板是照上述判据自己写的 ——
本仓库是 MIT 且公开发布，抄进去会传染。仓库选型见 `docs/research/poster-visual-system-repos.md`。

### 2.2 两套版式 + 三条版式规则

- **网格版式**（默认）：文章式抬头 → 栏目（序号 + 发丝线分隔的要点）→ 页脚素材行。
- **cover 版式**（`"layout": "cover"`）：大标题 + 一句钩子 + 论文主图 + 标签条。
  **横画布（≥1.2）左右分栏，竖画布上下堆叠** —— 16:9 的视频封面和 3:4 的小红书首图是两种排法。
- **密度旋钮 `--rhythm`**：横画布 0.72、竖画布 1.0。宽画布要"一屏讲完"、内容多，收紧间距；
  竖长图还能往下滚，保持舒展。**收的是间距，不是字号** —— 字号下限由 `LEGIBILITY_FLOOR` 守着。
- **主图规则**：横画布上通栏主图会当成**第一栏的导语图**（通栏横带在宽画布上会在图注右侧留一大片空档）；
  竖画布上保留通栏，但排成"图左 + 图注右"的一行。

### 2.3 几何闸门（三档判据，都是 fail-closed）

| 闸门 | 判据 | 说明 |
| --- | --- | --- |
| 溢出 | 每个 `[data-panel]` 的 `scrollHeight - clientHeight > 2` 即失败 | 靠 `.col > *{min-height:0}` 让"装不下"表现为**面板被压扁并报溢出**，而不是被 `overflow:hidden` 静默裁掉 |
| 可读性（网格） | `body_px ≥ 目标 × 0.75` | 目标按渠道给（见上表）；到下限还溢出就**减内容**，不许继续缩字 |
| 可读性（封面） | `h1_pct ≥ 4.0%` 画布宽 | 封面没有正文，比标题：1080 宽的小红书首图 → 标题 ≥43px |
| 填充率 | `panel_fill`（正文面板面积 / 栏位面积） | 反映"栏内是否留大片空白"；换风格时用它否掉了"卡片之间裂开一道缝"的排法（0.64） |

### 2.4 产物登记（界面上看得见才算数）

`poster_stage` 每渲染一张画布就登记一个 image 产物，`meta` 里带
`{width, height, preset, platform}`（`platform` 给前端作品库用 —— 它一直在按文件名猜平台）；
另外把**第一张画布（小红书首图）的 HTML** 登记为 `kind="html"` 的「首图预览」：
查看器 `PosterViewer.vue` 是按 `kind === 'html'` 找预览的，以前只登记 PNG，所以那个页签一直显示「尚未产出」。

> ⚠️ **2026-09-19 修的一个真 bug**：旧版 `.col` 的子项没设 `min-height:0`，
> 内容装不下时会把整栏顶出画布再被 `.sheet{overflow:hidden}` 裁掉，而 `[data-panel]` 一个都不报溢出 ——
> 于是 `zhihu` 这类"其实塞不下"的画布会**带着裁掉的半张图**判 pass。现在这类画布会如实报溢出。


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

### 二分收敛的样子（实例）

`conf` 2304×1728、DeepRare 真 spec：从 `--s=1.0` 起，落到 `0.9565`（body 21.4px）通过；
`zhihu` 1600×1200 同一份 spec：一路降到下限 `1.0631`（= 目标 22px 的 75%）还溢出，
于是走 §1.5 那条"砍 2 个次要块"，砍完在 `1.0631` 通过 —— 每次尝试都记在
`poster-<preset>.render.json` 的 `report.tries` 里，可复现、可解释。

离线重放这套逻辑（不联网、不调 LLM，用真 run 的 spec/原图）：
`apps/papercast-server/.venv/bin/python var/scratch/poster_stage_offline.py var/runs/<runId>/poster`

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

## 3.5 路线 B+ · 小红书 3:4 组图（guizang 技能链路，2026-09-19 接入）

**是什么**：`poster` 阶段在出完确定性画布之后，把**同一份** `poster.spec.json` 交给
`app/modules/cards_deck.py`，用 `op7418/guizang-social-card-skill` 的 Editorial 版式**重排成一组
1080×1440 的小红书图文**（封面 / 要点台账 / 证据图卡 / 判断页，4–9 张），产物落 `poster/cards/`。

**为什么是「重排」而不是「再叫一次 LLM」**：spec 已经是 LLM 产出、并逐条核过数字可回溯的内容
（`poster_stage._sanitize`）。组图要的是同一批事实的另一种版式。少一次 LLM 调用 = 少一处幻觉源、
少一次等待，而且离线可复现（`var/scratch/poster_stage_offline.py` 跑的就是这段代码）。

| 事项 | 做法 |
| --- | --- |
| 开关 | `PAPERCAST_POSTER_DECK` = `auto`（默认，**装了技能才跑**）/ `on` / `off`；设置页「解析与渲染」可改；`/api/env` 里有 `deck.{mode,skillInstalled,skillPath,active}` |
| 技能从哪来 | 只从用户级安装目录**运行时读取**（`~/.agents/skills/guizang-social-card-skill`，可用 `GUIZANG_SKILL_DIR` / `SKILLS_ROOT` 覆盖）。**模板/CSS 不进本仓库**（它是 AGPL-3.0，本仓库 MIT 且公开发布）；本文件只带一层自写覆盖（字体栈、图卡底色、一处上游间距） |
| 出图 | `ops/shot/render_social_deck.mjs`（我们自己的，逐个 `.poster` 节点截图，`--scale 2`） |
| 自检 | 技能自带的 `validate-social-deck.mjs`（R1 溢出 / R2 页脚相撞 / R4 最小字号 / R5 四横带密度 / R6 标题行数上限 / R9 标题间距…），结果直接写成阶段闸门「小红书组图（guizang 技能）」 |
| 装不下怎么办 | `_run_deck` 最多重排 3 次（每页要点 4→3 条、再砍到前 3 页），每次如实写日志；仍不过才记 fail |
| fail-closed | 技能没装 / 开关 off → 记一条 `run`「跳过」，**不判失败**，渠道画布照常交付；装配或渲染异常 → 记 fail，但不动已渲染好的画布 |
| 技能没装时 | 阶段里显示「技能未安装（跑 ./ops/install_skills.sh 装 guizang-social-card-skill）」 |

单独跑（不联网、不调 LLM，用真 run 的 spec/原图）：

```bash
apps/papercast-server/.venv/bin/python var/scratch/poster_stage_offline.py var/runs/<runId>/poster
DECK=off …   # 验证关掉时的行为
```

### 接入时被真跑抓出来的四个坑（都锁进了 `tests/test_cards_deck.py`）

| 坑 | 症状 | 解法 |
| --- | --- | --- |
| **截字** | 封面标题 13 个字塞不进两行，第一版直接输出「罕见病诊断智…」 | `fit_title`：**先按标点砍从句，砍不动再整档降字号**，永不截半个词（技能 R4 的建议原文就是 "cut copy instead of shrinking type"） |
| **稀疏页** | 只有 3 条要点时，模板的 `.ledger` 把内容挤在上半页、下半页一大片空 —— **技能的 R5 密度门抓不到**（它量的是"元素占位"不是"墨迹"） | 覆盖层 `.ledger{flex:1}` + 行高下限 118px（M08 配方的下限）、上限 260px |
| **kicker 重复** | `Nature · VOL 651 · 2026` + `Nature` 拼一起，封面顶行读成两个 Nature | `dedupe_parts()`：互为子串的只留长的那个 |
| **图卡页下方留白** | 模板的图卡按 16:10 定高，图卡页会空出四分之一页 | 图卡页的画框改成 `flex:1`（去掉 aspect-ratio），图本身仍 `contain` —— 不裁剪、不拉伸，只是画框变大 |
| **字体依赖** | 换 `HOME` 跑时封面判失败 —— 因为雅黑在 `~/.local/share/fonts`，`HOME` 一变字体就没了，标题量出来的宽度掉到 `h1_pct` 下限以下 | 这其实是**正确**的 fail-closed（没字体的话字是看不见的），但要知道封面闸门依赖本机字体：换机器先装 `fonts-noto-cjk` |

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
| 本机**没有中文衬线体**（`fc-match "Noto Serif CJK SC"` → DejaVu Sans） | 纸面编辑风的标题走「重字重 + 紧字距」的黑体，不写 `serif`/`Songti` —— 写了会回退到 DejaVu 造成中英混排跳变。要真衬线得先装字体，再改 `poster_theme.FONT_STACK` |
| CSS `text-wrap:balance` 在中文里会**拆词**（"可追溯推/理"） | 只用在**封面短标题**（避免尾行只剩两三个字）；长中英混排标题用自然断行。真正的修复要词典级断行，不在本轮 |

---

## 6. 待办

0. **已完成（2026-09-19 R1.5）**：五个数字渠道画布（conf/zhihu/bili/xhs/xhs-long/bili-cover）、cover 版式、
   可读性闸门、`ops/imagegen.sh` 出图入口。公众号封面不做。
1. **已完成（2026-09-19 换风格）**：`poster` 阶段接进流水线（`poster_stage.run_poster`，digest → spec → 按渠道渲染）；
   视觉系统换成纸面编辑风（`poster_theme.py`）；交付集补上 `xhs-cover`（小红书首图）；
   三档闸门补全（溢出 / 正文可读性 / 封面标题），并修掉"溢出被 `overflow:hidden` 静默裁掉"的 bug。
   实证：`var/scratch/poster-review/stage/`（5/5 通过）、`docs/evidence/poster-{xhs-cover,zhihu,bili-cover}.png`、
   测试 `tests/test_poster_theme.py`。
2. **spec 的生成**：LLM 写 spec 的部分已在 `poster_stage._write_spec`（含数字回溯）。
   还剩：封面标题仍是主标题切前 40 字 —— 应该单独让 LLM 写一句 ≤14 字的短标题（现在会遇到中文标题被拦腰断行）。
3. **路线 C 实测**：拿到 `DASHSCOPE_API_KEY` 后跑 `ops/imagegen.sh`，出 hero 图 → `poster.spec.hero.json` 重排。
4. **视觉自检**：几何闸门只能保证"不溢出、不空"，不能保证"好看"。Paper2Poster 用 VLM 读图打分；
   本机没有 VLM key，可用千问多模态或 codex（当前不可用）补这一步。
5. **组图还没接进投递**：`publish._pick_media` 现在仍按 `poster/*.png` 挑封面（不含 `poster/cards/`），
   所以真实投递用的还是渠道画布，不是这组 3:4 组图。要接的话得让发布侧按渠道认 `cards/xhs-*.png`。
6. **封面短标题仍靠 LLM 的 cover.title**：`poster_stage` 现在是让 LLM 在 cover spec 里写短标题；
   如果它写长了，`fit_title` 会砍从句 —— 更稳的做法是给封面标题单独一条 ≤14 字的生成约束。
7. **投放侧封面还没分渠道**（不在本模块，别漏）：`publish._pick_media` 给所有渠道挑同一张封面
   （按文件名排序会挑到 `poster-bili-cover.png`），所以**投到小红书的封面目前不是那张 3:4 首图**；
   前端 `src/data/works.ts` 的小红书封面回退也没优先认 `poster-xhs-cover.png`。
   两处都在别的轨道正在改的文件里，本轮**没动**，交接给他们。
