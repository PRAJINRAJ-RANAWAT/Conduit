#!/bin/bash
# Shows the token limiter. "bob" has 300 tokens/min; each call below costs ~100.
# Expect: several 200s (tokens left shrinking) then 429 with a Retry-After header.
for i in 1 2 3 4 5; do
  curl -s -D - -o /dev/null localhost:8080/v1/chat/completions \
    -H "Authorization: Bearer key-bob" -H "Content-Type: application/json" \
    -d "{\"max_tokens\":100,\"messages\":[{\"role\":\"user\",\"content\":\"q$i-$RANDOM\"}]}" \
    | grep -iE "^HTTP|retry-after|x-ratelimit|x-conduit" | tr -d '\r' | paste -sd' ' -
done
