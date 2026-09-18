#!/usr/bin/env bash
# 一条命令把工作区装起来（给刚 clone 下来的人用）。
#
# 用法：
#   ./ops/install.sh                     # 最小可用：后端 venv + 前端依赖 + 上游参考克隆
#   ./ops/install.sh --all               # 全都装上：两个发布通道 + 小红书 MCP（要 Go）+ 截图工具
#   ./ops/install.sh --with-zhihu        # 只加知乎通道（Playwright + chromium）
#   ./ops/install.sh --with-bilibili     # 只加 B站通道（biliup 独立 venv）
#   ./ops/install.sh --with-mcp          # 只加小红书 MCP（clone 源码 + 打补丁 + Go 编译）
#   ./ops/install.sh --with-shot         # 只加截图/海报渲染工具（ops/shot 的 npm 依赖）
#   ./ops/install.sh --skip-upstream     # 不克隆 reference/upstream/（不需要上游时）
#   ./ops/install.sh --no-lock           # 用 requirements.txt（跟随下限）而不是 requirements.lock.txt
#
# 二进制不入库：小红书 MCP 需要自己编（--with-mcp，要 Go >= 1.24），见 docs/INSTALL.md §5.2。
#
# 幂等：已存在的 venv / 已装的依赖 / 已克隆的上游都跳过，不覆盖、不删除。
# 非破坏性：脚本只写 var/ 与组件内的 .venv/、node_modules/，不动你的代码与 git 状态。
#
# 装完跑：./ops/start_all.sh  → 前端 http://127.0.0.1:5178  后端 http://127.0.0.1:8000/docs
set -euo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
APPS="$WS/apps"
VENV="$APPS/papercast-server/.venv"
PYTHON_MIN="3.11"

WITH_ZHIHU=0
WITH_BILIBILI=0
WITH_MCP=0
WITH_SHOT=0
SKIP_FRONTEND=0
SKIP_UPSTREAM=0
USE_LOCK=1

while [ $# -gt 0 ]; do
  case "$1" in
    --all)            WITH_ZHIHU=1; WITH_BILIBILI=1; WITH_MCP=1; WITH_SHOT=1 ;;
    --with-zhihu)     WITH_ZHIHU=1 ;;
    --with-bilibili)  WITH_BILIBILI=1 ;;
    --with-mcp)       WITH_MCP=1 ;;
    --with-shot)      WITH_SHOT=1 ;;
    --skip-frontend)  SKIP_FRONTEND=1 ;;
    --skip-upstream)  SKIP_UPSTREAM=1 ;;
    --no-lock)        USE_LOCK=0 ;;
    -h|--help)        sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "未知参数：$1（--help 看用法）" >&2; exit 2 ;;
  esac
  shift
done

# 缓存一律收进 var/（规范 §2）：工作区自包含，也避免家目录缓存只读时整个安装失败
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$WS/var/cache/pip}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$WS/var/cache/uv}"
export npm_config_cache="${npm_config_cache:-$WS/var/cache/npm}"
export npm_config_tmp="${npm_config_tmp:-$WS/var/npm-tmp}"
mkdir -p "$PIP_CACHE_DIR" "$UV_CACHE_DIR" "$npm_config_cache" "$npm_config_tmp"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   ✓ %s\n' "$*"; }
skip() { printf '   · %s\n' "$*"; }
die()  { printf '\n   ✗ %s\n' "$*" >&2; exit 1; }

# ---------- 0. 找 Python ----------
find_python() {
  for c in python3.13 python3.12 python3.11 python3; do
    command -v "$c" >/dev/null 2>&1 || continue
    if "$c" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= tuple(int(x) for x in '$PYTHON_MIN'.split('.')) else 1)"; then
      echo "$c"; return 0
    fi
  done
  return 1
}

say "环境检查"
PY="$(find_python)" || die "需要 Python >= $PYTHON_MIN（推荐 3.13）：https://www.python.org/downloads/"
ok "Python: $(command -v "$PY") → $("$PY" -V 2>&1)"
if [ "$SKIP_FRONTEND" = 0 ]; then
  command -v node >/dev/null 2>&1 || die "需要 Node.js >= 20：https://nodejs.org/"
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
  [ "$NODE_MAJOR" -ge 20 ] || die "Node 版本过低（当前 $(node -v)），需要 >= 20"
  ok "Node: $(node -v) / npm $(npm -v)"
