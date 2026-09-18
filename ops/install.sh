#!/usr/bin/env bash
# 一条命令把工作区装起来（给刚 clone 下来的人用）。
#
# 用法：
#   ./ops/install.sh                     # 最小可用：后端 venv + 前端依赖 + 上游参考克隆
#   ./ops/install.sh --all               # 加上两个发布通道（知乎 Playwright / B站 biliup）
#   ./ops/install.sh --with-zhihu        # 只加知乎通道
#   ./ops/install.sh --with-bilibili     # 只加 B站通道
#   ./ops/install.sh --skip-upstream     # 不克隆 reference/upstream/（不需要上游时）
#   ./ops/install.sh --no-lock           # 用 requirements.txt（跟随下限）而不是 requirements.lock.txt
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
SKIP_FRONTEND=0
SKIP_UPSTREAM=0
USE_LOCK=1

while [ $# -gt 0 ]; do
  case "$1" in
    --all)            WITH_ZHIHU=1; WITH_BILIBILI=1 ;;
    --with-zhihu)     WITH_ZHIHU=1 ;;
    --with-bilibili)  WITH_BILIBILI=1 ;;
    --skip-frontend)  SKIP_FRONTEND=1 ;;
    --skip-upstream)  SKIP_UPSTREAM=1 ;;
    --no-lock)        USE_LOCK=0 ;;
    -h|--help)        sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "未知参数：$1（--help 看用法）" >&2; exit 2 ;;
  esac
  shift
done

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
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$REQ"
ok "安装依赖：$(basename "$REQ")（$(grep -cve '^\s*#' -e '^\s*$' "$REQ") 行）"
"$VENV/bin/python" -c "import fastapi, fitz, pymupdf4llm, httpx, PIL, psutil; print('   ✓ 关键依赖可导入: fastapi / pymupdf / pymupdf4llm / httpx / pillow / psutil')"

# ---------- 3. 前端 ----------
if [ "$SKIP_FRONTEND" = 0 ]; then
  say "前端依赖（apps/papercast）"
  if [ -d "$APPS/papercast/node_modules" ]; then
    skip "node_modules 已存在（要重装：rm -rf apps/papercast/node_modules 后重跑）"
  elif [ -f "$APPS/papercast/package-lock.json" ]; then
    npm --prefix "$APPS/papercast" ci --silent
    ok "npm ci 完成"
  else
    npm --prefix "$APPS/papercast" install --silent
    ok "npm install 完成"
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
say "本地二进制（ops/bin/）"
chmod +x "$WS"/ops/bin/* 2>/dev/null || true
for b in xiaohongshu-mcp xiaohongshu-mcp-auth xiaohongshu-login; do
  if [ -x "$WS/ops/bin/$b" ]; then ok "ops/bin/$b 可执行"; else skip "缺少 ops/bin/$b"; fi
done
printf '   · 重新编译（可选，需要 Go）：./ops/build_mcp.sh —— 见 docs/INSTALL.md「重编小红书 MCP」\n'

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

# ---------- 8. 收尾 ----------
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
