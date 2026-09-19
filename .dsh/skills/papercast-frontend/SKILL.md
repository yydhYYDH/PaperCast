---
name: papercast-frontend
description: PaperCast 前端的界面规范与验证配方（暖调单色编辑风格、对话优先入口、只给结论、不许看板化）。改 apps/papercast 任何界面、文案或查看器之前读它；含真实踩过的坑与 ops/shot 核验脚本清单。
---

# PaperCast 前端：编辑风格 + 对话优先 + 只留结论

## 0. 什么时候用

只要动 `apps/papercast/` 里的**界面、文案、样式、查看器、交互**，先读这一篇再动手。
后端/流水线/发布逻辑不在本技能范围（看 `apps/papercast-server/docs/` 与 `docs/`）。

三条不可协商的底线：

1. **受众是评审专家、学生、顺路点进来的人** —— 不装专家、不摆控制台、不用行话；
2. **一个入口**：工作台就是一个大对话框，右侧一条「谁在干活」名单，其余功能安静地待在左边导航里；
3. **能不选就不选**：默认即最优，选项藏到「设置」；页面上只留结论，细节默认折叠。

## 1. 视觉基调（暖调单色，纸面感）

- 画布 `#f7f6f3`、白卡、**1px 极浅描边**（`#eaeaea`）；**几乎不用阴影**（仅弹层允许一点）；
- 标题走**衬线**（`--serif`），正文 15px / 1.7，颜色只用近黑与三档灰；
- **颜色只用来表达状态**（绿=通过 / 琥珀=等你 / 红=失败 / 蓝=进行中），且必须是柔和的粉彩底 + 深字，不要饱和色块；
- 禁止：渐变、emoji、图标字体、进度条墙、统计卡墙、等宽大数字、彩色徽章堆叠、"深色控制台面板"；
- 所有设计变量集中在**唯一**的全局样式 `src/style.css`（`:root` 里），组件里写 scoped 样式但**不新增色值**——要新颜色先加 token。

细节与配方见 [references/design-system.md](references/design-system.md)。

## 2. 文案声音

- 中文、短句、动词开头；一句人话能说清就别用名词堆；
- **不许把后端术语端给用户**：不出现 `stage`/`artifact`/`run_id`/`mock`/`API`/`MCP` 这类词（导航和页面标题用「取论文 / 读懂 / 写作 / 视觉 / 视频 / 运营」）；
- **读不到就说读不到**，并给出下一步（例：「小红书 MCP 报告未登录：先去『平台账号』扫码，再回来刷数据」）；**永远不要用 0、空白或编造的示例数据顶替**；
- 失败也要有回执（toast 或对话里的一条消息），不要「点了没反应」。

## 3. 代码地图（改前先看这三处）

| 你要改什么 | 去哪里 |
| --- | --- |
| 颜色 / 字号 / 圆角 / 通用组件类 | `src/style.css`（唯一全局样式，`:root` token + `.page-head`、`.sheet`、`.toast`、`.logbox`…） |
| 任何 HTTP 调用 | `src/api/http.ts`（**唯一出口**）＋ `src/api/types.ts`（形状）＋ `src/api/mock.ts`（离线同形状实现） |
| 后端产物地址 | `assetUrl()`（`src/api/index.ts`）—— 后端给的是 `/artifacts/...` 相对路径，直接 fetch/src 会 404 |
| 工作台（对话入口） | `src/views/WorkbenchView.vue` + `src/components/chat/{ChatThread,ChatMessage,Composer,AgentRail}.vue` + `src/stores/chat.ts` |
| 对话里能派活（动作卡） | 卡片长在 `ChatMessage.vue`（`.act`），执行在 `stores/chat.ts` 的 `runAction()`；后端给卡在 `app/chat_api.py` 的「意图 → 动作提案」，形状是 `api/types.ts` 的 `ChatAction` |
| 状态 | `src/stores/*`（Pinia）。**对话消息由 runs store 里的运行推导**，不要另造一份状态 |
| 产物查看器 | `src/components/viewers/*.vue`，props 是 `{ run }`，优先读**这次运行**的真产物 |

