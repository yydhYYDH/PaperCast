# 目录迁移记录 · 2026-09-19

> 一次把「代码 / 参考 / 工具 / 运行态 / 文档」混在同一层的扁平工作区，整理成五层结构。
> 规范见 [`conventions.md`](conventions.md)。本文件只记录**改了什么、为什么、怎么回滚**。

## 1. 迁移前的问题

| # | 问题 | 证据 |
| --- | --- | --- |
| 1 | 工作区根**不是 git 仓库**，无 `.gitignore`：四天的工作没有任何版本兜底 | `git status` → `fatal: not a git repository` |
| 2 | 三类内容同层混放：产品代码、上游克隆、机器缓存 | 根目录 12 个条目里有 `.cache`/`.tools`/`repos` 与 `papercast*` 并列 |
| 3 | 重复目录：`paper-share-skills/` 与 `repos/paper-share-skills/` 内容一致 | 86 个文件 md5 清单无差异 |
| 4 | 运行态埋在组件里：`papercast-server/data/`、`.venv/`、登录态 `.cache/` | `data/{runs,uploads,logs,pids}` 与源码同级 |
| 5 | 文档分叉：总纲在 `docs/`（1 个文件），调研结论是根目录一个孤立 md | — |
| 6 | 联调垃圾散落：`.tools/{one.txt,f.json,server.log}`（含测试笔记 token）、`papercast-server/:memory:.ses` | — |
| 7 | 上游二进制来路不明：文档没记怎么编译的 | `.tools/bin/{xiaohongshu-mcp,xiaohongshu-mcp-auth,xiaohongshu-login}` |

## 2. 旧 → 新 对照表

| 旧路径 | 新路径 |
| --- | --- |
| `papercast/` | `apps/papercast/` |
| `papercast-server/` | `apps/papercast-server/` |
| `xiaohongshu-mcp/` | `apps/xiaohongshu-mcp/` |
| `repos/`（23 个克隆） | `reference/upstream/` |
| `baoyu-research/` | `reference/baoyu-research/` |
| `.tools/shot/` | `ops/shot/` |
| `.tools/bin/` | `ops/bin/` |
| `.skillsearch/` | `ops/skillsearch/` |
| `papercast-server/scripts/start_all.sh`、`stop_all.sh` | `ops/start_all.sh`、`ops/stop_all.sh`（跨组件，故上移） |
| `papercast-server/scripts/{run_dev,smoke_test}.sh` | 原地不动（单组件脚本） |
| `.tools/{go,gocache,gopath}/` | `var/toolchains/{go,gocache,gopath}/` |
| `.cache/` | `var/cache/` |
| `papercast-server/data/{runs,uploads,logs,pids}/` | `var/{runs,uploads,logs,pids}/` |
| `papercast-server/samples/` | `var/samples/` |
| `paper-dissemination-agents-landscape.md` | `docs/research/paper-dissemination-agents-landscape.md` |
| `papercast-server/docs/*` | 原地不动（组件文档跟随组件） |
| `.tools/xhs-test-post.png` | `docs/evidence/xhs-test-post.png` |

### 删除

| 对象 | 理由 |
| --- | --- |
| `paper-share-skills/`（根） | 与 `reference/upstream/paper-share-skills/` 内容一致，且无任何代码引用它；上游 clone 仍在 |
| `.tools/{one.txt,f.json,server.log}` | 小红书接口联调残留（`f.json` 含一条测试笔记的 `xsecToken`） |
| `papercast-server/:memory:.ses` | 51 字节的会话残留文件 |
| `example-papers/` | 当时是空目录（迁移过程中被并发轨道放入了 `deeprare.pdf`，故**保留未删**，见第 5 节） |

## 3. 为迁移改过的文件

| 文件 | 改动 |
| --- | --- |
| `apps/papercast-server/app/config.py` | 默认 `data_dir`/`upload_dir` 由组件内 `data/` 改为工作区 `var/`（保留单跑退路） |
| `ops/start_all.sh`、`ops/stop_all.sh` | 重写为自推导工作区根，指向 `apps/`、`ops/bin/`、`var/{logs,pids,runs,uploads,cache}` |
| `apps/papercast-server/scripts/run_dev.sh` | uv 缓存路径 → `var/cache/uv` |
| 22 个文件（组件文档、README、`ops/shot/*`、`ops/skillsearch/*`、`docs/00-goal…`） | 批量改写硬编码 `/home/yydh/hack/...` 旧路径 |
| `apps/papercast/src/views/SettingsView.vue`、`apps/papercast/README.md`、`apps/papercast-server/docs/02-module-generate.md`、`docs/00-goal-and-architecture.md` | 文案里的 `repos/` → `reference/upstream/` |
| **新增**：`README.md`、`AGENTS.md`、`.gitignore`、`docs/{README,conventions,migration-2026-09-19}.md`、`docs/research/upstream-repos.md`、`reference/README.md`、`ops/README.md`、`var/README.md`、`ops/build_mcp.sh` | — |

## 4. 迁移暴露的三个坑（都已修，值得记住）

### 4.1 Go 二进制被 `sed` 改坏（我造成的）

批量 `sed` 改写路径时通配命中了 `ops/bin/` 下三个 Go 二进制——Go 把源码路径编译进二进制，改写后字符串长度变化导致内部偏移错位，`xiaohongshu-mcp -h` 直接 core dump。

修复：源码本来就完好，用 `var/toolchains` 里的 Go 工具链重建（干净版从 `git archive HEAD` 导出到 `var/build/` 构建），并把过程固化成 `ops/build_mcp.sh`（顺带补上了此前完全没记录的编译方法）。

### 4.2 venv 不能整体搬目录

`apps/papercast-server/.venv/bin/*` 的 shebang 与 `activate*` 脚本里写的是绝对路径，`mv` 之后 18 个文件仍指向 `papercast-server/.venv`，启动报 `env: '.../uvicorn': No such file or directory`（文件其实存在，是解释器路径失效）。

修复：把 18 个文本文件里的旧前缀改成新前缀（不要碰 venv 里的二进制）。

### 4.3 小红书 MCP 的 cookie 认 cwd

MCP 的 cookie 是**相对当前目录**的 `cookies.json`（`apps/xiaohongshu-mcp/cookies/cookies.go`），迁移后从工作区根启动，它在根目录新建了一个空 `cookies.json`，`login/status` 变成 `is_logged_in: false`（账号 momo 的登录态其实一直在组件目录里）。

修复：`ops/start_all.sh` 的 MCP 分支改为先 `cd apps/xiaohongshu-mcp/` 再起进程；登录态恢复。

**教训（已写进 `AGENTS.md` 与 `ops/README.md`）：永远不要对二进制跑 `sed`；有状态服务要按组件目录启动。**

## 5. 未归位：并发中的知乎轨道

迁移时另一条会话正在开发知乎发布轨道，其目录**原样保留在根目录**（动了会打断它），已列入 `.gitignore`：
`zhihu-official/`、`p2b/`、`.p2b/`、`.home-zhihu/`、`.venv-zhihu/`、`.conda-pkgs/`、`.tectonic-cache/`、`example-papers/`。
归位目标见 `conventions.md` 第 9 节。

## 6. 影响与回滚

**影响**：所有引用旧绝对路径的**工作区外**脚本（如果存在）会失效；工作区内的引用已全部改写（自检命令见 `conventions.md` 第 10 节）。

**回滚**：迁移只用了 `mv`（同盘瞬时），对照表是双向的——把第 2 节右列 `mv` 回左列即可；文件内容改动集中在第 3 节列出的文件，`git log` 可回溯（根仓库首次提交即本次整理后的状态）。
