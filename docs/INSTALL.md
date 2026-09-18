# 安装与运行

从一台干净的机器到「前端能打开、能上传 PDF、能过闸门」的最短路径。所有命令都在**仓库根目录**执行。

---

## 0. 系统要求

| | 要求 | 说明 |
| --- | --- | --- |
| Python | **≥ 3.11**（推荐 3.13；实跑环境 3.13.12） | 后端与两个发布通道服务 |
| Node.js | **≥ 20**（含 npm ≥ 10） | 前端构建与开发服务器 |
| 磁盘 | ≥ 2 GB | 后端依赖（含 onnxruntime）约 300 MB、`node_modules` 约 200 MB、`reference/upstream/` 约 400 MB（可跳过） |
| 网络 | 可访问 PyPI / npm | 只影响首次安装；运行时只有 LLM 与平台接口需要外网 |

建议顺手装的系统包（缺了不阻断安装，只影响个别路径）：

```bash
sudo apt install -y curl iproute2 jq fontconfig fonts-noto-cjk
#                  │     │        │  │          └─ 卡片图上的中文（不装会变方块）
#                  │     │        │  └─ 让后端问系统「哪些字体支持中文」（探测第 2 优先级）
#                  │     │        └─ scripts/smoke_test.sh 用它解析 JSON
#                  │     └─ start_all.sh 用 ss 判端口占用
#                  └─ start_all.sh 用 curl 探活
```

**不需要**：Go（除非你要自己编小红书 MCP，见 §5.3）、Tesseract、TeX、ImageMagick —— 这些只对应可选路径。
`ffmpeg` / `edge-tts` 只在 `video` 阶段用（见 §4.3）：不装则该阶段如实报 fail，其余阶段照常。

## 1. 三条命令（最小可用）

```bash
git clone <仓库地址> && cd <仓库目录>
./ops/install.sh          # 后端 venv + 前端依赖 + 上游只读克隆
./ops/start_all.sh        # 起后端 :8000 与前端 :5178
```

装完打开 <http://127.0.0.1:5178>。想先填配置：`vi apps/papercast-server/.env`（脚本已从 `.env.example` 生成）。

`install.sh` 幂等且非破坏性：已存在的 venv / `node_modules` / 上游克隆一律跳过，不覆盖、不删除；
它只写 `var/` 与依赖目录，不碰你的代码和 git 状态。pip 与 npm 的缓存也落在 `var/cache/`（工作区自包含，也不会因为家目录缓存不可写而失败）。

## 2. 装到哪一档

| 档位 | 命令 | 装了什么 | 适合 |
| --- | --- | --- | --- |
| 最小 | `./ops/install.sh` | 后端 + 前端 + 上游参考 | 只想跑「PDF → 文章 → 卡片」主链路 |
| 全部 | `./ops/install.sh --all` | 再加知乎、B站、小红书 MCP（要 Go）、截图工具 | 要真实投递，机器也齐 |
| 单加 | `--with-zhihu` / `--with-bilibili` / `--with-mcp` / `--with-shot` | 分别对应上面几项 | 只缺一样 |

其他开关：`--skip-upstream`（不克隆 28 个上游参考，省几百 MB）、`--skip-frontend`（只装后端）、
`--no-lock`（用 `requirements.txt` 的下限而不是 `requirements.lock.txt` 的精确锁版）。

Python 依赖有两份清单：

- `apps/papercast-server/requirements.txt`：直接依赖 + 版本下限（跟着走新版本）；
- `apps/papercast-server/requirements.lock.txt`：**实跑环境的全量精确锁版**（38 个包），安装脚本默认用它；
  知乎通道另有一份 `apps/zhihu-publisher/requirements.lock.txt`（77 个包）。

## 3. 手工安装（不用脚本）

```bash
# 后端
python3 -m venv apps/papercast-server/.venv
apps/papercast-server/.venv/bin/pip install -r apps/papercast-server/requirements.lock.txt

# 前端
npm --prefix apps/papercast ci

# 上游只读参考（按 docs/research/upstream-repos.md 登记的 commit 固定，缺哪个补哪个）
./ops/sync_upstream.sh --list    # 只核对，不动文件
./ops/sync_upstream.sh           # 补齐缺失的

# 配置与目录
cp apps/papercast-server/.env.example apps/papercast-server/.env
mkdir -p var/{runs,uploads,logs,pids,samples,cache,artifacts,secrets,scratch}
```

## 4. 可选依赖（按需要装）

### 4.1 发布通道

