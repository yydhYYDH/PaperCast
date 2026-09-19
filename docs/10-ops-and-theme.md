# 10 · 运营维护（服务健康 / 日志 / 运营数据）与前端主题

> 2026-09-19 新增。回答用户的两个要求：**「运营维护这边你好像还没有做界面」**、
> **「看一下能不能获得浏览量啊点赞数量这些」**。前端页面在「运营维护」，后端在 `/api/ops/*`。

## 1. 一条原则：数字只来自真实接口，拿不到就写拿不到

运营页最容易变成「好看的假仪表盘」。这里立了三条硬规矩，代码里也按它写：

1. **内容从本机产物里发现**，不是手填清单：扫 `var/runs/**/video/upload_result.json`、
   `var/artifacts/**/*receipt*.json` 等回执，只认**真的投递过**的条目（含 BV 号 / 知乎文章 URL）；
2. **数字来自平台真实接口**，每个渠道卡片上写明来源（`source` 字段，界面直接展示）；
3. **取不到就说取不到**：`gap` 字段解释为什么没有（如「浏览量只在创作者中心可见」），
   取数失败的渠道用 `errors` 原样列出来 —— 尤其不能把「没抓到」伪装成「零赞」：
   知乎通道的 `/api/v1/stats` 抓不到正文标题时直接返回 502 `STATS_EMPTY`，而不是回 `votes: "0"`。

## 2. 各平台到底能拿到什么（2026-09-19 实测）

| 渠道 | 能拿到 | 拿不到 | 走什么 | 实测结果 |
| --- | --- | --- | --- | --- |
| B 站 | **播放 / 点赞 / 投币 / 收藏 / 评论 / 弹幕 / 分享**、标题、作者、发布时间 | — | 公开接口 `api.bilibili.com/x/web-interface/view?bvid=`（不需要登录） | ✅ `BV1DveU6GEPR`：view=1，其余 0（新稿件，正常） |
| 知乎 | 赞同数、评论数（正文页上的数字） | **浏览量**（只在创作者中心）、阅读时长 | 通道服务 `GET /api/v1/stats?url=` → 用**已登录浏览器**抓正文页 | ⚠️ 端点通了，但当前登录态下返回 `STATS_EMPTY`（页面没渲染出标题）→ 界面如实显示失败原因，不显示 0 |
| 小红书 | 账号级数据（粉丝 / 获赞 / 收藏），来自 MCP `GET /api/v1/user/me` | **单篇浏览量**（创作者中心）、单篇点赞（MCP 未暴露） | `xiaohongshu-mcp`（GET 接口，每次真开浏览器，很慢） | ⚠️ MCP 当前 `is_logged_in: false` → 先到「平台账号」扫码，再刷数据 |

结论（直接回答用户的疑问）：**B 站的播放/点赞拿得到，而且是全量互动数据；小红书与知乎的点赞拿得到
（知乎要登录态、小红书要创作者中心），但两家的「浏览量」都不是公开数据，拿不到。**

## 3. 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/ops/services` | 五个服务的真实状态：端口是否在听（TCP 连接）、pid 是否存活、HTTP 健康与耗时、日志文件大小/更新时间 |
| POST | `/api/ops/services/{name}/{action}` | `start` / `stop` / `restart`；一律交给 `ops/start_all.sh`、`ops/stop_all.sh` 执行（不在代码里拼命令行） |
| GET | `/api/ops/logs?name=&lines=&grep=` | 读 `var/logs/<name>.log` 的尾巴（最多 2000 行），可关键字过滤；只读 |
| GET | `/api/ops/metrics?force=` | 运营数据（60s 缓存，`force=true` 绕过） |

服务白名单固定为 `backend` / `frontend` / `mcp` / `zhihu` / `bilibili`，未知名字一律 404，
避免「运营页变成任意命令执行入口」。错误形状仍是 `{"error":{"code","message","details"}}`。

## 4. 前端

`apps/papercast/src/views/OpsView.vue`（导航「运营维护」，store 在 `stores/ops.ts`）：

- **运营数据**：三张汇总卡（B 站 / 知乎 / 小红书）+ 每渠道明细表（标题、外链、发布时间、互动指标列），
  指标列名本地化（`view → 播放`…）；失败原因用琥珀色警示块列出；空渠道显示 `gap` 说明；
- **服务与日志**：五张服务卡（状态胶囊、端口、pid、健康耗时、日志大小、启动/重启/停止/看日志），
  下方是日志查看器（服务切换、行数、关键字、4 秒自动刷新开关、级别着色）；
