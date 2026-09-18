# 安装与运行

从一台干净的机器到「前端能打开、能上传 PDF、能过闸门」的最短路径。所有命令都在**仓库根目录**执行。

---

## 0. 系统要求

| | 要求 | 说明 |
| --- | --- | --- |
| Python | **≥ 3.11**（推荐 3.13） | 后端与两个发布通道服务 |
| Node.js | **≥ 20**（含 npm） | 前端构建与开发服务器 |
| 磁盘 | ≥ 2 GB | 后端依赖（含 onnxruntime）约 300 MB，`node_modules` 约 200 MB，`reference/upstream/` 按需 |
| 网络 | 可访问 PyPI / npm / GitHub | 只影响首次安装；运行时只有 LLM 与平台接口需要外网 |

**不需要**：Go（发布二进制已随仓库提供）、Tesseract、TeX。这些只对应可选路径，见第 4 节。

## 1. 三条命令（最小可用）

```bash
git clone <仓库地址> && cd <仓库目录>
./ops/install.sh          # 后端 venv + 前端依赖 + 上游只读克隆
./ops/start_all.sh        # 起后端 :8000 与前端 :5178
```

装完打开 <http://127.0.0.1:5178>。想先填配置：`vi apps/papercast-server/.env`（脚本已从 `.env.example` 生成）。

`install.sh` 是幂等的、非破坏性的：已存在的 venv / `node_modules` / 上游克隆一律跳过，不会覆盖或删除任何东西；
它只写 `var/` 与依赖目录，不碰你的代码和 git 状态。

## 2. 三档安装

| 档位 | 命令 | 装了什么 | 适合 |
| --- | --- | --- | --- |
| 最小 | `./ops/install.sh` | 后端 + 前端 + 上游参考 | 只想跑「PDF → 文章 → 卡片」主链路 |
| 加通道 | `./ops/install.sh --all` | 再加知乎（Playwright + chromium）与 B站（biliup） | 要真实投递 |
| 只要其一 | `--with-zhihu` / `--with-bilibili` | 分别对应上面两项 | 只投某个平台 |

其他开关：`--skip-upstream`（不克隆 24 个上游参考，省几百 MB）、`--skip-frontend`（只装后端）、
`--no-lock`（用 `requirements.txt` 的下限而不是 `requirements.lock.txt` 的精确锁版）。

Python 依赖有两份清单：

- `apps/papercast-server/requirements.txt`：直接依赖 + 版本下限（跟着走新版本）；
- `apps/papercast-server/requirements.lock.txt`：**实跑环境的全量精确锁版**（37 个包），安装脚本默认用它。
  知乎通道同样有一份 `apps/zhihu-publisher/requirements.lock.txt`（77 个包）。

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

## 4. 可选依赖（按阶段/通道装）

| 依赖 | 什么时候需要 | 没装会怎样 | 安装 |
| --- | --- | --- | --- |
| **chrome-headless-shell** | 图文卡片渲染（`PAPERCAST_CARDS=on`，默认开） | 卡片渲染不了，长文仍可用 | 装 Playwright 缓存即可：`./ops/install.sh --with-zhihu`（自带 chromium），或系统装 chromium；也可用 `PAPERCAST_CHROME=` 显式指定 |
| **CJK 字体** | 卡片上的中文 | 中文变方块 | `sudo apt install fonts-noto-cjk`（或设 `PAPERCAST_CJK_FONT=` 指向已有字体） |
| LaTeX（`pdflatex`/`xelatex`/`latexmk`） | 上传的是 `.tex`/arXiv 源码包 | 自动退化为源码解析并在 UI 标注「未编译」 | `sudo apt install texlive-xetex` |
| `tesseract` | 扫描件 PDF | 明确报 `CONTENT_TOO_SHORT` 并提示需要 OCR | `sudo apt install tesseract-ocr tesseract-ocr-chi-sim` |
| `mineru` | 想把解析引擎换成 mineru | 用默认 `pymupdf` 引擎 | 见上游 mineru 文档 |
| **biliup**（`biliup==1.2.4`） | B站通道投递 | 通道服务照常起，如实报 `unconfigured`，素材包照常导出 | `./ops/install.sh --with-bilibili` |
| **Playwright chromium** | 知乎 Playwright 通道、`ops/shot/` 截图 | 知乎报 `login_required`/失败；核心链路不受影响 | `./ops/install.sh --with-zhihu` |
| `edge-tts`、ImageMagick（`convert`） | 只有 `ops/make_short_video.py` 等**手工脚本**用 | 不影响服务与主链路 | `pip install edge-tts` + `sudo apt install imagemagick` |
| Go 工具链 | 只有要重编 `ops/bin/` 里的 MCP 二进制时才需要 | 用仓库自带二进制即可 | 见第 5 节 |

## 5. 两个不在仓库里的东西

### 5.1 上游只读参考：`reference/upstream/`（24 个仓库，未入库）

`.gitignore` 故意忽略了它们（每个都带自己的 `.git`）。按登记表复现：