| 依赖 | 什么时候需要 | 没装会怎样 | 安装 |
| --- | --- | --- | --- |
| **Go ≥ 1.24** | 编译小红书 MCP（二进制不入库） | 小红书通道 `offline`（后端启动时会如实说明缺二进制） | `./ops/install.sh --with-mcp`；工具链见 §5.3 |
| **biliup**（必须 1.x，锁 1.2.4） | B站通道投递 | 服务照常起，如实报 `unconfigured`，素材包照常导出 | `./ops/install.sh --with-bilibili` |
| **Playwright chromium** | 知乎 Playwright 通道 | 知乎报 `login_required` 或失败；核心链路不受影响 | `./ops/install.sh --with-zhihu` |
| `reference/upstream/zhihu-mcp` | 知乎通道运行时真的 import 它 | 通道服务起不来 | `./ops/sync_upstream.sh` |
| `python-markdown` 或系统 `pandoc` | 只有走知乎官方 OpenAPI 那条路（markdown→HTML） | 那条路报错；Playwright 路不受影响 | `sudo apt install pandoc` |

### 4.2 解析与渲染

| 依赖 | 用在哪 | 没装会怎样 | 安装 |
| --- | --- | --- | --- |
| **CJK 中文字体** | 卡片图上的中文（核心产物之一） | 卡片文字变方块；文章仍正常产出（只记一条失败 check） | `sudo apt install fonts-noto-cjk`，或设 `PAPERCAST_CJK_FONT=` 指向已有字体 |
| `tesseract` + 中文包 | 扫描件 PDF 的 OCR | 明确报 `CONTENT_TOO_SHORT` 并提示需要 OCR（不静默） | `sudo apt install tesseract-ocr tesseract-ocr-chi-sim` |
| `mineru` + 可用 GPU | 想把解析引擎换成 mineru | 默认用 `pymupdf`；无 GPU 时显式回退并 warn | 见上游 mineru 文档 |
| **chrome-headless-shell / chromium** | 被 **poster 阶段**（在流水线里，缺了该阶段报 fail）与 `ops/shot/` 截图脚本用 | 卡片与长文**不受影响**（卡片是纯 PIL 画的，不用浏览器） | `./ops/install.sh --with-zhihu`（带 chromium），或系统 `chromium`，或用 `PAPERCAST_CHROME=` 指定 |
| `npm --prefix ops/shot install` | `ops/shot/*.mjs` 截图/渲染脚本 | 截图工具跑不了 | `./ops/install.sh --with-shot` |

### 4.3 视频链路（流水线 `video` 阶段 + 手工脚本）

| 依赖 | 用途 | 安装 |
| --- | --- | --- |
| `ffmpeg` + `ffprobe` | 逐页配音+帧合成、字幕烧入、concat | `sudo apt install ffmpeg`（也能放 `var/toolchains/p2b/bin`，脚本会回落找） |
| `edge-tts` | 配音（TTS） | `pip install edge-tts` |
| `tectonic` + `poppler`（+`poppler-data`） | 上游 Beamer 编译与 PDF 出帧 | 上游官方安装脚本；poppler 走 conda-forge（见 `docs/research/paper-share-skills-run-notes.md`） |
| Microsoft YaHei 字体 | `ops/make_portrait_video.py` 里**硬编码**的字体族 | 装 `msyh.ttc` 到 `~/.local/share/fonts` 后 `fc-cache -f`，或改那个常量 |

### 4.4 明确**不需要**的

- **LaTeX（`pdflatex`/`xelatex`/`latexmk`）**：后端只在 `/api/env` 里 `which` 一下上报状态，**仓库里没有任何编译调用点**；
  `.tex` 输入永远走源码解析（`app/intake/latex_parser.py` 写死 `engine: latex-source`）。装了不会更快也不会更好。
- **ImageMagick**：仓库里没有任何 `convert`/`magick` 命令调用（只有 PIL 的 `Image.convert()` 方法）。

## 5. 三个不在仓库里的东西

### 5.1 上游只读参考：`reference/upstream/`（28 个仓库，未入库）

`.gitignore` 故意忽略了它们（每个都带自己的 `.git`）。按登记表复现：

```bash
./ops/sync_upstream.sh --list   # 核对本地 HEAD 与 docs/research/upstream-repos.md 的登记 commit
./ops/sync_upstream.sh          # 取回缺失的（固定 commit，不跟随默认分支）
```

只有**知乎通道**在运行时真的需要其中之一（`reference/upstream/zhihu-mcp`）；其余是只读参考，缺了不影响跑。

### 5.2 二进制：`ops/bin/`（**故意不入库**）

小红书 MCP 的三个 Linux 二进制与两个 Windows `.exe` 共约 95 MB，**不进 git**。要用就自己编（约 1 分钟）：

```bash
./ops/install.sh --with-mcp    # clone 上游源码 + 切到登记 commit + 打本地补丁 + 编译
```

