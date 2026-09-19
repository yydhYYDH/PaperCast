#!/usr/bin/env bash
# 回放三条**历史**案例，验证「发布后核验」判得对（纯读，不发布任何东西）。
#
# 背景（2026-09-19）：回执里写过四次「知乎已发布」，只有两次是真的。
#   · 22:24 本轮发布 p/2084769164527407496   -> 账号文章列表里没有它，登录态打开是知乎 404（假成功）
#   · 22:53 作品库直投 p/2084776632280150987 -> 同上（假成功）
#   · 12:47 直投 p/2084624457373696794       -> 真在账号里，但回执记的是 …/edit 编辑页地址
#   · 13:58 直投 p/2084642284419674506       -> 真在账号里，回执同样记了 …/edit
# 现在 app/article_flow.py 的 publish_article 在点完「发布」后会调 verify_published：
# 账号文章列表里有它（或文章页打得开且标题对得上）才算成功，并把正式地址写回 url。
#
# 用法（服务在跑就行）：bash apps/zhihu-publisher/scripts/replay_verify_cases.sh [base_url]
set -u
BASE="${1:-http://127.0.0.1:18070}"

probe() {
  local url="$1" title="${2:-}"
  local args=(-s -m 200 -G --data-urlencode "url=$url")
  [ -n "$title" ] && args+=(--data-urlencode "title=$title")
  NO_PROXY=127.0.0.1 no_proxy=127.0.0.1 curl "${args[@]}" "$BASE/api/v1/verify" | python3 -c "
import json, sys
raw = sys.stdin.read()
try:
    d = json.loads(raw).get('data', {})
except Exception:
    print('  原始回应:', raw[:200]); raise SystemExit(1)
print('  verified=%s how=%s total=%s' % (d.get('verified'), d.get('how') or '-', d.get('total')))
print('  正式地址:', d.get('canonicalUrl') or '-')
if d.get('note'):
    print('  说明:', d.get('note'))
"
}

echo '① 21:24 那条假成功（应: verified=False）'
probe 'https://zhuanlan.zhihu.com/p/2084769164527407496'
echo '② 12:47 真发了的那篇（应: verified=True，正式地址不带 /edit）'
probe 'https://zhuanlan.zhihu.com/p/2084624457373696794' 'DeepRare：三层多智能体系统做罕见病诊断，HPO 任务 Recall@1 达 57.18%'
echo '③ 13:58 回执记成 /edit 的那篇（应: verified=True，正式地址不带 /edit）'
probe 'https://zhuanlan.zhihu.com/p/2084642284419674506/edit' '把注意力对准目标：ReconVLA 用重建视线区域改进机器人操作'
echo '（三条都符合预期 = 核验可用；它不会因为列表里有一篇别的文章就判成功）'
