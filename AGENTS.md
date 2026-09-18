# AGENTS.md · 在本工作区干活前先读

完整规范见 [`docs/conventions.md`](docs/conventions.md)，这里只列最容易踩的几条。

## 1. 目录：五层，不许在根目录乱建

| 你要放的东西 | 放哪里 |
| --- | --- |
| 我们自己的代码 | `apps/<组件>/` |
| 别人的仓库（只读参考） | `reference/upstream/<name>/`，并在 `docs/research/upstream-repos.md` 登记 |
| 跨组件脚本、本地编译的二进制、渲染工具 | `ops/` |
| 跑出来的数据、缓存、日志、venv、conda env、工具链 | `var/` |
| 文档 | 全局的进 `docs/`，跟代码走的留在组件内（`apps/<组件>/docs/` 或 `README.md`） |

根目录只允许 `README.md`、`AGENTS.md`、`.gitignore` 三个文件。
当前有 8 个例外目录（并发中的知乎轨道），已写进 `.gitignore`，别在它们旁边再加新目录。

## 2. 路径：一律不写死 /home/yydh/hack

- Shell 脚本：`WS="$(cd "$(dirname "$0")/.." && pwd)"`，再拼 `$WS/apps/...`；
- Python/TS 代码：路径来自环境变量或相对自身文件位置推导，不出现绝对路径；
- 运行期数据目录由 `ops/start_all.sh` 通过 `PAPERCAST_DATA_DIR` / `PAPERCAST_UPLOAD_DIR` 注入到 `var/`；
- 缓存环境变量：`XDG_CACHE_HOME=$WS/var/cache`、`UV_CACHE_DIR=$WS/var/cache/uv`。

## 3. 别做的事

- 别把 `var/`、`node_modules`、`.venv`、`cookies.json`、`.env` 加进 git（`.gitignore` 已覆盖，别用 `-f`）；
- 别改 `reference/upstream/` 里的代码（要改就复制成 `apps/` 下的组件，或用 `docs/patches/` 记补丁）；
- 别用 `git add` 把 `apps/xiaohongshu-mcp`（独立仓库）塞进根仓库；
- 别用 `sed` 批量扫 `ops/bin/` 或任何二进制（会改坏内嵌路径，2026-09-19 已经踩过一次）；
- 发行/发布类动作（真实投递）必须过人工闸门，脚本默认只出 `export/`。

## 4. 验证命令（改完随手跑）

```bash
./ops/start_all.sh                     # 起服务（幂等：端口占用会跳过）
curl -s http://127.0.0.1:8000/api/health
cd apps/papercast && npx vue-tsc --noEmit
./ops/stop_all.sh
```

日志在 `var/logs/`，pid 在 `var/pids/`。服务起不来先看日志，再 `tail` 组件自己的 `README.md`。

## 5. 并发提醒

本工作区可能同时有别的会话在跑（例如知乎轨道）。改公共路径（`ops/`、`var/`、`docs/`）前，先 `ls -lat` 看有没有正在写入的新目录。
