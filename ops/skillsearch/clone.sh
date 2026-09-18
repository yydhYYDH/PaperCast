#!/bin/sh
cd /home/yydh/hack/reference/upstream || exit 1
export GIT_TERMINAL_PROMPT=0
repos="
flyanx/paper-to-wechat
aiworkskills/wechat-article-skills
op7418/guizang-social-card-skill
yhbcode000/paper-share-skills
HKUDS/Paper2Slides
pickxiguapi/paper2x
QuZhan51496/paper2anything
icip-cas/PPTAgent
showlab/Paper2Video
OpenDCAI/Paper2Any
Paper2Poster/Paper2Poster
"
for r in $repos; do
  name=$(echo "$r" | cut -d/ -f2)
  if [ -d "$name" ]; then echo "SKIP $name (exists)"; continue; fi
  echo "=== cloning $r ==="
  if git clone --depth 1 --single-branch "https://github.com/$r.git" "$name" 2>&1 | tail -2; then
    echo "DONE $name $(du -sh $name 2>/dev/null | cut -f1)"
  else
    echo "FAIL $name"
  fi
done
echo "=== ALL CLONES FINISHED ==="
du -sh /home/yydh/hack/reference/upstream/* 2>/dev/null
