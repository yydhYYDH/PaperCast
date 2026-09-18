#!/bin/sh
U=/home/yydh/hack/reference/upstream
for d in "$U"/*/; do
  n=$(basename "$d")
  title=$(grep -m1 -E "^# " "$d/README.md" 2>/dev/null | sed 's/^# *//' | cut -c1-70)
  desc=$(grep -m1 -vE "^$|^#|^!|^\[|^<|^\|" "$d/README.md" 2>/dev/null | sed 's/[[:space:]]\+/ /g' | cut -c1-110)
  lic=$(grep -m1 -ioE "MIT License|Apache License|GNU (GENERAL|AFFERO)|BSD|Mozilla Public" "$d"/LICENSE* 2>/dev/null | head -1)
  printf "%s :: %s :: %s :: %s\n" "$n" "$title" "$lic" "$desc"
done
