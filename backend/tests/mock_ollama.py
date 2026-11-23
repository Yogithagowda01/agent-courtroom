"""A tiny fake Ollama server, only for testing the real Ollama code path."""
import asyncio
import json
import re

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from app.benchmark import QUESTIONS

TRUTH = {q: a for q, a in QUESTIONS}
app = FastAPI()

@app.get('/api/tags')
async def tags():
    return {"models": [{"name": "llama3.2:3b"}, {"name": "qwen2.5:3b"}, {"name": "nomic-embed-text:latest"}]}

@app.post('/api/chat')
async def chat(req: Request):
    body = await req.json()
    system, user = body['messages'][0]['content'], body['messages'][-1]['content']
    q = next((k for k in TRUTH if k in user), None)
    truth = TRUTH[q] if q else 0
    role = re.search(r'\[ROLE:(\w+)\]', system)
    role = role.group(1) if role else None
    if role == 'judge' and '[MODE:qa]' in system:
        text = json.dumps({"final_answer": truth})
    elif role == 'judge':
        text = '```json\n' + json.dumps({"answer": "Not now", "summary": "Start with a modular monolith and revisit once the team has grown.", "confidence": 78, "scores": {"advocate": 6, "critic": 8, "evidence": 7, "risk": 5}}) + '\n```'
    elif role and '[MODE:qa]' in system:
        text = f"Checking the steps. Answer: {truth:g}"
    elif role:
        text = f"**{role.title()}:** A short, specific point about the question, written by the {role} agent."
    elif 'ONLY the final number' in system:
        text = str(truth + 1 if q == QUESTIONS[0][0] else truth)
    else:
        text = f"Working it out. Answer: {truth:g}"
    async def gen():
        for w in text.split(' '):
            yield json.dumps({"message": {"role": "assistant", "content": w + ' '}, "done": False}) + "\n"
            await asyncio.sleep(0.005)
        yield json.dumps({"done": True, "prompt_eval_count": 60, "eval_count": len(text.split())}) + "\n"
    return StreamingResponse(gen(), media_type='application/x-ndjson')