不编也没关系：`./ops/start_all.sh` 的 backend / frontend 照常起，只有小红书通道会明确报 `offline`。

### 5.3 小红书 MCP 的源码：`apps/xiaohongshu-mcp/`（独立 git 仓库，未入库）

它同时是**运行时的工作目录** —— cookie 是相对进程 cwd 的 `cookies.json`（`cookies/cookies.go`），
所以 `start_all.sh` 会先 `cd` 进去再起进程。`--with-mcp` 会替你 clone + 打补丁，手工做等价于：

```bash
git clone https://github.com/xpzouying/xiaohongshu-mcp apps/xiaohongshu-mcp
git -C apps/xiaohongshu-mcp checkout $(cat docs/patches/xhs-mcp-local-2026-09-19/base-commit.txt)
git -C apps/xiaohongshu-mcp apply ../../docs/patches/xhs-mcp-local-2026-09-19/tracked.diff

# Go 工具链：装系统 Go（https://go.dev/dl/，>= 1.24）即可，脚本会自动开 GOPROXY；
# 或用离线工具链：把 go 解压到 var/toolchains/go（脚本会自动 GOPROXY=off）
./ops/build_mcp.sh
```

补丁内容与原因见 `docs/patches/xhs-mcp-local-2026-09-19/`。MCP 首次运行还会自己下载一个内置 Chromium（约 150 MB）到 `var/cache/xiaohongshu-mcp/browser/`；
Windows 侧部署见 `ops/deploy_mcp_windows.sh`。**不要改 `reference/upstream/` 里的代码**（规范 §7），也不要用 `sed` 扫 `ops/bin/` 里的二进制。

## 6. 凭证：需要你本人做的事

| 东西 | 放哪 | 怎么来 |
| --- | --- | --- |
| LLM 密钥 | `apps/papercast-server/.env` 的 `LLM_API_KEY` | 任何 OpenAI 兼容端点（默认 `https://opencode.ai/zen/go/v1`）；留空时会尝试读 `~/.dsh/.credentials.yaml` 的 `GO_API_KEY`。**不填则 understand/article 阶段直接失败**（`LLM_NOT_CONFIGURED`） |
| 小红书登录态 | `apps/xiaohongshu-mcp/cookies.json` + `var/cache/xiaohongshu-mcp/browser/` | 前端「平台账号」页扫码，或 `./ops/bin/xiaohongshu-login` |
| 知乎登录态 | `var/secrets/zhihu/cookies.json` | 桌面窗口人工登录（风控拦纯 HTTP 扫码）：`./ops/start_all.sh zhihu` → 前端点「打开浏览器登录」 |
| 知乎官方 OpenAPI 密钥 | `ZHIHU_OPENAPI_APP_KEY` / `ZHIHU_OPENAPI_APP_SECRET` | 到知乎开放平台申请（内测审核） |
| B站登录态 | `var/home/.bilibili/cookies.json`（biliup 自管） | `./ops/start_all.sh bilibili` → 前端扫码，或 `ops/biliup_login_pty.py` |
| 文生图（可选） | `DASHSCOPE_API_KEY`（放 `var/secrets/imagegen.env`） | `ops/imagegen.sh` 用，缺了只影响文生图 |

**这些一律不入库**（`.gitignore` 已覆盖 `var/`、`cookies.json`、`.env`），也永远不要贴进 issue/日志。
规则见 `docs/conventions.md` §5、`var/secrets/README.md`。

联网端点清单（谁申请、没有时的确切行为）见 `docs/08-channels.md` 与各组件 README。

## 7. 装完怎么确认没问题

```bash
# 1) 渠道层自检（不联网、不投递、不写真实 var/ 数据）
apps/papercast-server/.venv/bin/python apps/papercast-server/scripts/check_channels.py
#    期望：0 失败（全新环境 24 项；工作区里已有真实 run 时 25 项——多出的那条在核验真实投递回执）

# 2) 服务存活
./ops/start_all.sh && curl -s http://127.0.0.1:8000/api/health

# 3) 各通道真实状态（没装的会如实报 offline / unconfigured / login_required）
curl -s http://127.0.0.1:8000/api/channels

# 4) 前端类型检查
cd apps/papercast && npx vue-tsc --noEmit
```

