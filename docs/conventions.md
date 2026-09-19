# 工作区规范（目录 · 路径 · 命名 · 密钥）

> 适用对象：`/home/yydh/hack` 下的所有内容。
> 版本：R1 · 2026-09-19 · 由 2026-09-19 的目录迁移引入（对照表见 `docs/migration-2026-09-19.md`）。
> 目标：**任何人在 30 秒内知道一个文件该放哪里、一段代码该怎么引用路径、什么东西绝不能进版本库。**

---

## 1. 五层结构

```text
hack/
├── README.md            工作区入口：是什么、怎么跑（唯一允许的说明入口）
├── AGENTS.md            给 AI/协作者的速查规则
├── .gitignore           忽略规则（运行态、依赖、密钥、上游克隆）
├── LICENSE              MIT 许可（GitHub 公开发布需要）
├── docs/                文档：总纲、规范、调研、证据、补丁
│   ├── 00-goal-and-architecture.md    跨子项目总纲
│   ├── conventions.md                 本文件
│   ├── migration-*.md                 目录迁移记录
│   ├── research/                      调研结论与上游清单
│   ├── evidence/                      验收证据（截图、回执）
│   └── patches/                       上游/本地改动的补丁留档
├── apps/                我们自己的代码（可运行、要维护）
│   ├── papercast/           前端
│   ├── papercast-server/    后端
│   └── xiaohongshu-mcp/     小红书渠道适配器（独立 git 仓库）
├── reference/           别人的代码（只读，可删可重克隆）
│   ├── upstream/            上游参考实现
│   └── baoyu-research/      出图后端调研
├── ops/                 跨组件的脚本与本地工具
│   ├── start_all.sh / stop_all.sh / build_mcp.sh
│   ├── shot/                HTML→PNG 渲染
│   ├── bin/                 本地编译的二进制（由 build_mcp.sh 生成）
│   └── skillsearch/         上游技能调研脚本
└── var/                 运行态（可删、可重建、不入库）
    ├── runs/ uploads/ logs/ pids/ samples/
    ├── cache/               缓存（npm / uv / conda / fontconfig / 浏览器登录态 …）
    └── toolchains/          Go 工具链与模块缓存
```

### 放置决策（新东西该去哪）

| 问题 | 答案 |
| --- | --- |
| 是我们写的、要长期维护的运行代码吗？ | `apps/<组件>/` |
| 是别人的仓库，只是拿来读？ | `reference/upstream/<name>/` + 登记到 `docs/research/upstream-repos.md` |
| 是跑出来的数据、缓存、日志、venv、模型、工具链？ | `var/` |
| 是跨组件的脚本或本地编译的二进制？ | `ops/` |
| 是结论、方案、验收证据？ | `docs/`（不是代码注释里） |
| 是上游/本地的一次性改动留档？ | `docs/patches/<主题>-<日期>/` |
| 以上都不是，只是临时试一下？ | 放 `var/scratch/`，并在 24 小时内处理掉 |

**根目录只允许 `README.md`、`AGENTS.md`、`.gitignore`、`LICENSE` 四个文件**（迁移期例外见第 9 节）。

---

## 2. 命名规范

| 对象 | 规则 | 例子 |
| --- | --- | --- |
| 组件目录 | 小写连字符，产品名或角色名 | `papercast-server`、`xiaohongshu-mcp` |
| 文档 | 全局文档 `NN-topic.md`（两位序号）；组件内文档放 `docs/` 下同名规则 | `00-goal-and-architecture.md` |
| 迁移/决策记录 | kebab + 日期 | `migration-2026-09-19.md` |
| 脚本 | 动词开头，`_` 分隔 | `start_all.sh`、`build_mcp.sh` |
| 运行数据 | 与代码里生成的 id 一致，不自造 | `run_87aeca6d7d33/`、`up_e543faed5be4/` |
| 补丁留档 | `docs/patches/<主题>-<日期>/` 下放 diff + status + 基线 commit | `docs/patches/xhs-mcp-local-2026-09-19/` |

---

## 3. 路径规范（最重要的一条）

### 3.1 不写死 `/home/yydh/hack`

Shell 脚本统一自推导工作区根：

```bash
WS="$(cd "$(dirname "$0")/.." && pwd)"     # ops/ 下的脚本
ROOT="$(cd "$(dirname "$0")/.." && pwd)"   # apps/<组件>/scripts/ 下的脚本
```

Python/TypeScript 由「自身文件位置」或环境变量推导，禁止出现绝对路径字面量：

