#!/usr/bin/env bash
# 开发模式启动：http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  echo "缺少 .venv，先执行：" >&2
  echo "  export UV_CACHE_DIR=/home/yydh/hack/var/cache/uv" >&2
  echo "  uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -r requirements.txt" >&2
  exit 1
fi

HOST="${PAPERCAST_HOST:-127.0.0.1}"
PORT="${PAPERCAST_PORT:-8000}"
echo "PaperCast API -> http://${HOST}:${PORT}"
exec .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
