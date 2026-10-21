# ops · 跨组件脚本与本地工具

| 路径 | 说明 |
| --- | --- |
| `start_all.sh` | 起后端 `:8000` + 三个发布通道（小红书 `:18060`、知乎 `:18070`、B站 `:18080`）+ 前端 `:5178`；幂等（端口占用即跳过）。用法：`./ops/start_all.sh [backend\|frontend\|mcp\|zhihu\|bilibili]` |
| `start_all.sh` 的 MCP 分支 | 会自动 `cd apps/xiaohongshu-mcp/` 后再起进程 —— 原因见下面「启动约束」 |
| `start_all.sh` 的 bilibili 分支 | 起 `apps/bilibili-publisher`（:18080，B 站投稿通道）。没装 biliup 也能起，服务会如实报 `unconfigured` |
| `biliup_login_pty.py` | 用 pty 驱动 `biliup login`（扫码菜单），原始输出写 `var/logs/biliup_login_pty.log`。biliup 装在 `var/toolchains/bili-venv`（**不在 PATH 里**，通道服务会自己找），凭证由 biliup 自管在 `var/home/.bilibili/cookies.json`（HOME 重定向） |
| `stop_all.sh` | 按 `var/pids/*.pid` 停服务 |
| `build_mcp.sh` | 重建 `ops/bin/` 里的三个 Go 二进制（干净版 + 本地 auth 版 + 登录工具） |
| `bin/` | 本地编译产物：`xiaohongshu-mcp`（上游 HEAD 干净版）、`xiaohongshu-mcp-auth`（含本地 `auth.go` 改动）、`xiaohongshu-login`（扫码登录工具）。**不入库**（`.gitignore` 已忽略整个目录）：别人 clone 后要自己编，`./ops/install.sh --with-mcp` 一条命令搞定。**二进制，不要 `sed`/改内容，只能重建** |
| `shot/` | HTML→PNG 渲染与截图脚本（chrome-headless-shell，来自 Playwright 缓存）；前端 10 张界面截图由 `shot.mjs` 生成 |
| `shot/render.mjs` | **通用 HTML→PNG 渲染入口**（可被其它组件调用）：`node ops/shot/render.mjs --html <p> --out <png> --width W --height H [--check]`，输出单行 JSON（面板溢出、缺图、面积填充率），退出码 3 = 几何自检不过。海报走这条 |
| `shot/render_social_deck.mjs` | **社交组图渲染入口**：`node ops/shot/render_social_deck.mjs <task-dir\|index.html> [--out <dir>] [--scale 2] [--only ids]`，把单文件 deck 里每个 `.poster`/`.cover` 节点各截一张 PNG（产物默认落 `<task-dir>/output/`，单行 JSON 汇总），退出码 3 = 一个卡片节点都没找到。小红书组图走这条（配合 `~/.agents/skills/guizang-social-card-skill` 的 `validate-social-deck.mjs` 自检，装法见 `ops/install_skills.sh`） |
| `imagegen.sh` | **文生图入口**：调 `baoyu-image-gen` 的官方 API 后端（默认 dashscope/qwen-image-2.0-pro）。密钥放 `var/secrets/imagegen.env`；内置 `npm_config_cache` 指向 `var/`（沙箱下 `~/.npm` 只读，否则 `npx` 必挂） |
| `sync_upstream.sh` | 按 `docs/research/upstream-repos.md` 的登记表复现/核对 `reference/upstream/`（`--list` 只核对，默认补齐缺失；幂等、非破坏） |
| `skillsearch/` | 上游技能调研脚本（`clone.sh` 克隆 11 个参考仓库、`inspect/deep2/readmes` 提取 README 结构） |
| `zhihu_fetch.py` | **知乎文章 → 正文+图片**：`./ops/zhihu_fetch.py <url> [-o OUT] [--no-download] [--json]`。用 Playwright + `var/secrets/zhihu/cookies.json` 抓取（直连 403），产出 `article.md` + 下载好的 `images/` + `meta.json`，默认落 `var/state/zhihu-fetch/<id>/`。自管理解释器（自动用 `var/toolchains/zhihu-mcp-venv` 重跑）。后端 intake 的 `kind=zhihu/url` 就是调它 |
| `hf_daily_job.sh` | **每日 HF 论文 → 小红书定时发布**入口：先幂等确保 `backend`/`mcp` 在跑，再交给 `hf_daily_job.py`。systemd timer 调它，也可手动跑（`--dry-run` / `--force` / `--check`） |
| `hf_daily_job.py` | 逻辑本体：取 HF daily upvotes 前 N（默认 5）→ 按 `var/state/hf-daily-job/seen.json` 去重 → 建 run 生成小红书图文（有界并发 `HF_CONCURRENCY`，默认 2）→ 自动放行 publish 闸门（`draft`，只生成）→ 读 `publish/xiaohongshu/export/` → 调小红书 MCP `/api/v1/publish` 带 `schedule_at` **排期发布**。当天成功打 `<日期>.done` 卡，单篇失败不拖垮整批 |
| `systemd/` | `papercast-hf-daily.service` + `.timer` 模板（`@WS@` 占位，安装时替换）。timer 每天 12:00，**`Persistent=true` 是实现"关机错过、开机补跑"的关键** |
| `install_hf_daily_timer.sh` | 安装/卸载 systemd user timer（`--uninstall`）。需 user systemd（`systemctl --user`）可用 |
| `install_hf_daily_cron.sh` | Linux cron 方案：写两行 user crontab —— `0 12 * * *` 每天跑 + `@reboot` 开机补跑；脚本内部有"到点才跑 + 当天打卡"，早于 12:00 的触发会自行跳过。前提是 cron 守护进程在跑且开机自启 |
| `install_hf_daily_windows_task.sh` | **本机（WSL2 旧式 init，无 systemd、cron 不跑）实际使用的方案**：注册 Windows 计划任务 `PaperCast-HF-Daily`（每天 12:00 调 `wsl.exe` → `hf_daily_job.sh`）+ 登录自启 `hf_daily.vbs`（Startup 文件夹，隐藏窗口，每次登录补跑）。`--uninstall` 可卸 |

