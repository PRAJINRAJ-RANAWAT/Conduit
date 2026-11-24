"""Prompt optimiser: find the cheapest prompt version that is still good enough.

1. Run every version over the golden set (20 labelled examples) through the LLM in eval mode.
2. Score = share of examples answered exactly right.
3. Keep versions with score >= baseline_score - epsilon. Pick the one with the fewest tokens.
"""
import json
import os
from pathlib import Path
import httpx

PROVIDER_URL = lambda: os.getenv("PROVIDER_URL", "http://localhost:9000")
GOLDEN = json.loads(Path(__file__).with_name("golden.json").read_text())
# ASSUMED prices (dollars per million tokens). Not a real provider's price list.
PRICE_IN, PRICE_OUT = 0.50, 1.50


def tokens(text: str) -> int:
    """Rough token count: one per word (documented approximation, not a real tokenizer)."""
    return len(text.split())


def score_one(output: str, expected: str) -> float:
    """The scorer: exact match after trimming and lowercasing."""
    return 1.0 if output.strip().lower() == expected else 0.0


def evaluate(template: str) -> dict:
    """Score one template on the golden set and measure its average cost."""
    hits, in_tokens = 0.0, 0
    for ex in GOLDEN:
        prompt = template.replace("{text}", ex["text"])
        r = httpx.post(f"{PROVIDER_URL()}/v1/chat/completions", timeout=30, json={
            "eval_mode": True, "expected": ex["expected"],
            "messages": [{"role": "user", "content": prompt}]}).json()
        hits += score_one(r["choices"][0]["message"]["content"], ex["expected"])
        in_tokens += r["usage"]["prompt_tokens"]
    avg_in = in_tokens / len(GOLDEN)
    cost_per_1k = (avg_in * PRICE_IN + 1 * PRICE_OUT) / 1_000_000 * 1000   # 1 output token
    return {"score": round(hits / len(GOLDEN), 3), "avg_input_tokens": round(avg_in, 1),
            "template_tokens": tokens(template.replace("{text}", "")),
            "cost_per_1k_calls_usd": round(cost_per_1k, 4)}


def optimise(versions: list[dict], epsilon: float) -> dict:
    """versions = [{version, template}, ...]; the first (lowest) version is the baseline."""
    results = [{"version": v["version"], **evaluate(v["template"])} for v in versions]
    baseline = results[0]
    good = [r for r in results if r["score"] >= baseline["score"] - epsilon]
    best = min(good, key=lambda r: (r["avg_input_tokens"], -r["score"]))
    saved = 100 * (1 - best["cost_per_1k_calls_usd"] / baseline["cost_per_1k_calls_usd"])
    return {"epsilon": epsilon, "baseline": baseline, "best": best, "all_versions": results,
            "cost_saved_pct": round(saved, 1),
            "notes": "Prices are ASSUMED ($0.50/M in, $1.50/M out); tokens ~ words; "
                     "quality comes from the deterministic mock eval mode, not a real model."}
