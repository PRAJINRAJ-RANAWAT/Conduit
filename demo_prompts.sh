#!/bin/bash
# Runs the optimiser over 5 versions of a sentiment prompt (needs gateway :8080 + mock LLM :9000).
curl -s -X POST localhost:8080/prompts/optimise -H "Authorization: Bearer key-alice" \
  -H "Content-Type: application/json" -d '{"epsilon": 0.1}' | python3 -c "
import sys, json
r = json.load(sys.stdin)
print('version  score  avg_input_tokens  cost/1k calls (ASSUMED prices)')
for v in r['all_versions']:
    tag = ' <- baseline' if v is r['all_versions'][0] else (' <- BEST' if v['version'] == r['best']['version'] else '')
    print('  v%d     %.2f   %5.1f             \$%.4f%s' % (v['version'], v['score'], v['avg_input_tokens'], v['cost_per_1k_calls_usd'], tag))
print('epsilon %.2f -> picked v%d, cost saved: %.1f%%' % (r['epsilon'], r['best']['version'], r['cost_saved_pct']))
print(r['notes'])"
