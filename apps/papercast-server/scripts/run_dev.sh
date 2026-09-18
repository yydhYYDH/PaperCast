#!/usr/bin/env bash
# 开发模式启动：http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  echo "缺少 .venv，先执行：" >&2
  echo "  # 推荐直接跑仓库根的安装脚本（幂等）：./ops/install.sh --skip-frontend" >&2
  echo "  # 或者手工：cd <仓库根> && python3 -m venv apps/papercast-server/.venv && \\" >&2
  echo "  #   apps/papercast-server/.venv/bin/pip install -r apps/papercast-server/requirements.lock.txt" >&2
  exit 1
fi

HOST="${PAPERCAST_HOST:-127.0.0.1}"
PORT="${PAPERCAST_PORT:-8000}"
echo "PaperCast API -> http://${HOST}:${PORT}"
exec .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
