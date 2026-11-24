#!/bin/bash
# Provider A fails on demand. Watch calls move to B, then return to A after A recovers.
# Needs gateway :8080, mock providers A :9000 and B :9001. (Breaker cooldown is 10s.)
call() { curl -s -D - -o /dev/null localhost:8080/v1/chat/completions -H "Authorization: Bearer key-alice" \
  -H "Content-Type: application/json" -d "{\"messages\":[{\"role\":\"user\",\"content\":\"f-$RANDOM\"}]}" \
  | grep -iE "^HTTP|x-conduit-provider" | tr -d '\r' | paste -sd' ' -; }
fail() { curl -s -X POST localhost:$1/admin/fail -H "Content-Type: application/json" -d "{\"on\":$2}" >/dev/null; }
echo "== A healthy";   call; call
echo "== A goes down"; fail 9000 true; for i in 1 2 3 4; do call; done
echo "== both down -> fast 503"; fail 9001 true; call; fail 9001 false
echo "== A recovers; wait 11s for the breaker's half-open probe"; fail 9000 false; sleep 11; call; call