```bash
./ops/sync_upstream.sh --list   # 核对本地 HEAD 与 docs/research/upstream-repos.md 的登记 commit
./ops/sync_upstream.sh          # 取回缺失的（固定 commit，不跟随默认分支）
```

只有**知乎通道**在运行时真的需要其中之一（`reference/upstream/zhihu-mcp`）；其余是只读参考，缺了不影响跑。

### 5.2 小红书 MCP：`apps/xiaohongshu-mcp/`（独立 git 仓库，未入库）

代码不在本仓库里（它是上游 `xpzouying/xiaohongshu-mcp` 的一个 clone + 本地 auth 补丁）。
**日常使用不需要它**：编译好的二进制 `ops/bin/xiaohongshu-mcp` 随仓库提供，`start_all.sh mcp` 直接可用。

要自己重编（例如换了架构）才需要源码 + Go：

```bash
git clone https://github.com/xpzouying/xiaohongshu-mcp apps/xiaohongshu-mcp
git -C apps/xiaohongshu-mcp checkout $(cat docs/patches/xhs-mcp-local-2026-09-19/base-commit.txt)
git -C apps/xiaohongshu-mcp apply ../../docs/patches/xhs-mcp-local-2026-09-19/tracked.diff
# 再装 Go 并把 GOROOT 指过去（脚本默认用 var/toolchains/go，离线编译）
GOPROXY=https://proxy.golang.org ./ops/build_mcp.sh
```

补丁内容与原因见 `docs/patches/xhs-mcp-local-2026-09-19/`。**不要改 `reference/upstream/` 里的代码**（规范 §7）。

## 6. 凭证：需要你本人做的事

| 东西 | 放哪 | 怎么来 |
| --- | --- | --- |
| LLM 密钥 | `apps/papercast-server/.env` 的 `LLM_API_KEY` | 任何 OpenAI 兼容端点；不填时后端会尝试读 `~/.dsh/.credentials.yaml` |
| 小红书登录态 | `apps/xiaohongshu-mcp/cookies.json` + `var/cache/xiaohongshu-mcp/browser/` | 前端「平台账号」页扫码，或 `./ops/bin/xiaohongshu-login` |
| 知乎登录态 | `var/secrets/zhihu/cookies.json` | 桌面窗口人工登录（风控拦纯 HTTP 扫码）：`./ops/start_all.sh zhihu` → 前端点「打开浏览器登录」 |
| 知乎 OpenAPI 密钥 | `ZHIHU_OPENAPI_APP_KEY` / `ZHIHU_OPENAPI_APP_SECRET` | 到知乎开放平台申请（需审核） |
| B站登录态 | `var/home/.bilibili/cookies.json`（biliup 自管） | `./ops/start_all.sh bilibili` → 前端扫码，或 `ops/biliup_login_pty.py` |

**这些一律不入库**（`.gitignore` 已覆盖 `var/`、`cookies.json`、`.env`），也永远不要贴进 issue/日志。
规则见 `docs/conventions.md` §5、`var/secrets/README.md`。

## 7. 装完怎么确认没问题

```bash
# 1) 渠道层自检（不联网、不投递、不写真实 var/ 数据）
apps/papercast-server/.venv/bin/python apps/papercast-server/scripts/check_channels.py
#    期望：25 项通过 / 0 失败

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
| 端口被占，`start_all.sh` 说跳过 | 幂等设计：它只在端口空闲时启动。先 `./ops/stop_all.sh` 或 `ss -ltn` 看谁占着 |
| 知乎点登录返回 409 `NO_DISPLAY` | 本机没有可见显示（无头服务器/容器）。需要在有桌面的终端跑，或用 `apps/zhihu-publisher/scripts/login-headed.sh` |
| 卡片上的中文是方块 | 缺 CJK 字体：`sudo apt install fonts-noto-cjk`，或设 `PAPERCAST_CJK_FONT=/path/to/font.ttc` |
| 卡片渲染失败 / 提示找不到 chrome | 装 `--with-zhihu`（带 chromium）或系统 chromium，或设 `PAPERCAST_CHROME=` 显式指向 |
| 通道显示 `offline`（连不上 127.0.0.1:180xx） | 那个通道服务没起：`./ops/start_all.sh zhihu|bilibili|mcp` |
| 通道显示 `login_required` / `unconfigured` | 如实上报，不是 bug：按第 6 节登录，或按第 4 节装依赖 |
| 服务启动报错 | 看 `var/logs/<服务>.log`；小红书 MCP 必须在自己的组件目录里启动（cookie 是 cwd 相对路径），`start_all.sh` 已处理 |
| 装了代理后本地服务连不上 | 通道一律 `trust_env=False`，本机服务不该走代理；若日志里出现 proxy 报错，检查 `http_proxy` 环境变量 |

## 9. 运行数据都在 `var/`（整个目录不入库）

产出、日志、缓存、凭证、工具链全在 `var/` 下，删掉整个目录只会丢历史运行记录。
目录职责与清理建议见 `var/README.md` 与 `docs/conventions.md` §4。最该珍惜的是：
`var/secrets/`（凭证）、`var/home/.bilibili/`、`var/cache/xiaohongshu-mcp/browser/`（登录态）、`var/runs/`（历史产出）。