```python
ROOT = Path(__file__).resolve().parent.parent          # apps/papercast-server/
_WORKSPACE = ROOT.parent.parent                        # 工作区根
VAR_DIR = _WORKSPACE / "var" if (_WORKSPACE / "apps").is_dir() else ROOT / "data"
```

> 这样单跑组件（没有 `apps/` 那一层）时会退回组件内的 `data/`，放进工作区时又落到 `var/`。

### 3.2 运行期位置由环境变量注入

| 环境变量 | 值（由 `ops/start_all.sh` 注入） | 用途 |
| --- | --- | --- |
| `PAPERCAST_DATA_DIR` | `<ws>/var/runs` | 每次运行的 `run.json` 与产物 |
| `PAPERCAST_UPLOAD_DIR` | `<ws>/var/uploads` | 上传的 PDF/LaTeX |
| `XDG_CACHE_HOME` | `<ws>/var/cache` | 小红书浏览器登录态、fontconfig、tectonic 等 |
| `UV_CACHE_DIR` | `<ws>/var/cache/uv` | uv 的包缓存（沙箱下 `~/.cache` 可能只读） |
| `GOROOT` / `GOPATH` / `GOCACHE` | `<ws>/var/toolchains/{go,gopath,gocache}` | 重建 Go 二进制时用 |

### 3.3 端口约定（不要改，脚本与文档都假设它）

| 端口 | 服务 |
| --- | --- |
| 8000 | 后端 API（`apps/papercast-server`，契约见其 `docs/04-api-contract.md`） |
| 5178 | 前端 dev（`apps/papercast`；preview 用 4178） |
| 18060 | 小红书 MCP（`ops/bin/xiaohongshu-mcp`） |
| 18070 | 知乎发布通道（`apps/zhihu-publisher`） |
| 18080 | B站发布通道（`apps/bilibili-publisher`，底层 biliup CLI） |

### 3.4 文档里引用路径

- 组件内部互相引用用相对路径（`../papercast/README.md` 会随目录移动而失效，**避免跨组件的相对路径**）；
- 跨组件引用写「工作区根相对路径」并加代码块，例如 ``apps/papercast-server/docs/04-api-contract.md``；
- 文档里出现绝对路径只允许一种情况：给运维复制的 systemd/nginx 片段，且必须与 `apps/papercast-server/docs/05-deployment.md` 保持同步。

### 3.5 进程工作目录（cwd）也是一条路径约定

有状态的本机服务**必须在自己的组件目录里启动**，因为相对路径是按 cwd 解析的：

| 服务 | 启动目录 | 原因 |
| --- | --- | --- |
| 小红书 MCP | `apps/xiaohongshu-mcp/` | cookie 文件是 cwd 下的 `cookies.json`（`cookies/cookies.go`）；cwd 不对就掉登录 |
| 后端 | 任意（推荐工作区根） | 数据目录由 `PAPERCAST_DATA_DIR` 注入，`.env` 按模块自身位置解析 |
| 前端 | `apps/papercast/`（`npm --prefix` 会切） | vite 配置与 `public/` 相对项目根解析 |

统一入口 `ops/start_all.sh` 已经处理这些目录切换；**手工起服务时，记得先 `cd` 到对应组件目录**。

---

## 4. `var/` 运行态规范

| 子目录 | 内容 | 删掉的后果 |
| --- | --- | --- |
| `var/runs/<runId>/` | **产出主目录**：`run.json` + 各阶段产物（intake/understand/article/publish）+ `publish/<渠道>/export/`、`receipt.json` | 历史运行不可复现，验收证据丢失 |
| `var/uploads/<uploadId>/` | 上传的原始论文 | 已建 run 会缺源文件 |
| `var/logs/` | 各服务日志（backend / frontend / mcp / zhihu / bilibili / 登录 pty 日志） | 无 |
| `var/secrets/` | **凭证**：`zhihu/cookies.json`、`bilibili/cookies.json`（均 chmod 600） | 要重新登录 |
| `var/artifacts/<平台>/` | **只放投递中转**：`export/<runId>/`、登录二维码截图、下载日志；**不放凭证** | 重跑发布阶段即可 |
| `var/home/` | HOME 重定向目录（`zhihu-home`、biliup 自管的 `.bilibili/`） | 第三方 CLI 的凭证/缓存丢失，要重登录 |
| `var/pids/` | `*.pid`，`stop_all.sh` 据此停服务 | 只能用端口/进程名手动清 |
| `var/samples/` | 固定样例（`paper2video.pdf`、`papercast-lab/`） | 冒烟脚本要重新准备样例 |
| `var/cache/` | 包缓存、浏览器登录态、fontconfig、tectonic | **`var/cache/xiaohongshu-mcp/browser` 删掉就要重新扫码登录** |
| `var/toolchains/` | Go 工具链、`bili-venv`（biliup）、`zhihu-*-venv`、`p2b`（TeX/conda） | 重建成本高，且要重新联网 |
| `var/interactions/` | **互动草稿**：`drafts.jsonl`（P1 起草的回复草稿，一行一条，`sent` 恒为 false —— 发没发看这个字段）。只落盘、不发送，见 `docs/10-ops-and-theme.md` §13 | 丢了起草记录（要重读一次评论）；不影响任何已发布内容 |
| `var/scratch/` | 一次性探索产物：临时截图、调试输出、临时数据 | 无 |
| `var/tmp/` · `var/build/` · `var/npm-tmp/` | 脚本临时文件、`build_mcp.sh` 的编译工作区、npm 临时目录 | 无（可随时清） |