- **运行与产物**：运行队列计数（进行中 / 等人工确认 / 已完成 / 失败）。

停止 / 重启都有 `window.confirm` 二次确认（停止会中断该通道的登录与投递能力）。

## 5. 界面风格：暖调单色 · 编辑风格（对外展示用）

**受众**（用户 2026-09-19 明确）：评审专家、学生、路过的路人 —— 所以不做成「专业仪表盘」。
两轮调整的结论：先去掉深色控制台感（改浅色），再去掉 SaaS 渐变与彩色块（改暖调单色 + 衬线标题）。

实现（`apps/papercast/src/style.css`，一份完整样式表，只靠变量换肤）：

- 画布 `#f7f6f3`，卡片纯白 + 1px `#eaeaea` 描边，**不用阴影**（阴影只出现在弹层）；
- 标题衬线（`Newsreader / Iowan Old Style / Songti SC / Noto Serif CJK SC` → Georgia 回退），
  正文系统无衬线 15px / 1.7；主按钮近黑，危险动作淡红底；
- 颜色只表达状态：`#edf3ec/#346538`、`#fbf3db/#956400`、`#fdebec/#9f2f2d`、`#e1f3fe/#1f6c9f`；
- 每个页面顶部有 `page-head`：一个衬线大标题 + 一句人话说明（`工作台 / 运行记录 / 作品库 / 平台账号 / 运营维护 / 设置`）；
- 术语下沉：顶栏不再出现 `http adapter`、渠道卡不再出现 `localhost:18070`（`plainEndpoint()` 翻成人话）；
- 运营页的日志框改成浅色卡片（原来是深色终端块），指标列名本地化（播放/点赞/投币…）；
- 交互回执：`AppDialog.vue`（应用内确认框，替代 `window.confirm`）+ `AppToasts.vue`（气泡），
  退出登录 / 停启服务 / 更新数据都会给一句明确回执；
- 动效只有进入时的 10px 淡入上移，且尊重 `prefers-reduced-motion`。

核验：`node ops/shot/ui_check.mjs` —— 实测 `--canvas #f7f6f3`、标题字体解析为衬线栈、
六个导航项、确认框（打开→取消）、气泡「数据已更新」、五个服务卡 + 日志框、**控制台 0 错误**；
证据 `docs/evidence/ui-*.png`（工作台 / 平台账号 / 退出登录确认 / 运营数据 / 运营气泡 / 服务与日志 / 运行记录 / 作品库 / 设置 / 窄屏）。

## 6. 复现验证

```bash
./ops/start_all.sh                      # 五个服务
curl -s http://127.0.0.1:8000/api/ops/services | head -c 400
curl -s http://127.0.0.1:8000/api/ops/metrics | python3 -m json.tool | head -40
node ops/shot/ops_theme_check.mjs       # 换肤 + 运营页的真实核验（打印计算样式/接口码/控制台错误）
```

证据（`docs/evidence/`）：`ops-dashboard.png`、`ops-services.png`、`theme-light-workbench.png`、
`theme-light-platforms.png`。最近一次核验：主题计算样式 `--bg=#f5f7fb --accent=#4f46e5`、
运营数据 3 张卡 + 1 行 B 站明细、服务卡 5 张（全部在线，pid/健康耗时/日志大小齐全）、
接口全部 200、**控制台 0 错误**。

## 7. 已知边界

- `/api/ops/metrics` 有 60s 缓存：小红书那条要真开浏览器（可达 1～2 分钟），不缓存会拖死页面；
- 知乎 `/api/v1/stats` 目前抓到的是登录墙页面（`STATS_EMPTY`）——上游 `get_feed_detail` 的选择器
  依赖知乎当前 DOM，需要再查一次（属未完成项）；
- 小红书单篇互动数据需要在 `apps/xiaohongshu-mcp` 里补创作者中心抓取（MCP 目前只覆盖公开 feed 接口）；
- 服务的启动是同步调用 `ops/` 脚本（90s 超时），起停期间前端按钮禁用，但不是任务队列；
- 真实投递仍按原约定：必须过人工闸门。

## 8. 退出登录（2026-09-19 做实）

三个渠道的凭证位置不同，退出登录按各自的真实位置清理，并把**执行结果**回给前端（前端不再收到空洞的 204）：

