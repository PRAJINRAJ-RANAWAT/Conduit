"""A fake LLM. Lets us test Conduit without paying for real API calls."""
import asyncio
from fastapi import FastAPI

app = FastAPI()


@app.post("/v1/chat/completions")
async def chat(body: dict):
    await asyncio.sleep(0.2)  # pretend the model is thinking
    last = body["messages"][-1]["content"]
    reply = f"echo: {last} " + "word " * (body.get("max_tokens", 50) // 2)  # length follows max_tokens
    return {
        "choices": [{"message": {"role": "assistant", "content": reply}}],
        "usage": {"prompt_tokens": len(last.split()), "completion_tokens": len(reply.split())},
    }
