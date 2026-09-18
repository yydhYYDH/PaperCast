#!/bin/sh
D="$HOME/.dsh/sessions/--home-yydh-hack--"
O=/home/yydh/hack/var/sessions
mkdir -p "$O"
i=0
for s in session-9a2e73c4-97bf-4bc2-9357-5d16ed4abba4 session-a1420e6d-6203-4fc2-aa53-b1f197a2241c session-b5026512-4b3d-49de-a6a8-f6c4b29dc59f session-0624897e-aed5-4562-9d06-47ef874e6878 session-ff8705e2-016c-4b1a-aec3-5685596b2e5f; do
  i=$((i+1))
  zstd -dc "$D/$s/session.jsonl.zstd" > "$O/sess-$i.jsonl" 2>/dev/null
  printf "sess-%s.jsonl  %s\n" "$i" "$(du -h $O/sess-$i.jsonl | cut -f1)"
done
ls -la "$O"