跨组件约定：确认框走 `ui.askConfirm()`（不要 `window.confirm`），提示走 `ui.toast()`；
端口/地址不许写死，来自 `VITE_API_BASE` 与后端返回。

## 4. 硬规则（写代码时逐条对）

**必须**

- 人工闸门（发布、退出登录、停服务）→ `ui.askConfirm()`，默认动作排第一，按钮文案是动词；
- **对话里派活也得过闸门**：动作卡只有 `risk=readonly`（只读）允许自动执行，其余一律等用户点那个动词按钮；
  服务端只产出「做什么 + 参数」、**不产生副作用**；`risk=public`（真发到平台上）按危险动作渲染并写明撤不回来；
  失败要有回执（卡片标红 + 气泡说原因），不许「点了没反应」；
- **只读动作也要留痕**：自动执行的只读动作（看数据、读评论）进行中要写清**在做什么**（读一次平台要
  几十秒），失败必须在对话里留一行原因 —— 只有一条会自己消失的 toast 等于没回执；
  而且**别让长动作冻住输入框**（`ask()` 里不要 `await` 只读动作），并发读取要在 store 里合并；
- **互动：读、起草都不许有发送入口**：读评论只给只读卡，起草只落 `var/interactions/drafts.jsonl`，
  页面上不许冒出「回复/发送」按钮；真要发的唯一入口是起草之后那张**危险卡**（§14：
  按钮文案「发出去」、点了还要过 `ui.askConfirm`、失败必须标红说原因、成功后落 `sent.jsonl`）；
  发送接口有四道闸门（`confirmed` / `PAPERCAST_INTERACTIONS_SEND` 开关默认关 / 目标 / 20 条每小时），
  前端**不要**替用户把 `confirmed` 写成 true —— 那是「点过确认」的意思，只能由那一次点击带来；
- 真实数据优先：先读运行产物，示例只在读不到时兜底，并且**兜底要看得出来**；
- 空状态、加载中、失败三种态都要有文案（不是转圈了事）；
- 移动/窄屏：右栏 ≤1180px 收起，对话列自适应。

**禁止**

- 新增 UI 组件库、图标库、CSS 框架（就手写 + token）；
- `window.confirm/alert/prompt`、以及任何"浏览器原生冒泡对话框"；
- 统计卡（`.stat-card`/`.stat-grid`）与服务卡片墙（`.svc-grid`/`.svc`）—— **2026-09-19 已整套删除**，
  并在 `style.css` 原处留了注释；要展示数字就用「一句结论 + 最多三个数字」；
- 在仓库里写死 `/home/...` 绝对路径或端口；
- 把 `var/`、`cookies.json`、`.env` 之类提交进 git。

## 4.7 回执必须摆出来（2026-09-19，用户：「跑完了但是没有回执」）

一条内容可能被投过**不止一次**：这一轮的发布（M3，回执在 `publish/<渠道>/receipt.json`）失败后，
用户可以从作品库**直投**（回执在 `publish/direct/<渠道>/receipt.json`，后端还会把它并进总表
`publish/receipts.json` 的 `channels.<渠道>`，并写上 `updatedBy: work-library`）。
后果：只看总表的话，「已发布」会把那次失败**盖掉**，用户根本看不出这件东西是怎么发出去的。

规矩：

- 作品卡的状态取**最新**那条回执，但状态说明要写清**是谁投的**（`本轮发布` / `作品库直投`）；
- 详情里必须有「回执」块，**这个渠道投过的每一条都列出来**（新的在上）：状态、出处、时间、
  投的是哪份标题、字数/图数/账号、原文链接（有就点开）、失败原因（原文照抄）、以及原回执文件；
- 回执里**没有链接就直说**「这份回执里没有链接（这个渠道没回地址）」，不要留白让人以为没发出去；
- 失败/渠道不可用的那条，要给出路：「素材包还在本地，可以照『手动发布指引』自己发」；
- 数据来源只有回执与发布阶段的检查项（`data/works.ts` + `LibraryView.vue` 的 `loadExtras`），**不许编**。

