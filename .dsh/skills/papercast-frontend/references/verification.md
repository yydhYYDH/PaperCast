# 验证与已踩过的坑

## 命令清单

```bash
# 1) 类型（在 apps/papercast 里跑，仓库根跑会找不到 tsconfig）
cd apps/papercast && npx vue-tsc --noEmit

# 2) 浏览器核验（需要前端在 5178、后端在 8000；截图落 docs/evidence/）
node ops/shot/ui_check.mjs
node ops/shot/ops_conclusion_check.mjs
node ops/shot/chat_check.mjs
node ops/shot/chat_viewers.mjs
node ops/shot/digest_banner_check.mjs

# 3) 前后端接口对账（必须用后端 venv 的 python，系统 python3 会 Permission denied）
apps/papercast-server/.venv/bin/python ops/check_api_contract.py

# 4) 后端单测（改后端才需要；纯函数/契约，秒级）
cd apps/papercast-server && .venv/bin/python -m pytest -q

# 5) 服务状态
curl -s http://127.0.0.1:8000/api/health
./ops/start_all.sh          # 幂等；日志 var/logs/，pid var/pids/
```

脚本里 chromium 用 `~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell`，
依赖在 `ops/shot/node_modules`。

## 投递这类「点下去要等」的动作怎么验

- **界面不卡 ≠ 没卡**：投递面板的「卡」实测是**在等服务器**（主线程长任务 0 个），
  量法用 `ops/shot/publish_latency_check.mjs`：它同时看「点击到有反馈的耗时」与
  `PerformanceObserver` 的 longtask —— 前者大后者为 0，就说明是等待不是卡死。
- **等待文案只报事实**：显示真实已等秒数 + 说清那边在做哪几步；**不做进度条**（进度只能靠猜）。
- **不可逆动作不进自动化检查**：验「正在投递」的样子时，只把 store 的 `busy`/`elapsed` 摆出来截图，
  绝不调 `deliver()`；渠道那边验填稿用后端的 `dry_run`（只填不发）。

## 判定标准

- **控制台 0 错误**（脚本里 `console` + `pageerror` 都收）；有 404 先看是不是漏配路由或忘了 `assetUrl()`；
- 断言写**计算样式或 DOM 数量**，不要写「我改过了」；
- 截图进 `docs/evidence/`，命名 `<主题>-<页面>.png`。

## 真实踩过的坑（照着避）

1. **`v-for` + `v-if` 同层**：报 `Property 'ch' does not exist`，改成 `<template v-for>` 包 `v-if`。
2. **展开区用 `v-show` 读 `items[0].stats`**：空数组时组件渲染抛错 → `onMounted` 也不执行，
   表现是「整页数据和服务都加载不出来」，看着像后端挂了。用 `v-if` 不渲染即不求值。
3. **查看器读内置示例**：`DigestViewer` 曾只读 `public/samples/digest.json`，真后端下显示的是示例论文；
   现在优先 `assetUrl(run.stages[…].artifacts[…].url)`，示例只兜底。
4. **相对产物地址**：后端返回 `/artifacts/...`，前端直接 fetch/src 会解析到 dev server → 404。
   统一 `assetUrl()`（`src/api/index.ts`）。
5. **旧深色残留**：`DigestViewer` 抬头曾是 `linear-gradient(#151d2c → #10151f)`（旧控制台主题），
   在暖色纸面上像一块黑板；审查时专门搜 `linear-gradient`、`#0…`、`#1…`。
6. **接口契约漂移**：前端调了后端没有的路由（例如刚加的 `POST /api/chat` 在后端重启前是 404），
   页面上表现为「什么都不显示」；先跑 `ops/check_api_contract.py`，再确认后端确实重启过
   （uvicorn 没开 `--reload`，改路由必须重启）。
7. **别 `git add -A`**：本工作区常有其它轨道在半写同一批文件；按白名单提交自己的文件。
8. **dev server 的 HMR 会陈旧**（2026-09-19 连着踩两次）：改完 SFC 后若页面报
   `_ctx.xxx is not a function`（模板是新的、script 还是旧的），或某个视图点了不切换，
   先怀疑 Vite 的内存模块图过期 —— 重启前端（`kill $(cat var/pids/frontend.pid)` 再
   `./ops/start_all.sh frontend`，它幂等但端口还被占时会跳过，所以要先 kill），
   别花时间怀疑自己的 Vue 写法。
9. **浏览器的代理来自环境变量**：这台机器挂着 `http_proxy=127.0.0.1:7890`，Playwright 会照它给
   浏览器配代理，**`--no-proxy-server` 盖不住它**（它是靠 `NO_PROXY` 决定直连哪些主机的）。
   访问 127.0.0.1 一直没事，是因为 `NO_PROXY` 里有 127.*；但测**局域网 IP**（手机走的那条路）时
   必须把那个 IP 也加进 `NO_PROXY`，否则会被代理拦成 502 —— `mobile_check.mjs` 已按 origin 自动补上。
   `curl` 同理：`NO_PROXY=127.0.0.1 curl …`。
10. **改 vite 配置不生效**：`ops/start_all.sh` 起前端时带的 `--host 127.0.0.1` 会**盖掉**
   `apps/papercast/vite.config.ts` 里的 `server.host`（手机访问就卡在这，2026-09-19 实测）。
10. **闸门分支要留一句实话**：`review_style_check.mjs` 在「当前没有停在闸门的 run」时
    `gateLine` 为 null —— 这时别写「已验证闸门上方那句话」，如实说它和已验的结论句是同一个
    `review.line`。要真验闸门，得等一条 run 走到 publish 闸门。

## 提交与协作

- 提交信息：`feat(papercast): …` / `fix(papercast): …`，正文写清「改了什么 + 怎么验的 + 没纳入谁的东西」；
- 推送：`git push origin main`（另一个轨道可能刚推过，先 `git log --oneline -3` 看一眼）；
- 跨轨道协调：`./ops/board.sh say <轨道名> "…"`，改公共路径（`ops/`、`var/`、`docs/`）前先 `ls -lat`。
