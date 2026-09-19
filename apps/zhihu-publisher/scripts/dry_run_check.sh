#!/usr/bin/env bash
# 真发布是不可逆的，验「填稿这条路通不通」只能用只填不发的 dry_run。
#
# 它做的事：把某个运行导出好的素材（标题 / 正文 / p*.jpg 配图）交给 /api/v1/publish，
# 带 dry_run=true —— 渠道那边会把标题正文填进编辑器、把图传进正文，**绝不点「发布」**。
# 断言：接口 success、图「上传数 == 传进去的张数」、正文块数 > 0；任一不满足 exit 1。
#
# 用法：bash apps/zhihu-publisher/scripts/dry_run_check.sh [导出目录] [服务地址]
#   默认导出目录取 var/runs 下最近一次有 zhihu export 的运行。
set -u
WS="$(cd "$(dirname "$0")/../../.." && pwd)"
BASE="${2:-http://127.0.0.1:18070}"

pick_export() {
  local d
  for d in $(ls -1dt "$WS"/var/runs/*/publish/zhihu/export 2>/dev/null); do
    [ -f "$d/title.txt" ] && [ -f "$d/content.txt" ] && { echo "$d"; return; }
  done
}
EXPORT="${1:-$(pick_export)}"
if [ -z "$EXPORT" ] || [ ! -f "$EXPORT/title.txt" ]; then
  echo "找不到可用的导出目录（需要 title.txt + content.txt）：$EXPORT" >&2
  exit 2
fi

PY="${PAPERCAST_PY:-$WS/apps/papercast-server/.venv/bin/python}"
BODY="$WS/var/scratch/dry-run-request.json"
mkdir -p "$(dirname "$BODY")"
"$PY" - "$EXPORT" "$BODY" <<'PY'
import json, pathlib, sys
d, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
imgs = sorted(str(p) for p in d.glob('p*.jpg'))
out.write_text(json.dumps({
    "title": (d / 'title.txt').read_text(encoding='utf-8').strip(),
    "content": (d / 'content.txt').read_text(encoding='utf-8'),
    "images": imgs, "tags": [], "run_id": "dry-run-check", "confirmed": True, "dry_run": True,
}, ensure_ascii=False), encoding='utf-8')
print(len(imgs))
PY
WANT="$(basename "$EXPORT")"
COUNT="$("$PY" -c "import json;print(len(json.load(open('$BODY'))['images']))")"

echo "素材：$EXPORT（$COUNT 张配图）"
START=$(date +%s)
env NO_PROXY=127.0.0.1 no_proxy=127.0.0.1 curl -s -m 300 -H 'Content-Type: application/json' \
  --data "@$BODY" "$BASE/api/v1/publish" > "$WS/var/scratch/dry-run-result.json"
END=$(date +%s)
echo "耗时：$((END - START))s"

"$PY" - "$WANT" "$COUNT" "$WS/var/scratch/dry-run-result.json" <<'PY'
import json, sys
want, count, path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
r = json.load(open(path, encoding='utf-8'))
d = r.get('data') or {}
blocks = (d.get('markdown') or {}).get('blocks')
up, bad = d.get('imagesUploaded'), d.get('imagesFailed')
print("success=%s 正文块=%s 图=%s/%s 失败 标签=%s" % (r.get('success'), blocks, up, bad, d.get('tagsAdded')))
print("message:", str(d.get('upstreamMessage') or r.get('error') or '')[:160])
for w in (d.get('warnings') or [])[:3]:
    print("warning:", str(w)[:140])
bad_list = []
if not r.get('success'): bad_list.append('接口没成功')
if blocks in (None, 0): bad_list.append('正文块数为 0')
if up != count: bad_list.append('配图只上去 %s/%s 张' % (up, count))
if bad: bad_list.append('%s 张图失败了' % bad)
print('✗ ' + '；'.join(bad_list) if bad_list else '✓ dry_run 通过：标题正文已填、配图 %s/%s 张进正文（没有点发布）' % (count, count))
sys.exit(1 if bad_list else 0)
PY