## 4.4 手机端（≤720px，2026-09-19）

**底线**：桌面上是什么样就继续是什么样；手机**不是**「缩小的桌面」，而是同一套信息的另一种排法。
所有手机规则都关在 `@media (max-width: 720px)` 里（总则在 `src/style.css`，其余在各组件自己的样式块）。

- 左栏 → **底部标签栏**（`NavRail.vue`：`flex-direction: row` + `order: 2`）；顶栏挤成一行
  （窄屏换短文案：`演示` / `小红书` / `0 项`）；页头只留标题 + 一个动作按钮（`.meta-line` 藏掉）；
- **表格一律变卡片**（`RunsView.vue` 是样板：表头隐藏、`tr` 变 grid、每格的名字用 `::before` 补）；
- 行内元素要能换行，**别让固定宽度顶出去**（作品库封面墙的列宽是行内样式，手机上必须
  `!important` 压回单列）；
- 手指点得着：按钮 ≥ 34px（`.btn` 40px），输入框字号 **16px**（小于 16px 时 iOS 会自动放大整页）；
- 占位文案、提示语在窄屏要短一截（`Composer.vue` 用 `matchMedia` 切）；主行动按钮占满一行；
- 手机访问：vite 要绑 `0.0.0.0`（注意 `ops/start_all.sh` 里那行 `--host` 会盖掉 `vite.config.ts`），
  接口地址不许写死 127.0.0.1（非本机页面自动改用同源相对地址，vite 代理 `/api`、`/artifacts`）。

## 4.5 产品上特有的两条流程（改这里之前先读懂）

**Agent 审核**（`src/review.ts`，2026-09-19）

- 位置：**六个产出环节之后、人工闸门之前**。右侧名单第七行是「审核」（提醒：这不是后端 stage，
  `id: 'review'` 只是滚动锚点）；对话里有一条 `#m-review`；
- 数据来源：后端每个阶段真实落盘的 `stage.checks`（label/state/detail）+ 两条前端交叉检查
  （事实源 digest 在不在、走完的环节有没有产物）。**能用真数据核的就别问模型**；
- 硬规矩：还在跑时**不许说「已经通过」**（只说「已出来的这部分核过了，收齐了我再核一次」）；
  `state === 'fail'` 的项必须在闸门上方说出来；
- 人工闸门上方那一句 `Agent 审核已经通过 · 核了 N 项…` 与审核消息里的结论句是**同一个
  `review.line`**（review.ts 算一次，两处渲染）—— 别在两处各写一份文案，那样一定会漂移。

**个性化层（风格技能）**（`src/stores/style.ts` + `src/views/StyleView.vue`）

- 风格 = 本机的技能（`GET /api/skills`，后端只读 SKILL.md 的 frontmatter）。仓库自己的规范放在
  `<repo>/.dsh/skills/`，第三方设计技能在 `~/.agents/skills`（`ops/install_skills.sh` 装的）；
- 生效方式：**并进这一轮运行的 `brief`**（后端 `app/prompts.py` 的 BRIEF_RULES 约束它、
  `brief_checks` 机检遵从度）—— 所以风格是真生效、可核对的，不是界面上的装饰开关。
  用户自己说的话永远排在风格前面（见 `chat.runConfig()`）；
- 界面上要露出来：输入框下面那一行「风格：xxx · 改」，点一下跳风格页；**别把它藏进「设置」**；
- 「界面本身长什么样」由本技能管，不由这个开关管 —— 两者别混。

## 5. 改完必须验证（少一步都别提交）

```bash
cd apps/papercast && npx vue-tsc --noEmit          # 类型必须干净
cd /path/to/repo && node ops/shot/<脚本>            # 见下，控制台必须 0 错误
```

