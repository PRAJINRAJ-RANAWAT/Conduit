#!/bin/bash
# Fires 8 requests as "bob" (limit 5/min). Expect five 200s then 429s.
# Needs: docker compose up -d, gateway on :8000 (see README).
for i in 1 2 3 4 5 6 7 8; do
  curl -s -o /dev/null -w "request $i -> HTTP %{http_code}\n" localhost:8000/v1/chat/completions \
    -H "Authorization: Bearer key-bob" -H "Content-Type: application/json" \
    -d "{\"messages\":[{\"role\":\"user\",\"content\":\"q$i-$RANDOM\"}]}"
done