## 8. 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 端口被占，`start_all.sh` 说跳过 | 幂等设计：只在端口空闲时启动。先 `./ops/stop_all.sh` 或用 `ss -ltn` 看谁占着 |
| `start_all.sh` 报小红书 MCP「启动失败」 | 两个可能：① 没编二进制 → `./ops/install.sh --with-mcp`；② `apps/xiaohongshu-mcp/` 目录不在（那是它的工作目录，cookie 相对 cwd）→ `./ops/install.sh --with-mcp`。backend/frontend 不受影响 |
| 知乎点登录返回 409 `NO_DISPLAY` | 本机没有可见显示（无头服务器/容器）：需要有桌面的终端，或用 `apps/zhihu-publisher/scripts/login-headed.sh` |
| 卡片上的中文是方块 | 缺中文字体：`sudo apt install fonts-noto-cjk`，或设 `PAPERCAST_CJK_FONT=/path/to/font.ttc` |
| 海报渲染 / 截图提示找不到浏览器 | 装 chromium（`--with-zhihu` 带一个）或设 `PAPERCAST_CHROME=`；截图脚本还可用 `SHOT_CHROME=` |
| 通道显示 `offline`（连不上 127.0.0.1:180xx） | 那个通道服务没起：`./ops/start_all.sh zhihu` / `bilibili` / `mcp` |
| 通道显示 `login_required` / `unconfigured` | 如实上报，不是 bug：按 §6 登录，或按 §4 装依赖 |
| 服务启动报错 | 看 `var/logs/<服务>.log`；小红书 MCP 必须在自己的组件目录里启动，`start_all.sh` 已处理 |
| 装的代理让本地服务连不上 | 通道一律 `trust_env=False`，本机服务不走代理；日志里出现 proxy 报错就查 `http_proxy` |
| 视频脚本报 `Microsoft YaHei` 找不到 / `ffprobe` 找不到 | 见 §11「已知的坑」第 2、3 条 |

## 9. 运行数据都在 `var/`（整个目录不入库）

产出、日志、缓存、凭证、工具链全在 `var/` 下，删掉整个目录只会丢历史运行记录。
目录职责与清理建议见 `var/README.md` 与 `docs/conventions.md` §4。最该珍惜的是：
`var/secrets/`（凭证）、`var/home/.bilibili/`、`var/cache/xiaohongshu-mcp/browser/`（登录态）、`var/runs/`（历史产出）。

## 10. 推到 GitHub 之前

**① 许可**：仓库是 MIT（`LICENSE`）。`reference/upstream/` 里的 28 个上游各有自己的许可证，它们不入库，
只以只读克隆存在（登记表 `docs/research/upstream-repos.md` 里逐条记了来源与许可证）。

**② 体积**：`ops/bin/` 的二进制与 `apps/xiaohongshu-mcp/` 源码都已排除，仓库本体约 50 MB（比早先少了约 95 MB 的二进制），
`git clone` 下来很快。历史里如果曾经提交过二进制，`git log --stat -- ops/bin` 能看到；在意体积就用 `git filter-repo` 清历史。

**③ 凭证别推上去**（推之前跑一遍）：

```bash
git ls-files | grep -E "cookie|\.env$|secret|\.venv|node_modules" || echo 干净
git grep -nIE "SESSDATA|z_c0=|sk-[A-Za-z0-9]{20,}" $(git rev-list --all | head -50) || echo 历史里没有凭证
```

**④ 推**：

```bash
git remote add origin git@github.com:yydhYYDH/PaperCast.git   # 本仓库当前的 origin
git push -u origin main
```

推之前先 `git fetch` 看有没有别人的提交；落后就 `merge` 回本地再推，**不要 `--force`**（本工作区常有多会话并行）。

**⑤ CI**：仓库自带 `.github/workflows/ci.yml`，push 会跑后端渠道层自检（`scripts/check_channels.py`，不联网不投递）与前端 `vue-tsc`。

## 11. 已知的坑（审计实读代码后记下来的，尚未修）

| # | 现象 | 位置 | 影响 |
| --- | --- | --- | --- |
| 1 | `LaTeX` 装了也没用：`/api/env` 宣告 `mode: compile`，但没有编译调用点 | `app/main.py:184,207` vs `app/intake/latex_parser.py:254-258` | 只影响预期，不影响跑 |
| 2 | 视频脚本字体族硬编码 `Microsoft YaHei`，缺字体直接 `SystemExit`，且没有环境变量可覆盖 | `ops/make_portrait_video.py:41,76` | 手工视频链路 |
| 3 | `make_run_video_artifacts.py` 用裸 `ffprobe`（只查 PATH，不像同目录脚本有 `resolve_tool` 回落） | `ops/make_run_video_artifacts.py:84` | 手工视频链路 |
| 4 | `ops/shot/` 的 npm 依赖不在最小安装里 | `ops/install.sh`（`--with-shot` 才装） | 截图/海报 |
| 5 | ~~poster / video 阶段不在流水线里跑~~ —— **已修**（2026-09-19）：`models.py` 的 `IMPLEMENTED_STAGES` 已含 6 段、`SKIPPED_STAGES` 为空，poster 与 video 都随流水线跑 | `app/models.py:18-22` | —（保留此行仅为记录曾有的误解） |