| 渠道 | 清理什么 | 备注 |
| --- | --- | --- |
| 知乎 | `var/secrets/zhihu/cookies.json`（由 zhihu-publisher 的 `DELETE /api/v1/login/cookies`）+ 清它自己的状态缓存 | 缓存不清会「登出后 15s 内还显示已登录」——已修 |
| B 站 | 通道服务自己的 cookies + `var/home/.bilibili/cookies.json` + `var/artifacts/bilibili/cookies.json`（biliup 的 HOME 位置，只清服务侧会仍显示已登录） | 实测：登出后渠道状态立刻变 `login_required` |
| 小红书 | `apps/xiaohongshu-mcp/cookies.json` **+ 浏览器 profile `var/cache/xiaohongshu-mcp/browser`**，然后重启 MCP | 见下 |

小红书为什么连 profile 一起删：MCP 的 `/api/v1/login/status` 不是读文件，而是**真开一个浏览器**
访问 `xiaohongshu.com/explore` 看 DOM 里有没有用户菜单，而它的 `POST /logout` 只是它自己的 HTTP 鉴权登出
（与小红书账号无关）。所以只删 `cookies.json` 时它照样报「已登录」——实测确认；
删掉 profile 并重启 MCP 后才会真的变成未登录。重启顺带清掉进程内的 300s 状态缓存。

验证方式（不牺牲用户登录态）：把 profile 目录 `mv` 到 `var/scratch/`，重启 MCP 观察状态变化，再 `mv` 回来。
凭证文件同样先备份到 `var/scratch/cookie-backup/` 再恢复。当前三渠道均为 `ready`。
## 9. 对话式入口（2026-09-19）

工作台不再是三栏控制台，而是**一个对话 + 右侧「谁在干活」名单**：

- 前端文件：`src/views/WorkbenchView.vue`、`src/components/chat/{ChatThread,ChatMessage,Composer,AgentRail}.vue`、`src/stores/chat.ts`；
- **不新造状态**：消息由 `runs` store 里那条运行推导（阶段状态 / 产物清单 / 自检 / 最后一条日志），界面不会和状态漂移；
- 三种输入走同一个框：粘贴 arXiv 链接或编号 → 直接开跑；把 PDF 拖进聊天区 → `POST /api/uploads` 拿 `uploadId` → `source={kind:'pdf', value: uploadId}`；其它话 → 问模型；
- `POST /api/chat`（后端 `app/chat_api.py`）：只把该运行已落盘的事实源（`run.json` + `understand/digest.json` + 产物清单）喂给配置好的模型，事实源里没有的直接说没有；没配模型返回 400 `LLM_NOT_CONFIGURED`；
- 人工闸门变成对话里的一条提问，**默认动作排第一**（其余选项为安静按钮）；
- 右侧名单：六个环节的状态点（进行中会呼吸）+ 当前动作 + 产物数，点一行滚到它说过的话；
- 顺序默认全开（长文 + 海报 + 视频 + 三平台排稿），选项不放在入口，想改去「设置」。

顺带修掉两处「看着像真结果」的坑：查看器的产物地址统一走 `assetUrl()`（后端给的是相对路径），
`digest.json` / `narration.json` 优先读**这次运行**的真产物，内置示例只在读不到时兜底。

核验脚本：`ops/shot/chat_check.mjs`（渲染与窄屏）、`ops/shot/chat_viewers.mjs`（查看器读真产物）、`ops/shot/chat_drop.mjs`（拖拽遮罩）。
实测：提问「这篇论文的局限是什么」返回的是该论文真实局限（来自 digest），未配置/未重启时会明确报错而不是装作答了。
## 10. 运营维护：只留结论（2026-09-19）

用户对受众的判断是「评审专家 / 学生 / 路人」，所以运营页从看板改成"先说结论"：

- **第一屏只有一句话**：能把真实数字加起来就说结论（`已发出 3 条内容，合计 1,204 个播放、86 个点赞`），
  加不出来就直说读不到，并把第一个原因写在同一句里（`现在还读不到任何数字 —— 小红书 MCP 报告未登录…`）；
- **最多三个数字**（播放 / 点赞 / 评论），没有就不显示空位；
- **每个平台一行**：平台名 + 一句状态（发了几条 / 为什么读不到）+ 一个关键数 + 「看明细」；
  明细表要手动展开，默认不占地方；
- **服务与日志默认收起**：折叠条本身就是一句结论（`这台机器上的 5 个服务都在跑。`），展开后才是
  逐服务的一行（在跑 / 没在跑 + 启动重启停止看日志），日志再点一次才拉出来；
