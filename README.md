# hack · 工作区

「一篇论文进去，多种传播物料出来，并且能真实投递到内容平台」的实验工作区。
主体是 **PaperCast**（论文 → 小红书图文，前后端 + 渠道适配器已跑通骨架）；
另有并行的发布轨道 **知乎**（进行中，见文末「迁移期例外」）。

- 总纲与目标：[`docs/00-goal-and-architecture.md`](docs/00-goal-and-architecture.md)
- **目录与路径规范：[`docs/conventions.md`](docs/conventions.md)** ← 新增东西前先看这个
- 文档总入口：[`docs/README.md`](docs/README.md)
- 2026-09-19 的目录迁移对照（旧路径 → 新路径）：[`docs/migration-2026-09-19.md`](docs/migration-2026-09-19.md)

## 目录地图（五层，根目录只放这五个目录 + 三个元文件）

| 目录 | 放什么 | 可删性 |
| --- | --- | --- |
| `apps/` | **我们自己的代码** | 不可删 |
| | `papercast/` Vue 3 前端（六阶段 dashboard，mock/http 双适配器） | |
| | `papercast-server/` FastAPI 后端（L0–L3 + 横切控制面/证据审计） | |
| | `xiaohongshu-mcp/` 小红书渠道适配器（Go，**独立 git 仓库**，含本地 auth 改动） | |
| | `zhihu-publisher/` 知乎渠道适配器（Python + Playwright，HTTP :18070；契约见其 `README.md`） | |
| `reference/` | **别人的代码，只读** | 可删可重克隆 |
| | `upstream/` 23 个上游参考实现（清单见 `docs/research/upstream-repos.md`） | |
| | `baoyu-research/` 出图后端调研（R2 素材增强） | |
| `ops/` | **跨组件的脚本与工具** | 脚本不可删 |
| | `start_all.sh` / `stop_all.sh` 起停三个服务；`build_mcp.sh` 重建 Go 二进制；`sync_upstream.sh` 核对/复现上游参考 | |
| | `shot/` HTML→PNG 渲染（chrome-headless-shell）；`bin/` 本地编译的发布二进制 | |
| | `skillsearch/` 上游技能调研脚本 | |
| `var/` | **运行态**：runs / uploads / logs / pids / samples / cache / toolchains | 可删（见 `var/README.md`） |
| `docs/` | 文档：总纲、规范、调研、证据、补丁 | 不可删 |

根目录只额外允许 `README.md`、`AGENTS.md`、`.gitignore` 三个文件。

## 快速开始

```bash
# 起全部服务：后端 :8000 + 三个发布通道（小红书 :18060 / 知乎 :18070 / B站 :18080）+ 前端 :5178
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
| 只跑后端（热重载） | `cd apps/papercast-server && ./scripts/run_dev.sh` |
| 端到端冒烟（上传 PDF → 建 run → 过闸门） | `apps/papercast-server/scripts/smoke_test.sh <paper.pdf>` |
| 真实投递小红书（默认只出 `export/` 不投递） | `PUBLISH=1 apps/papercast-server/scripts/smoke_test.sh <paper.pdf>` |
| 前端类型检查 / 构建 | `cd apps/papercast && npx vue-tsc --noEmit && npx vite build` |
| 重建发布二进制 | `./ops/build_mcp.sh` |

## 服务与端口

| 服务 | 端口 | 进程来源 | 日志 |
| --- | --- | --- | --- |
| 后端 API | 8000 | `apps/papercast-server/.venv/bin/uvicorn` | `var/logs/backend.log` |
| 前端 dev | 5178 | `npm --prefix apps/papercast run dev` | `var/logs/frontend.log` |
| 小红书 MCP | 18060 | `ops/bin/xiaohongshu-mcp` | `var/logs/mcp.log` |
| 知乎发布通道 | 18070 | `apps/zhihu-publisher`（uvicorn，用 `var/toolchains/zhihu-mcp-venv`） | `var/logs/zhihu.log` |
| B站发布通道 | 18080 | `apps/bilibili-publisher`（uvicorn，底层 biliup CLI） | `var/logs/bilibili.log` |
| （DSH Web GUI） | 3080 | `dsh web`，不属于本工作区 | — |

## 迁移期例外（并发中的知乎轨道）

知乎发布轨道正在并行开发，其目录暂时留在根目录，**未纳入上面的五层结构**：
迁移期曾有 8 个例外目录，2026-09-19 已全部归位（见 `docs/conventions.md` §9），现在一个都不剩。
它们已全部写进 `.gitignore`；那条轨道收尾后按 `docs/conventions.md` 第 9 节归位。
