#!/usr/bin/env bash
# 冒烟：上传一个 PDF → 建运行 → 轮询到等待闸门 → 放行 → 打印产物
# 用法：./scripts/smoke_test.sh /path/to/paper.pdf [base_url]
#
# 发布闸门默认回 draft（只准备 export/，不真实投递）。只有显式 PUBLISH=1 才真发帖：
#   PUBLISH=1 ./scripts/smoke_test.sh paper.pdf
set -euo pipefail

PDF="${1:?用法: smoke_test.sh <paper.pdf> [base_url]}"
BASE="${2:-http://127.0.0.1:8000}"
PUBLISH="${PUBLISH:-0}"

command -v jq >/dev/null || { echo "需要 jq" >&2; exit 1; }

echo "== 1. 上传 =="
UP=$(curl -sS -F "file=@${PDF}" "${BASE}/api/uploads")
echo "$UP" | jq -c .
UPLOAD_ID=$(echo "$UP" | jq -r .uploadId)

echo "== 2. 建运行 =="
RUN=$(curl -sS -X POST "${BASE}/api/runs" -H 'Content-Type: application/json' \
  -d "{\"source\":{\"kind\":\"pdf\",\"value\":\"${UPLOAD_ID}\"},\"config\":{\"article\":{\"variants\":[\"xhs\"]},\"publish\":{\"targets\":[\"xiaohongshu\"],\"autoPublish\":false}}}")
RUN_ID=$(echo "$RUN" | jq -r .id)
echo "run: $RUN_ID"

echo "== 3. 轮询 =="
for i in $(seq 1 240); do
  S=$(curl -sS "${BASE}/api/runs/${RUN_ID}")
  ST=$(echo "$S" | jq -r .status)
  CUR=$(echo "$S" | jq -r '[.stages[] | select(.status=="running" or .status=="waiting")][0] | "\(.id) \(.status) \(.progress)"')
  echo "  [$i] run=$ST stage=$CUR"
  if [ "$ST" = "waiting" ]; then
    SID=$(echo "$S" | jq -r '[.stages[] | select(.status=="waiting")][0].id')
    if [ "$SID" = "publish" ] && [ "$PUBLISH" != "1" ]; then
      OPTION="draft"
      echo "== 4. 放行闸门 publish → draft（安全默认：只准备 export/，不投递）=="
    else
      OPTION="continue"
      echo "== 4. 放行闸门 ${SID} → ${OPTION} =="
    fi
    curl -sS -o /dev/null -w "gate %{http_code}\n" -X POST \
      "${BASE}/api/runs/${RUN_ID}/stages/${SID}/gate" -H 'Content-Type: application/json' \
      -d "{\"optionId\":\"${OPTION}\"}"
  fi
  [ "$ST" = "done" ] && break
  [ "$ST" = "failed" ] && { echo "$S" | jq '.error'; exit 1; }
  sleep 3
done

echo "== 5. 结果 =="
curl -sS "${BASE}/api/runs/${RUN_ID}" | jq '{status, title, digest: (.digest.title // null), stages: [.stages[] | {id, status, artifacts: (.artifacts | length), checks}]}'
echo "产物地址：${BASE}/artifacts/${RUN_ID}/article/xhs.md"