- **运行概况也是一句话**（`一共跑过 11 次，5 次完成、1 次等你确认、5 次没成功。`），不是五张卡；
- 「看数据 / 看服务状态」的分段控件**删了** —— 一页看完，选择越少越好；
- `src/style.css` 里的 `.stat-grid / .stat-card / .svc-grid / .svc` 整块删除，并在原处留了注释，
  防止以后有人顺手把卡片墙拼回来。

核验：`ops/shot/ops_conclusion_check.mjs` —— 六个页面都断言「0 个看板元件」、运营页断言
服务默认 `display:none`、展开后有 8 行 + 200 行日志、控制台 0 错误；
`ops/shot/ui_check.mjs` 与 `ops/shot/chat_check.mjs` 同步更新以匹配新结构。
## 11. 仓库级技能：`papercast-frontend`（2026-09-19）

前端这一套规矩（暖调单色、对话优先入口、只留结论、不许看板化、验证脚本清单、真实踩过的坑）
现在是一条**可被 dsh 会话直接加载的技能**，放在：

```
.dsh/skills/papercast-frontend/
├── SKILL.md                      # 什么时候用 / 视觉基调 / 文案声音 / 代码地图 / 硬规则 / 验证 / 反模式
└── references/
    ├── design-system.md          # token 表、排印、间距、组件配方、文案模板
    └── verification.md           # 命令清单、判定标准、7 个真实踩坑、提交与协作
```

- **为什么放仓库里**：DSH 的技能发现根优先级是 `<repo>/.dsh/skills` > `<repo>/.agents/skills` > `~/.dsh/skills` > `~/.agents/skills`。
  放仓库里 = 跟着代码走、能进 git、换机器/换会话都在，也不会污染用户目录；
- **和 `ops/install_skills.sh` 的分工**：那个脚本装的是 4 个**第三方**设计技能（`reference/upstream/` → `~/.agents/skills`）；
  本仓库自己的规范走 `.dsh/skills/`；
- `AGENTS.md` §1 已把 `.dsh/` 写成根目录唯一允许的目录（只放技能包，别的仍必须进五层）；
- 新增技能：建 `.dsh/skills/<name>/SKILL.md`，frontmatter 写 `name`（`^[a-z0-9]+(-[a-z0-9]+)*$`）+ `description`，
  目录名与 `name` 保持一致；写得越具体越有用 —— 命令、路径、断言、以及"我们踩过什么坑"。

核验：写完当场在会话里 `skill(name: "papercast-frontend")` 加载成功（provider `filesystem`，资源目录即仓库内路径），
技能目录会随会话技能清单自动刷新，不需要重启 dsh。

## 12. 用对话发任务：一句话 → 一张动作卡（2026-09-19）

> 用户原话：「运营管理这边是不是还需要一个 agent 可以帮忙做一些互动？」「你要不合并到主 agent」
> 「**现在主 agent 真的好像不能对话**」「希望是那种可用对话的形式来发布任务」。

**先说诊断**（实测，不是猜）：主 agent 不是坏了 —— `POST /api/chat` 一直能答（curl 一句
「你好，你能做什么」模型答得很正常）。它的问题是**什么都做不了**：那个端点只把 run.json /
digest.json 喂给模型换一段话，没有任何动作；前端 `stores/chat.ts` 还会抢先改道（话里带 arXiv
号 → 直接开跑，别的链接 → 一句「拿不到正文」）。所以「发任务」这条路是缺的，不是坏的。

**结论（用户拍板）**：**不新增第 7 个 agent、也不新增 stage** —— 六个 stage 的前端契约一个字不动，
把能力挂到主 agent 身上（与 `02-six-agents-coverage.md` §2.4「社区运营不新增 stage」一脉相承）。
互动（读评论 / 起草回复）是主 agent 的一项技能，不是第七个人。

### 12.1 契约：返回体多一个 `action`

`POST /api/chat` 的响应除了 `reply`，可以有 `action`（说不出动作时为 `null`）：

```jsonc
{ "kind": "gate|metrics|service|run",
  "title": "要重启后端吗？",          // 卡片的标题，用人话
  "detail": "服务名 backend，动作 restart…",
  "params": { "name": "backend", "action": "restart" },
  "needsConfirm": true,               // false = 只读动作，前端直接执行（少一次点击）
  "confirmLabel": "重启",             // 那个动词按钮的文案
  "risk": "readonly|local|public" }   // public = 真发到平台上，界面按危险动作渲染
```

前端把它渲染成对话里的一张卡（`ChatMessage.vue` 的 `.act`）：一句话 + 一个动词按钮 + 「先不做」，
点了才执行；执行完卡片收起、补一条回执；失败卡片标红并说明原因。

