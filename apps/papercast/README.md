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
| 文章生成 | 平台体裁（小红书 / 知乎 / B站 / 公众号）× 讲述者人格（作者自述 / 同行拆解 / 科技快讯 / 技术解读 / 审稿人）多套文字稿 + 卡片 | `kangw24/paper2content`、`paper2anything/paper2wechat`、`flyanx/paper-to-wechat`；人格规范见 `papercast-server/docs/09-voice-styles.md` |
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
  stores/         runs（运行状态、轮询）、platforms（渠道登录态）、ui（视图与预览 Tab）
  components/     输入面板、流水线时间轴、阶段卡片、产物面板
    viewers/      理解层 / 文章 / Poster / 视频 / 发布 五个预览器
  views/          运行历史、产物库、平台账号、引擎与环境
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
GET  /api/platforms                 -> PlatformChannel[] 渠道账号与登录态
GET  /api/platforms/:id/login/qrcode-> PlatformQrcode    扫码登录二维码
POST /api/platforms/:id/login/logout-> 204               退出登录（清 cookies）
```

后端只需把每个阶段的 `status / progress / logs[] / artifacts[] / gate` 填进 `PaperRun` 即可，
产物的 `url` 指向可预览的静态地址（Markdown / HTML / 图片 / MP4）。

## 平台登录入口

发布渠道的账号 / 登录态收敛在「平台账号」页，三个入口共用同一套登录流程（`components/PlatformLoginDialog.vue`）：

1. 左侧导航「平台账号」；
2. 顶栏的小红书状态条（已登录显示账号，未登录点一下直接进登录页；**首屏探测期间显示「平台账号 · 探测中…」**，不是空白）；
3. 发布页的「扫码登录」按钮 —— 勾选的渠道没就绪时，「确认发布」会禁用并说明原因（只能走「仅存草稿」）。

四个渠道各自的登录形态（都由后端 `login` 字段驱动，前端按它选流程）：

| 渠道 | 形态 | 页内操作 | 底层 |
| --- | --- | --- | --- |
| 小红书 | `qrcode` | 页内二维码 + 4 分钟倒计时 + 5s 轮询 | `xiaohongshu-mcp`（取码即建等待会话，扫上自动落 cookies） |
| 知乎 | `browser` | 点「打开浏览器登录」→ 桌面弹出浏览器窗口（含人机验证）→ 页面轮询到 `ready` | `zhihu-publisher`（风控拦纯 HTTP 扫码，必须真人过窗口） |
| B 站 | `qrcode` | 页内二维码（**biliup 出的真码**）+ 倒计时 + 轮询 | `bilibili-publisher`，后端顺手起一次 `biliup login` 并把 `qrcode.png` 取回来 |
| 微信公众号 | `env` | 无（`unconfigured`） | 需要 AppID / AppSecret，本期只出草稿 |

设计约定：

- 前端不直连 `:18060` / `:18070` / `:18080`，只调后端 `/api/platforms/*`；凭证只落本机；
- 小红书二维码**只在用户点击时取一次**（MCP 每次取码会新建一个 4 分钟等待会话，重复取会顶掉上一个），之后前端 5s 轮询登录态；B 站相反 —— 重复取码是安全的（biliup 覆盖旧码）；
- 没接通的渠道（公众号缺凭证 / 通道服务没起 / 服务离线）如实显示成「未配置 / 服务离线」，并把接通命令放在卡片上可一键复制，不显示成可用；
- 通道服务离线或未配置时，「扫码登录」按钮直接禁用（避免点出一个必然失败的请求）；
- mock 适配器下弹层会明确标注「演示二维码，不会真的登录」。

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
