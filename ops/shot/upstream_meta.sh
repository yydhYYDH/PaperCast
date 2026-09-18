#!/bin/sh
# 一次性元数据导出（临时）
U=/home/yydh/hack/reference/upstream
for d in "$U"/*/; do
  n=$(basename "$d")
  [ -d "$d/.git" ] || { printf "%s\t(NO .git)\t\t\t\t\n" "$n"; continue; }
  url=$(git -C "$d" remote get-url origin 2>/dev/null)
  sha=$(git -C "$d" log -1 --format=%h 2>/dev/null)
  date=$(git -C "$d" log -1 --format=%cs 2>/dev/null)
  sh=$(git -C "$d" rev-parse --is-shallow-repository 2>/dev/null)
  lic=$(ls "$d" 2>/dev/null | grep -iE "^(license|copying)" | head -1)
  sz=$(du -sh "$d" 2>/dev/null | cut -f1)
  printf "%s\t%s\t%s\t%s\tshallow=%s\tlic=%s\tsize=%s\n" "$n" "$url" "$sha" "$date" "$sh" "$lic" "$sz"
done
