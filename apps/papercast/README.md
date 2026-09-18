# PaperCast · 论文多形态传播控制台

输入 PDF / arXiv 链接 / LaTeX 源码，跑完一条六段流水线，产出**文章**、**Poster**、**视频**，并在人工确认后投递到小红书 / 公众号 / B 站。

前端为 Vue 3 + Vite + TypeScript + Pinia；默认内置**模拟适配器**（mock adapter），无需后端即可完整演示；
接上真实后端时只需设置环境变量，组件与状态管理无需改动。

```bash
npm install
npm run dev      # http://127.0.0.1:5178
npm run build    # vue-tsc 类型检查 + 产物构建
```

## 六段流水线

| 阶段 | 做什么 | 本项目复用的开源实现 |
| --- | --- | --- |
| 输入归一化 | PDF / arXiv / LaTeX → 统一 paper 模型（content.md + 图表） | `paper-share-skills/pdf-to-markdown`（MinerU）、`paper2anything/scripts/parse_pdf.py` |
| 论文理解层 | 抽取贡献 / 方法 / 证据 / 图表，落一份 `digest.json` 作为**唯一事实源** | `pickxiguapi/paper2x → paper2note` |
| 文章生成 | 微信 / 小红书 × 学术 / 媒体 四套风格文字稿 + 封面 | `kangw24/paper2content`、`paper2anything/paper2wechat`、`flyanx/paper-to-wechat` |
| Poster | Parser → Planner → Painter → 盲读校验，输出 `poster.html` / `poster.png` | `paper2anything/paper2poster`、`Paper2Poster/Paper2Poster` |
| 视频 | Beamer 幻灯片 → 旁白 → TTS → 合成 + 封面（横竖双版本） | `yhbcode000/paper-share-skills`、`showlab/Paper2Video` |
| 发布 | 小红书 MCP / 公众号草稿箱 / biliup，全部带人工闸门 | `xpzouying/xiaohongshu-mcp`、`aiworkskills/wechat-article-skills`、`biliup` |

设计上刻意保留了真实 skill 链的两个特征：

1. **单一理解层**：文章 / Poster / 视频都从同一份 `digest.json` 派生，避免三个产物互相矛盾；
2. **人工闸门**：理解层确认、海报规格、发布前三处会停下来等人放行，而不是一把梭全自动。

## 目录结构

```
src/
  api/            PipelineApi 接口 + mock（默认）与 http（接后端）两个实现
  stores/         runs（运行状态、轮询）、ui（视图与预览 Tab）
  components/     输入面板、流水线时间轴、阶段卡片、产物面板
    viewers/      理解层 / 文章 / Poster / 视频 / 发布 五个预览器
  views/          运行历史、产物库、引擎与环境
  data/env.ts     环境依赖状态 + 阶段↔引擎映射
public/samples/   演示用示例产物（见下方「示例数据」）
```

## 对接真实后端

前端只依赖 `src/api/types.ts` 里的 `PipelineApi` 接口。启动后端后：

```bash
VITE_API_BASE=http://127.0.0.1:8000 npm run dev
```

即自动切换到 `src/api/http.ts` 的 `HttpPipelineApi`。约定的 HTTP 契约：

```
POST /api/runs                      -> PaperRun          提交论文
GET  /api/runs                      -> PaperRun[]        运行列表
GET  /api/runs/:id                  -> PaperRun          轮询进度 / 日志 / 产物
GET  /api/runs/:id/events           -> SSE（可选，未接时退化为轮询）
POST /api/runs/:id/stages/:sid/gate -> { optionId }      人工闸门放行
POST /api/runs/:id/cancel           -> 204               中止
```

后端只需把每个阶段的 `status / progress / logs[] / artifacts[] / gate` 填进 `PaperRun` 即可，
产物的 `url` 指向可预览的静态地址（Markdown / HTML / 图片 / MP4）。

## 示例数据

默认示例运行的主题论文是 **arXiv:2510.05096（Paper2Video / PaperTalker，Show Lab, NUS）**：

- `public/samples/digest.json`、`public/samples/article/*.md`、`public/samples/video/narration.json`
  —— 由本地仓库 README、arXiv 摘要页、项目主页三处**一致**信息生成，论文未公开的数值一律未引入，
  指标条目均为定性结论并注明「作者未在 README 中给出具体数值」。
- `public/samples/video/paper2video.mp4` —— 来自 showlab/Paper2Video 的公开产物，仅用于演示播放器与时间轴联动。
- `public/samples/poster/poster.html`、`public/samples/covers/*.svg` —— 为本项目手写的产物样例。

## 已知边界

- `public/samples/poster/poster.png` 是本次用 `chrome-headless-shell` 真实渲染出来的（1080×1440），
  渲染脚本见 `../../ops/shot/shot.mjs`；换成后端渲染时把 `poster.html → PNG` 接到流水线里即可。
- 视频用现成 MP4 代替现场合成：本机虽没有系统 ffmpeg，但 playwright 缓存里有自带的
  `~/.cache/ms-playwright/ffmpeg-1011/ffmpeg-linux`，后端合成时可以直接指过去。
- `screenshots/` 下是用 `chrome-headless-shell` 跑出来的 10 张界面截图（工作台各预览 + 运行中 + 三个视图）。
- 文章里的公式当前以 TeX 源码样式呈现，接入后端后可换成 KaTeX 渲染。

## 调研出处

仓库结构、阶段拆分与复用决策来自 `../paper-dissemination-agents-landscape.md` 的 GitHub 调研，
相关仓库已浅克隆到 `../../reference/upstream/`（paper2anything、paper2x、paper-to-wechat、paper2content、
Paper2Poster、Paper2Slides、Paper2Video、paper-share-skills、guizang-social-card-skill、
wechat-article-skills、PPTAgent、Paper2Any、xiaohongshu-mcp）。
