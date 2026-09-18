# ops · 跨组件脚本与本地工具

| 路径 | 说明 |
| --- | --- |
| `start_all.sh` | 起后端 `:8000` + 小红书 MCP `:18060` + 前端 `:5178`；幂等（端口占用即跳过）。用法：`./ops/start_all.sh [backend\|frontend\|mcp]` |
| `stop_all.sh` | 按 `var/pids/*.pid` 停服务 |
| `build_mcp.sh` | 重建 `ops/bin/` 里的三个 Go 二进制（干净版 + 本地 auth 版 + 登录工具） |
| `bin/` | 本地编译产物：`xiaohongshu-mcp`（上游 HEAD 干净版）、`xiaohongshu-mcp-auth`（含本地 `auth.go` 改动）、`xiaohongshu-login`（扫码登录工具）。**二进制，不要 `sed`/改内容，只能重建** |
| `shot/` | HTML→PNG 渲染与截图脚本（chrome-headless-shell，来自 Playwright 缓存）；前端 10 张界面截图由 `shot.mjs` 生成 |
| `skillsearch/` | 上游技能调研脚本（`clone.sh` 克隆 11 个参考仓库、`inspect/deep2/readmes` 提取 README 结构） |

## 约定

- 跨组件的才放这里；只服务单个组件的脚本放 `apps/<组件>/scripts/`（如 `run_dev.sh`、`smoke_test.sh`）；
- 所有脚本自推导工作区根：`WS="$(cd "$(dirname "$0")/.." && pwd)"`，不写死 `/home/yydh/hack`；
- 不在脚本里打印 cookie / token；发布类动作默认走「只出 `export/`，不真实投递」。

## 重建 Go 二进制（`build_mcp.sh` 做什么）

```bash
./ops/build_mcp.sh          # 用 var/toolchains 里的 Go 工具链与模块缓存（离线可编译）
```

编译环境：`GOROOT=var/toolchains/go`、`GOPATH=var/toolchains/gopath`、`GOCACHE=var/toolchains/gocache`、`GOPROXY=off`、`CGO_ENABLED=1`（与原二进制一致，动态链接）。
干净版是把 `git archive HEAD` 导出到 `var/build/xhs-clean` 后再编译，避免把本地未提交的 `auth.go` 混进主二进制。