作业可调环境变量：`HF_DAILY_TOP`（默认 5）、`HF_PUBLISH_AT`（排期起点，默认 `18:00`）、`HF_PUBLISH_GAP_MIN`（每篇间隔分钟，默认 15）、`HF_CONCURRENCY`（并发生成数，默认 2）、`HF_RUN_TIMEOUT_SEC`（单篇超时，默认 1800）。

## 约定

- 跨组件的才放这里；只服务单个组件的脚本放 `apps/<组件>/scripts/`（如 `run_dev.sh`、`smoke_test.sh`）；
- 所有脚本自推导工作区根：`WS="$(cd "$(dirname "$0")/.." && pwd)"`，不写死 `/home/yydh/hack`；
- 不在脚本里打印 cookie / token；发布类动作默认走「只出 `export/`，不真实投递」。

## 启动约束（迁移时踩过的坑）

| 约束 | 原因 | 表现 |
| --- | --- | --- |
| 小红书 MCP 必须在 `apps/xiaohongshu-mcp/` 目录里启动 | 它的 cookie 是**相对进程当前目录**的 `cookies.json`（`cookies/cookies.go` 的 `localCookiesPath`） | 换 cwd 后会在新目录新建一个空 `cookies.json`，`/api/v1/login/status` 直接返回 `is_logged_in: false` |
| 后端 venv 不能整体搬目录（搬了要改 shebang） | `.venv/bin/*` 的 shebang 与 `activate*` 里写的是绝对路径 | 报 `env: '.../.venv/bin/uvicorn': No such file or directory`（文件其实在） |
| 二进制只能重建，不能改内容 | Go 把源码路径编译进二进制，改字符串会破坏内部偏移 | 启动即 core dump |

## 重建 Go 二进制（`build_mcp.sh` 做什么）

```bash
./ops/build_mcp.sh          # 用 var/toolchains 里的 Go 工具链与模块缓存（离线可编译）
```

编译环境：`GOPATH=var/toolchains/gopath`、`GOCACHE=var/toolchains/gocache`、`CGO_ENABLED=1`（与原二进制一致，动态链接）。
Go 工具链优先用工作区自带的 `var/toolchains/go`（此时 `GOPROXY=off`，离线可编）；
新机器上没有它就回落到系统 `go`（需要 >= 1.24，`GOPROXY` 默认走 proxy.golang.org）。
干净版是把 `git archive HEAD` 导出到 `var/build/xhs-clean` 后再编译，避免把本地未提交的 `auth.go` 混进主二进制。
