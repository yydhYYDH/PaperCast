# hack · 工作区

「一篇论文进去，多种传播物料出来，并且能真实投递到内容平台」的实验工作区。
主体是 **PaperCast**：论文 → 摘要长文 / 图文卡片 / 视频，再按渠道投递到小红书、知乎、B站。

- 安装：[`docs/INSTALL.md`](docs/INSTALL.md)
- 总纲与目标：[`docs/00-goal-and-architecture.md`](docs/00-goal-and-architecture.md)
- **目录与路径规范：[`docs/conventions.md`](docs/conventions.md)** ← 新增东西前先看这个
- 任务板（谁在做什么）：[`docs/TODO.md`](docs/TODO.md)
- 6 个 Agent 的覆盖、证据与边界：[`docs/02-six-agents-coverage.md`](docs/02-six-agents-coverage.md)
- 文档总入口：[`docs/README.md`](docs/README.md)
- 2026-09-19 的目录迁移对照（旧路径 → 新路径）：[`docs/migration-2026-09-19.md`](docs/migration-2026-09-19.md)

## 目录地图（五层，根目录只放这五个目录 + 四个元文件）

| 目录 | 放什么 | 可删性 |
| --- | --- | --- |
| `apps/` | **我们自己的代码** | 不可删 |
| | `papercast/` Vue 3 前端（六阶段 dashboard，mock/http 双适配器） | |
| | `papercast-server/` FastAPI 后端（L0–L3 + 横切控制面/证据审计） | |
| | `xiaohongshu-mcp/` 小红书渠道适配器（Go，**独立仓库、不在本仓库里**，见 `docs/INSTALL.md`） | |
| | `zhihu-publisher/` 知乎渠道适配器（Python + Playwright，HTTP :18070；契约见其 `README.md`） | |
| | `bilibili-publisher/` B站渠道适配器（Python + biliup CLI，HTTP :18080） | |
| `reference/` | **别人的代码，只读** | 可删可重克隆 |
| | `upstream/` 28 个上游参考实现（只读；清单与登记 commit 见 `docs/research/upstream-repos.md`，按登记 commit 复现：`./ops/sync_upstream.sh`） | |
| | `baoyu-research/` 出图后端调研（R2 素材增强） | |
| `ops/` | **跨组件的脚本与工具** | 脚本不可删 |
| | `install.sh` 一键安装；`start_all.sh` / `stop_all.sh` 起停服务；`build_mcp.sh` 重建 Go 二进制；`sync_upstream.sh` 核对/复现上游参考 | |
| | `shot/` HTML→PNG 渲染（chrome-headless-shell）；`bin/` 本地编译的发布二进制（**不入库**，见 `docs/INSTALL.md` §5.2） | |
| | `skillsearch/` 上游技能调研脚本 | |
| `var/` | **运行态**：runs / uploads / logs / pids / samples / cache / toolchains / secrets … | 可删（见 `var/README.md`） |
| `docs/` | 文档：总纲、规范、调研、证据、补丁 | 不可删 |

根目录只允许 `README.md`、`AGENTS.md`、`.gitignore`、`LICENSE` 四个文件，其余一律进五层。

## 安装

需要 **Python ≥ 3.11**（推荐 3.13）与 **Node ≥ 20**。
不需要 Go —— 除非你要自己编小红书 MCP（二进制不入库，`--with-mcp` 会用 Go 编译它）。
逐项说明、可选依赖与排查见 [`docs/INSTALL.md`](docs/INSTALL.md)。

```bash
git clone <这个仓库> && cd <仓库目录>

./ops/install.sh          # 最小可用：后端 venv + 前端依赖 + 上游只读克隆
./ops/install.sh --all    # 全都装上：两个发布通道 + 小红书 MCP（要 Go）+ 截图工具

# 安装脚本会自动从 .env.example 生成 .env，记得填 LLM 密钥
vi apps/papercast-server/.env
```

`install.sh` 幂等且非破坏性：已存在的 venv / `node_modules` / 上游克隆都跳过，只写 `var/` 与依赖目录。
不想用脚本就照 [`docs/INSTALL.md`](docs/INSTALL.md) 的手工步骤来。

Python 依赖分两档：`requirements.txt`（直接依赖 + 版本下限）与 `requirements.lock.txt`
（实跑环境的全量精确锁版），安装脚本默认装后者。前端用 `npm ci`（`package-lock.json` 已入库）。

## 快速开始

```bash
# 起全部服务（没装通道的服务会如实报 unconfigured，不影响其它服务）
./ops/start_all.sh
./ops/start_all.sh backend        # 也可以只起一个：backend | frontend | mcp | zhihu | bilibili

# 存活与引擎环境
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/env

# 停
./ops/stop_all.sh
```

其他常用入口：

| 目的 | 命令 |
| --- | --- |
| 渠道自检（不联网、不投递） | `apps/papercast-server/.venv/bin/python apps/papercast-server/scripts/check_channels.py` |
| 只跑后端（热重载） | `cd apps/papercast-server && ./scripts/run_dev.sh` |
| 端到端冒烟（上传 PDF → 建 run → 过闸门） | `apps/papercast-server/scripts/smoke_test.sh <paper.pdf>` |
| 真实投递小红书（默认只出 `export/` 不投递） | `PUBLISH=1 apps/papercast-server/scripts/smoke_test.sh <paper.pdf>` |
| 前端类型检查 / 构建 | `cd apps/papercast && npx vue-tsc --noEmit && npx vite build` |
| 编译发布二进制（小红书 MCP，二进制不入库） | `./ops/install.sh --with-mcp`（或已 clone 源码后 `./ops/build_mcp.sh`） |

## 服务与端口

| 服务 | 端口 | 进程来源 | 日志 |
| --- | --- | --- | --- |
| 后端 API | 8000 | `apps/papercast-server/.venv/bin/uvicorn` | `var/logs/backend.log` |
| 前端 dev | 5178 | `npm --prefix apps/papercast run dev` | `var/logs/frontend.log` |
| 小红书 MCP | 18060 | `ops/bin/xiaohongshu-mcp`（**需自建**：`./ops/install.sh --with-mcp`） | `var/logs/mcp.log` |
| 知乎发布通道 | 18070 | `apps/zhihu-publisher`（uvicorn，用 `var/toolchains/zhihu-mcp-venv`） | `var/logs/zhihu.log` |
| B站发布通道 | 18080 | `apps/bilibili-publisher`（uvicorn，底层 biliup CLI） | `var/logs/bilibili.log` |
| （DSH Web GUI） | 3080 | `dsh web`，不属于本工作区 | — |

## 根目录纪律

根目录只允许 `README.md`、`AGENTS.md`、`.gitignore`、`LICENSE` 四个文件，其余一律进五层。
2026-09-19 迁移期曾为并发开发的知乎轨道在根目录留了 8 个例外目录，**现已全部归位、例外归零**
（旧路径 → 新路径的完整对照见 [`docs/conventions.md`](docs/conventions.md) §9）。