### 12.2 四条设计取舍

1. **规则优先、模型兜底**。认得出来的意图由代码直接给卡（不花模型的钱、不受模型当时状态影响）
   —— 没配模型时「重跑一遍 / 放行 / 看数据 / 重启服务」照样发得出去；认不出来才落到自由问答。
   代码里的规则表：起停服务（5 个白名单服务名）、人工闸门（只在**真有**等待放行的阶段时给卡）、
   重跑一遍（带上这次的 source）、运营数据、互动（本轮只如实说「还没接上」）。
2. **服务端零副作用**。`_propose()` 只产出「打算做什么 + 参数」，执行全在前端、由用户点卡片触发 ——
   这个端点永远不会因为一句话就投递、就停进程，人工闸门不在这里被绕过。
3. **闸门只认内存里那份状态**（`_live_run()` 走 `store.get()`，不读 run.json）。原因是被实测教过一次：
   盘上写着 `failed`、界面还停在「等待放行」（漂移），照着盘提卡会递出一个早已不成立的
   stageId/optionId。**没有等待放行的阶段时，「放行」这类话不许给卡**，这条有单测锁着。
4. **只读才自动执行**。`risk=readonly`（看数据）直接跑；动本机服务的动作除了卡片还要过一遍应用内确认框
   （停/重启会中断在跑的运行）；`public` 的动作（真发出去）按钮按危险动作渲染并在卡上写明「撤不回来」。

### 12.3 顺手修掉的落单问题①

`stores/runs.ts` 的 `confirm()` / `cancel()` 原来没有 try/catch，而后端在「重启后没有活跃任务」时返
**409 GATE_REJECTED** —— 四个调用点（阶段卡 / 对话里的闸门提问 / 发布页三个按钮）全会变成无人接的
promise rejection：用户点了放行，界面永远停在「等待放行」且一句解释都没有。现在失败 → 气泡说原因 +
拉一次真实状态 + 返回 `false`（**不抛**，免得又造一个无人接的 rejection）。演示模式的自动放行也补了
`.catch()` 复位标记（否则 409 之后永不重试且无提示）。

### 12.4 小红书账号安全（这是「互动」为什么分三步走）

本机的 `xiaohongshu-mcp` **本来就有**读评论（`get_feed_detail`）、回复评论（`reply_comment_in_feed`）、
通知（`list_notifications` / `reply_notification` / `like_notification`）这些工具，是后端当年
**故意没暴露**（`docs/03-module-publish.md`：避免被当成自动化运营工具滥用）。现在要接，按风险分三步：

| 步骤 | 做什么 | 状态 |
| --- | --- | --- |
| P1 | **只读**评论/通知 + 由主 agent 起草回复（草稿只落盘，不发送） | 本轮之后做 |
| P2 | 逐条人工确认后才发送（走 MCP 访问预算，默认关） | 等账号恢复 + 用户明确授权 |
| — | 全自动回复 | **不做**：账号真实吃过风控且每次调用都真开浏览器 |

同一个道理，本轮把「看数据」的动作**走 60s 缓存**（`force=false`）而不是强制刷新 —— 每 force 一次
就是每个平台真探测一次（小红书那条要真开浏览器）。

### 12.5 核验

```bash
cd apps/papercast && npx vue-tsc --noEmit                        # 类型
cd apps/papercast-server && .venv/bin/python -m pytest -q         # 含 tests/test_chat_actions.py（9 条，锁上面三条性质）
curl -s -X POST http://127.0.0.1:8000/api/chat -H 'content-type: application/json' \
     -d '{"message":"重新跑一遍","runId":"<runId>","history":[]}' | python3 -m json.tool   # 看 action
node ops/shot/chat_action_check.mjs                               # 真界面：只读自动执行 / 卡片出现 / 「先不做」收起 / 普通提问不产生卡片 / 控制台 0 错误
```

`chat_action_check.mjs` 断言的四件事（对照真后端跑）：① 「看下现在的数据」**不摆卡片**、随后补一条
一句话结论（读不到就说读不到）；② 「重新跑一遍」只出卡片（按钮是「重跑一遍」+「先不做」），点「先不做」
卡片收起且**没有副作用**；③ 普通提问（这篇论文的局限是什么）不产生带按钮的卡片；④ 控制台 0 错误。
这个脚本**不点任何会真发出去的动作**，跑之前会先预热一次 60s 缓存，免得核验本身去撞浏览器预算。
证据截图：`docs/evidence/chat-action-{metrics,card,dismissed}.png`。