fi

# 软依赖：缺了不阻断安装，但会影响某些路径（见 docs/INSTALL.md §4）
MISSING=""
for c in curl jq fc-list ss; do command -v "$c" >/dev/null 2>&1 || MISSING="$MISSING $c"; done
if [ -n "$MISSING" ]; then
  printf '   · 建议补装（可选）：%s\n' "$MISSING"
  printf '     sudo apt install -y curl jq iproute2 fontconfig   # jq 给冒烟脚本用，fontconfig 帮后端找中文字体\n'
fi
if command -v fc-list >/dev/null 2>&1; then
  fc-list :lang=zh >/dev/null 2>&1 || printf '   · 没找到中文字体：卡片上的中文会是方块 → sudo apt install fonts-noto-cjk\n'
fi

# ---------- 1. 目录骨架 ----------
say "准备 var/ 目录"
mkdir -p "$WS/var"/{runs,uploads,logs,pids,samples,cache,artifacts,secrets,scratch,tmp,build}
ok "var/{runs,uploads,logs,pids,samples,cache,artifacts,secrets,scratch,tmp,build}"
if [ ! -f "$APPS/papercast-server/.env" ] && [ -f "$APPS/papercast-server/.env.example" ]; then
  cp "$APPS/papercast-server/.env.example" "$APPS/papercast-server/.env"
  ok "已从 .env.example 生成 apps/papercast-server/.env（**记得填 LLM 密钥**）"
else
  skip "apps/papercast-server/.env 已存在"
fi

# ---------- 2. 后端 venv ----------
say "后端依赖（apps/papercast-server）"
if [ -x "$VENV/bin/python" ]; then
  skip "venv 已存在：$VENV"
else
  "$PY" -m venv "$VENV"
  ok "创建 venv：$VENV"
fi
REQ="$APPS/papercast-server/requirements.txt"
[ "$USE_LOCK" = 1 ] && [ -f "$APPS/papercast-server/requirements.lock.txt" ] && REQ="$APPS/papercast-server/requirements.lock.txt"
"$VENV/bin/python" -m pip install --quiet --upgrade pip \
  || die "pip 升级失败（缓存目录不可写？PIP_CACHE_DIR=$PIP_CACHE_DIR）"
"$VENV/bin/python" -m pip install --quiet -r "$REQ" || die "装依赖失败：$REQ"
ok "安装依赖：$(basename "$REQ")（$(grep -cve '^\s*#' -e '^\s*$' "$REQ") 行）"
"$VENV/bin/python" -c "import fastapi, fitz, pymupdf4llm, httpx, PIL, psutil; print('   ✓ 关键依赖可导入: fastapi / pymupdf / pymupdf4llm / httpx / pillow / psutil')"

# ---------- 3. 前端 ----------
if [ "$SKIP_FRONTEND" = 0 ]; then
  say "前端依赖（apps/papercast）"
  # 判断"装好了"要看哨兵文件，不能只看目录在不在：npm 中途失败会留下半个 node_modules，
  # 只看目录就会把坏环境当好的（第一次跑这个脚本正好踩到）。
  if [ -x "$APPS/papercast/node_modules/.bin/vite" ]; then
    skip "node_modules 看起来完整（要重装：rm -rf apps/papercast/node_modules 后重跑）"
  else
    if [ -d "$APPS/papercast/node_modules" ]; then
      rm -rf "$APPS/papercast/node_modules"
      skip "清掉上一次没装完的 node_modules"
    fi
    if [ -f "$APPS/papercast/package-lock.json" ]; then
      npm --prefix "$APPS/papercast" ci --no-audit --no-fund --silent \
        || die "npm ci 失败（网络问题，或缓存目录不可写：npm_config_cache=$npm_config_cache）"
      ok "npm ci 完成（缓存：$npm_config_cache）"
    else
      npm --prefix "$APPS/papercast" install --no-audit --no-fund --silent || die "npm install 失败"
      ok "npm install 完成"
    fi
  fi
fi