规则：
1. `var/` 整体不入库（`.gitignore` 已忽略），可在需要时整体删除重建；
2. **产出去哪**：凡是要在 dashboard 里预览/下载的，一律写进 `var/runs/<runId>/<stage>/`
   —— 后端只把这里挂到 `/artifacts/<runId>/<stage>/<rel>`，写到别处就是 404；
3. **权威副本只有一份**：run 内 `publish/<渠道>/export/` 是权威；`var/artifacts/<平台>/export/<runId>/`
   是通道服务自留的中转目录，可随时删，不参与验收；
4. **凭证不进 `var/artifacts/`**：统一放 `var/secrets/`（见 §5）；第三方工具自管凭证位置的
   （biliup 的 `$HOME/.bilibili/`、小红书 MCP 的 cwd `cookies.json`）不必搬，用 `HOME`/cwd 重定向
   把它圈进 `var/` 或组件目录即可，**不要复制第二份**；
5. 唯一“贵重”的是凭证/登录态（`var/secrets/`、`var/home/`、`var/cache/xiaohongshu-mcp/browser`）与 `var/runs/`；
6. 清理时用 ``du -sh var/* | sort -h`` 先看体积，别 `rm -rf var` 一把梭。

---

## 5. 密钥与账号规范

| 东西 | 位置 | 规则 |
| --- | --- | --- |
| 小红书 cookie | `apps/xiaohongshu-mcp/cookies.json`、`var/cache/xiaohongshu-mcp/browser/` | 已在 `.gitignore`/上游 `.gitignore` 覆盖，**永不入库、永不外传**；位置由 MCP 按 cwd 决定，不要搬 |
| 知乎 cookie | `var/secrets/zhihu/cookies.json`（chmod 600） | 由 `zhihu-publisher` 写；2026-09-19 从 `var/artifacts/zhihu/` 迁出（服务仍兼容读旧路径） |
| B站 cookie | `var/home/.bilibili/cookies.json`（chmod 600） | biliup **自管**位置：用 `HOME=var/home` 圈进 `var/`，不复制第二份 |
| 后端本地配置 | `apps/papercast-server/.env` | 同上；只提交 `.env.example` |
| LLM 凭据 | `~/.dsh/.credentials.yaml`（工作区外） | 代码只读不写，不复制到工作区 |
| 调研过程中拿到的 token | 不许落在 `docs/` 或 `var/logs/` | 引用响应时先删 `xsecToken` 等字段 |

边界（与总纲 ADR 4 一致）：**重计算可以在远端，发布只能在本机**；账号凭证不出本机。

---

## 6. 文档规范

| 文档 | 归属 |
| --- | --- |
| 跨子项目总纲、规范、迁移记录、调研结论、验收证据 | `docs/` |
| 组件设计（模块划分、接口契约、部署） | `apps/<组件>/docs/` |
| 组件怎么跑起来（最小上手） | `apps/<组件>/README.md` |
| 上游仓库清单与版本 | `docs/research/upstream-repos.md` |

规则：新增文档必须挂到 `docs/README.md` 的索引表里；文档里的路径引用必须符合第 3 节。

---

## 7. 上游参考规范（`reference/`）

1. **只读**：不修改 `reference/upstream/` 下的任何文件（包括 `AGENTS.md`、测试）；
2. 克隆到 `reference/upstream/<repo-name>/`，并在 `docs/research/upstream-repos.md` 登记「来源 / HEAD / 日期 / 我们借用什么」；
3. 需要改上游代码时：复制成 `apps/` 下的组件（如 `apps/xiaohongshu-mcp`，保留自己的 `.git` 与本地分支），改动留补丁到 `docs/patches/`；
4. 不使用 git submodule（上游是纯参考资料，不是构建依赖）；
5. 参考区可以随时删除重克隆，因此**任何必须保留的结论都要写进 `docs/research/`**，不要只留在上游仓库的 README 里。

---

## 8. 脚本规范

| 类型 | 位置 | 例子 |
| --- | --- | --- |
| 跨组件（起停全部服务、重建产物、跨目录流水线） | `ops/` | `start_all.sh`、`stop_all.sh`、`build_mcp.sh` |
| 单组件（只服务一个组件，跟着组件的生命周期走） | `apps/<组件>/scripts/` | `run_dev.sh`、`smoke_test.sh` |

要求：`set -euo pipefail`；顶部注释写清用法；幂等（端口占用就跳过，不要重复起）；不写死绝对路径；不打印 cookie/token。

---

## 9. 根目录收口（已完成，2026-09-19）

迁移期为了不打断并发中的知乎/B站轨道，根目录曾留 8 个例外目录；**现在归零**，根目录只剩
`README.md` / `AGENTS.md` / `.gitignore` / `LICENSE` 四个文件（`LICENSE` 是 09-19 可发布化时新增的
标准元文件，不是目录例外），加上 `.dsh/` 这**一个长期目录**（DSH 技能发现根，见下表末行）。

全量对照：

| 原路径 | 现在 | 备注 |
| --- | --- | --- |
| `zhihu-official/` | `apps/zhihu-publisher/scripts/`（脚本）+ `apps/zhihu-publisher/docs/zhihu-official-notes.md`（笔记） | 归位时同步改了 `ZHIHU_LOGIN_SCRIPT` 默认值、`login-headed.sh` 的 `WS` 推导深度（`../../..`）、以及三条提示文案 |
| `zhihu-official/sample-article.md` | `var/samples/zhihu-sample-article.md` | 测试稿属输入样例 |
| `zhihu-official/.zhihu-publish-output/` | `var/artifacts/zhihu/publish-output/` | 原来是 **cwd 相对**的隐藏产物目录（换目录就找不到），现在由 `publish.py` 按 `PAPERCAST_WS` 推导 |
| `example-papers/deeprare.pdf` | `var/samples/deeprare.pdf` | 输入样例 |
| `.p2b/`、`p2b/` | `var/toolchains/p2b/` | TeX/conda 工具链 |
| `.venv-zhihu/`、`.home-zhihu/` | `var/toolchains/zhihu-cli-venv/`、`var/home/zhihu-home/` | venv 的 shebang 是绝对路径，**只能重建不能 mv** |
| `.conda-pkgs/`、`.tectonic-cache/` | `var/cache/{conda-pkgs,tectonic}/` | 包缓存 |
| `biliup` 相关 | `var/toolchains/bili-venv/`、`var/home/.bilibili/` | B站轨道新增：biliup venv + 凭证（HOME 重定向） |
| —（09-19 新增，**保留在根目录**） | `.dsh/skills/<name>/SKILL.md` | DSH 的技能发现根（优先级最高）。只放技能包，不放代码/数据；**要跟代码一起提交，不许加进 `.gitignore`**；这不是临时例外，是长期约定。仓库自己的前端规范就是 `papercast-frontend`，第三方设计技能仍由 `ops/install_skills.sh` 装到 `~/.agents/skills` |

**下次往根目录放东西前**：先想清楚它属于哪一层；真要开例外，必须在 §9 加一行 + 在 `.gitignore` 加一条，
并在标题里写明**打算什么时候收口**。

这些都已在 `.gitignore` 里。归位时**不要直接 `mv` venv/conda 目录**：先看清楚里面有没有写死的绝对路径（venv 的 `bin/*` shebang、conda 的 `prefix`），必要时重建而不是搬移。

---

## 10. 自检清单

```bash
cd <工作区根>                            # 例：cd ~/hack
ls -la                                  # 根目录只有 4 个元文件（README.md/AGENTS.md/.gitignore/LICENSE）+ 5 个目录 + .dsh/（技能根，已提交）
grep -rn 'hack/\.tools\|hack/\.cache\|hack/repos' apps ops docs   # 应为空：旧路径已改完
grep -rniE 'secret|token=cookie' docs                              # 应无明文凭据
du -sh var/* | sort -h                  # 运行态体积
./ops/start_all.sh && curl -s http://127.0.0.1:8000/api/health && ./ops/stop_all.sh
```
