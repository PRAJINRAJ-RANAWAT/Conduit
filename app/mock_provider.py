"""A fake LLM. Lets us test Conduit without paying for real API calls.

Normal mode: sleeps a bit, echoes the prompt.
Eval mode (body has "eval_mode": true): a DETERMINISTIC classifier simulator. Its accuracy is a
hand-written function of the prompt's features (does it name the labels? how many examples?),
so prompt-optimisation can be tested without a real model. It shows the pipeline works; it says
nothing about real model quality.
"""
import asyncio
import hashlib

from fastapi import FastAPI, HTTPException

app = FastAPI()
state = {"fail": False}   # flip with POST /admin/fail to simulate an outage


@app.post("/admin/fail")
async def set_fail(body: dict):
    state["fail"] = bool(body["on"])
    return state


def eval_accuracy(prompt: str) -> int:
    """Percent of examples this prompt 'gets right', from its features."""
    p = prompt.lower()
    labels = "positive" in p and "negative" in p
    examples = min(p.count("example:"), 3)
    return 40 + 40 * labels + 5 * examples + 5 * ("one word" in p)


def eval_reply(body: dict) -> str:
    prompt = body["messages"][-1]["content"]
    expected = body["expected"]
    # Same prompt features + same example always give the same answer (hash, not random).
    features = f"{eval_accuracy(prompt)}|{body['messages'][-1]['content'][-80:]}"
    roll = int(hashlib.sha256(features.encode()).hexdigest(), 16) % 100
    if roll < eval_accuracy(prompt):
        return expected
    return "negative" if expected == "positive" else "positive"


@app.post("/v1/chat/completions")
async def chat(body: dict):
    if state["fail"]:
        raise HTTPException(500, "provider is down (simulated)")
    last = body["messages"][-1]["content"]
    if body.get("eval_mode"):
        reply = eval_reply(body)
        completion = 1
    else:
        await asyncio.sleep(0.2)  # pretend the model is thinking
        reply = f"echo: {last} " + "word " * (body.get("max_tokens", 50) // 2)  # length follows max_tokens
        completion = len(reply.split())
    return {
        "choices": [{"message": {"role": "assistant", "content": reply}}],
        "usage": {"prompt_tokens": len(last.split()), "completion_tokens": completion},
    }