| 脚本 | 断言什么 |
| --- | --- |
| `ops/shot/ui_check.mjs` | 六个页面渲染、退出登录确认框、运营页回执、截图入 `docs/evidence/` |
| `ops/shot/ops_conclusion_check.mjs` | 六页 **0 个看板元件**、运营页服务默认 `display:none`、展开后 8 行 + 200 行日志 |
| `ops/shot/chat_check.mjs` | 对话入口：输入框 / 名单 / 展开产物 / 窄屏收起右栏 |
| `ops/shot/chat_viewers.mjs` | 查看器读的是**真产物**（不是内置示例） |
| `ops/shot/digest_banner_check.mjs` | 论文理解抬头是暖白底（计算样式 luminance > 0.9、无渐变） |
| `ops/shot/chat_drop.mjs` | 拖 PDF 的遮罩出现/消失（不真的上传） |
| `ops/shot/receipt_check.mjs` | 回执：作品库里每一件「已发布/没发成功」的详情都要有回执块，投过几次就几条，失败带原文，有链接的带链接（截图 `docs/evidence/library-receipt-*.png`） |
| `ops/shot/publish_latency_check.mjs` | 投递面板的等待核验（**不真发布**）：面板出现 ≤1s、面板到「确认发布」可点 ≤3s、主线程长任务 0 个、60 秒内重开不重拉 drafts、「重新检查」必须真重探，并摆出「正在投递…已等 N 秒」截图 `docs/evidence/publish-waiting.png`；超时/有长任务/多拉一次就 exit 1 |
| `ops/shot/mobile_check.mjs` | 手机端（默认 390×844，可传 `[origin] [宽] [高]`）：七页 + 产物查看器的横向溢出 / 越界元素 / 小于 32px 的按钮，截图 `docs/evidence/mobile-*.png` |
| `ops/shot/review_style_check.mjs` | Agent 审核：名单第七行「审核」+ 43 项检查、`#m-review` 的结论句「Agent 审核已经通过…」、检查项 pill；风格页：后端读到的 6 个技能、展开是 SKILL.md 原文、换风格落 localStorage 并显示在输入框那一行 |
| `ops/shot/interactions_check.mjs` | 互动 P1+P2：说「看看评论」只读读一遍（真开一次浏览器，几十秒）、页面上没有发送类按钮；贴一段评论 → 草稿**只落盘**（断言 drafts.jsonl 多一行且 `sent:false`）+ **发送卡出现但不自动执行**，点「先不做」后 `var/interactions/sent.jsonl` 行数不变。**脚本全程不点「发出去」** |
| `ops/shot/chat_action_check.mjs` | 对话派活：只读动作自动执行 + 一句话结论、有副作用的只出卡片且「先不做」无副作用、普通提问 0 新卡、控制台 0 错误（**不点任何会真发出去的动作**；跑前会预热运营数据缓存，别去撞浏览器预算） |

接口对账（前端调了后端没有的路由 = 上线即 404）：

```bash
apps/papercast-server/.venv/bin/python ops/check_api_contract.py
```

提交按仓库习惯：`feat(papercast): …` / `fix(papercast): …`，**只提交前端轨道与它需要的最小后端改动**，
不要 `git add -A`（工作区常有别的轨道在半写），commit 后 `git push origin main`。
细节与真实踩坑见 [references/verification.md](references/verification.md)。

## 6. 反模式（都是本项目真踩过的）

- `v-for` 与 `v-if` 写在**同一层** → `ch` 不在作用域，编译期就报错；要 `<template v-for>` 包一层；
- 展开区用 `v-show` 而模板里读 `items[0].stats` → 空数组时渲染崩溃，**组件挂不上，连页面数据都加载不出来**；
  要 `v-if`（不渲染就别求值）；
- 查看器直接 `fetch(a.url)` → 打到 dev server 上 404；必须 `assetUrl()`；
- 查看器默认读 `public/samples/*` → 界面显示的是**示例论文**，用户会当成真结果；
- 旧主题的深色块（例如深蓝黑渐变抬头）会残留 → 视觉审查时专门搜 `linear-gradient` 与 `#1xxxxx`；
- 用 `ops/check_api_contract.py` 漏查新增端点 → 前端调 404 接口，页面上什么都不显示（先看控制台）。