# ---------- 4. 上游只读克隆 ----------
if [ "$SKIP_UPSTREAM" = 0 ]; then
  say "上游参考克隆（reference/upstream/，按登记的 commit 固定）"
  if [ -x "$WS/ops/sync_upstream.sh" ]; then
    "$WS/ops/sync_upstream.sh" || printf '   ! 有上游没取全（离线或网络受限？）。核心流水线不依赖它们，可稍后重跑本步。\n'
  else
    skip "没有 ops/sync_upstream.sh，跳过"
  fi
else
  skip "按参数要求跳过上游克隆"
fi

# ---------- 5. 本地二进制（小红书 MCP） ----------
say "本地二进制（ops/bin/ —— 不入库，需要自己编）"
chmod +x "$WS"/ops/bin/* 2>/dev/null || true
HAVE_MCP=1
for b in xiaohongshu-mcp xiaohongshu-mcp-auth xiaohongshu-login; do
  [ -x "$WS/ops/bin/$b" ] || HAVE_MCP=0
done
if [ "$HAVE_MCP" = 1 ]; then
  ok "ops/bin/ 三个 Linux 二进制都在"
elif [ "$WITH_MCP" = 0 ]; then
  skip "还没有 ops/bin/xiaohongshu-mcp（小红书通道用不了，其它不受影响）"
  printf '   · 想要小红书通道：./ops/install.sh --with-mcp（要 Go >= 1.24，会 clone 源码并编译）\n'
fi

# ---------- 6. 知乎通道 ----------
if [ "$WITH_ZHIHU" = 1 ]; then
  say "知乎通道（apps/zhihu-publisher）"
  ZVENV="$WS/var/toolchains/zhihu-mcp-venv"
  if [ ! -d "$WS/reference/upstream/zhihu-mcp" ]; then
    printf '   ! 缺少 reference/upstream/zhihu-mcp（上游克隆没取到），知乎通道暂时装不了。\n'
  else
    [ -x "$ZVENV/bin/python" ] || { "$PY" -m venv "$ZVENV"; ok "创建 venv：$ZVENV"; }
    "$ZVENV/bin/python" -m pip install --quiet --upgrade pip
    ZREQ="$APPS/zhihu-publisher/requirements.txt"
    [ "$USE_LOCK" = 1 ] && [ -f "$APPS/zhihu-publisher/requirements.lock.txt" ] && ZREQ="$APPS/zhihu-publisher/requirements.lock.txt"
    "$ZVENV/bin/python" -m pip install --quiet -r "$ZREQ"
    ok "安装依赖：$(basename "$ZREQ")"
    if "$ZVENV/bin/python" -c "import playwright" 2>/dev/null; then
      export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
      "$ZVENV/bin/python" -m playwright install chromium >/dev/null 2>&1 \
        && ok "chromium 就绪（PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH）" \
        || printf '   ! chromium 没装上（网络？）。只有 Playwright 通道需要它，可稍后手工：%s -m playwright install chromium\n' "$ZVENV/bin/python"
    fi
    printf '   · 登录知乎需要**桌面窗口**（风控拦纯 HTTP 扫码）：./ops/start_all.sh zhihu 后点前端「打开浏览器登录」\n'
  fi
fi

# ---------- 7. B站通道 ----------
if [ "$WITH_BILIBILI" = 1 ]; then
  say "B站通道（apps/bilibili-publisher）"
  BVENV="$WS/var/toolchains/bili-venv"
  [ -x "$BVENV/bin/python" ] || { "$PY" -m venv "$BVENV"; ok "创建 venv：$BVENV"; }
  "$BVENV/bin/python" -m pip install --quiet --upgrade pip
  "$BVENV/bin/python" -m pip install --quiet "biliup==1.2.4"
  ok "biliup $("$BVENV/bin/python" -c "import importlib.metadata as m; print(m.version('biliup'))" 2>/dev/null || echo '?') 装好在 $BVENV"
  printf '   · 登录：./ops/start_all.sh bilibili 后点前端扫码，或跑 ops/biliup_login_pty.py（终端里扫码）\n'
  printf '   · 没登录时服务如实报 unconfigured，素材包照常导出\n'
fi

# ---------- 8. 小红书 MCP（源码编译，二进制不入库） ----------
if [ "$WITH_MCP" = 1 ]; then
  say "小红书 MCP（clone 源码 + 打补丁 + 编译）"
  SRC="$APPS/xiaohongshu-mcp"
  PATCH_DIR="$WS/docs/patches/xhs-mcp-local-2026-09-19"
  UPSTREAM_URL="${XHS_MCP_REPO_URL:-https://github.com/xpzouying/xiaohongshu-mcp}"
  if [ -d "$SRC/.git" ]; then
    skip "源码已存在：$SRC（要重来：rm -rf apps/xiaohongshu-mcp 后重跑）"
  else
    command -v git >/dev/null 2>&1 || die "缺 git"
    git clone --quiet "$UPSTREAM_URL" "$SRC" || die "clone 失败：$UPSTREAM_URL"
    ok "clone 上游：$UPSTREAM_URL"
    if [ -f "$PATCH_DIR/base-commit.txt" ]; then
      ( cd "$SRC" && git checkout --quiet "$(cat "$PATCH_DIR/base-commit.txt")" ) \
        && ok "切到登记 commit：$(cat "$PATCH_DIR/base-commit.txt" | cut -c1-7)"
    fi
    if [ -f "$PATCH_DIR/tracked.diff" ]; then
      if ( cd "$SRC" && git apply "$PATCH_DIR/tracked.diff" ); then
        ok "已打上本地补丁（auth / guard 等改动）"
      else
        printf '   ! 补丁没打上（可能已包含或冲突）——看 %s/status.txt\n' "$PATCH_DIR"
        printf '     小红书"带鉴权/护栏"的那一版需要这个补丁；不打也能编，只是少了本地改动。\n'
      fi
    fi
  fi
  if [ -x "$WS/var/toolchains/go/bin/go" ] || command -v go >/dev/null 2>&1; then
    ok "Go 就绪"
  else
    die "缺 Go（需要 >= 1.24）：https://go.dev/dl/ 装好后重跑，或把工具链解压到 var/toolchains/go"
  fi
  "$WS/ops/build_mcp.sh" || die "编译失败（看上面的输出；docs/INSTALL.md §5.2）"
  ok "ops/bin/ 已产出：xiaohongshu-mcp / -auth / xiaohongshu-login（+ 两个 Windows .exe）"
  printf '   · 首次运行 MCP 会自动下载内置 Chromium（约 150MB）到 var/cache/xiaohongshu-mcp/browser/\n'
fi

# ---------- 9. 截图 / 海报渲染工具（ops/shot） ----------
if [ "$WITH_SHOT" = 1 ]; then
  say "截图 / 海报渲染工具（ops/shot）"
  command -v npm >/dev/null 2>&1 || die "缺 npm（Node >= 20）"
  if [ -d "$WS/ops/shot/node_modules/playwright" ]; then
    skip "ops/shot 依赖已装"
  else
    npm --prefix "$WS/ops/shot" install --no-audit --no-fund --silent \
      || die "ops/shot 依赖安装失败（npm_config_cache=$npm_config_cache）"
    ok "ops/shot 依赖装好（含 playwright）"
  fi
  printf '   · 还需要一个 chromium：node ops/shot/render.mjs 会告诉你缺什么；\n'
  printf '     或 var/toolchains/zhihu-mcp-venv/bin/python -m playwright install chromium\n'
fi

# ---------- 10. 收尾 ----------
say "完成"
printf '   后端 venv   : %s\n' "$VENV"
printf '   启动全部    : ./ops/start_all.sh\n'
printf '   停止全部    : ./ops/stop_all.sh\n'
printf '   前端        : http://127.0.0.1:5178   后端文档: http://127.0.0.1:8000/docs\n'
printf '   自检（不联网）：apps/papercast-server/.venv/bin/python apps/papercast-server/scripts/check_channels.py\n'
printf '\n   还没做的事（都需要你本人）：\n'
printf '   1) 填 apps/papercast-server/.env 里的 LLM 密钥（不填就只出模板/离线路径）\n'
printf '   2) 各平台登录（小红书扫码 / 知乎桌面窗口 / B站扫码）—— 见 docs/INSTALL.md「凭证」\n'
printf '   3) 详细说明与可选项：docs/INSTALL.md\n'
