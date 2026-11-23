"""Mini benchmark: debate vs three simple baselines on maths word problems."""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections import Counter
from typing import Any

from . import db, engine
from .engine import Usage, _call
from .llm import ProviderError, Resolved

QUESTIONS: list[tuple[str, float]] = [
    ("A shop sells pens in packs of 6 for 24 rupees. How many rupees do 15 pens cost?", 60),
    ("A train travels 60 km each hour. It runs for 2.5 hours and then 90 km more. How many km is that in total?", 240),
    ("Riya had 48 stickers. She gave a third of them to her brother and then bought 9 more. How many stickers does she have now?", 41),
    ("A classroom has 7 rows of 8 desks. 12 desks are broken. How many desks still work?", 44),
    ("Tom is 4 years older than twice his sister's age. His sister is 9. How old is Tom?", 22),
]

METHODS = [
    {"id": "direct", "label": "Direct answer", "sub": "1 call per question"},
    {"id": "step", "label": "Step by step", "sub": "1 call, reasons first"},
    {"id": "majority", "label": "Majority vote", "sub": "3 samples, most common wins"},
    {"id": "courtroom", "label": "Agent Courtroom", "sub": "3 agents + judge"},
]

_RUNS: dict[str, dict[str, Any]] = {}
_TASKS: dict[str, asyncio.Task] = {}


def extract_number(text: str) -> float | None:
    if not text:
        return None
    m = re.findall(r"answer\s*[:=]?\s*\$?\s*(-?\d[\d,]*(?:\.\d+)?)", text, flags=re.I)
    pool = m or re.findall(r"-?\d[\d,]*(?:\.\d+)?", text)
    if not pool:
        return None
    try:
        return float(pool[-1].replace(",", ""))
    except ValueError:
        return None


def is_correct(predicted: float | None, truth: float) -> bool:
    return predicted is not None and abs(predicted - truth) < 1e-6


def _system(kind: str) -> str:
    if kind == "direct":
        return "Solve the maths word problem. Reply with ONLY the final number, nothing else."
    return "Solve the maths word problem step by step, briefly (at most 60 words). End with 'Answer: <number>'."


async def _single(resolved: Resolved, question: str, kind: str, temperature: float, usage: Usage) -> float | None:
    messages = [{"role": "system", "content": _system(kind)}, {"role": "user", "content": question}]
    raw = await _call(resolved.debater, resolved.debater_model, messages, temperature=temperature,
                      max_tokens=20 if kind == "direct" else 160, usage=usage)
    return extract_number(raw)


async def answer_with(method: str, resolved: Resolved, question: str, usage: Usage) -> float | None:
    if method == "direct":
        return await _single(resolved, question, "direct", 0.0, usage)
    if method == "step":
        return await _single(resolved, question, "step", 0.0, usage)
    if method == "majority":
        votes = []
        for _ in range(3):
            v = await _single(resolved, question, "step", 0.7, usage)
            if v is not None:
                votes.append(v)
        return Counter(votes).most_common(1)[0][0] if votes else None
    result = await engine.run_debate({"question": question, "rounds": 1, "id": None}, resolved, persist=False, mode="qa")
    if not result:
        return None
    usage.add(result["usage"].prompt, result["usage"].completion)
    return extract_number(str(result["verdict"].get("final_answer") or ""))


def _blank(run_id: str, model_label: str) -> dict[str, Any]:
    return {
        "id": run_id, "status": "running", "model": model_label, "created_at": time.time(),
        "total": len(QUESTIONS), "done": 0, "current": "Starting...",
        "methods": [{**m, "correct": 0, "answered": 0, "tokens": 0, "seconds": 0.0} for m in METHODS],
        "error": None,
    }


def snapshot(run: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in run.items() if k != "created_at"} | {"questions": len(QUESTIONS)}


def get_latest(user_name: str | None = None) -> dict[str, Any] | None:
    if _RUNS:
        matching = [r for r in _RUNS.values() if not user_name or r.get("user_name") == user_name]
        if matching:
            run = max(matching, key=lambda r: r["created_at"])
            return snapshot(run)
    saved = db.latest_benchmark(user_name=user_name)
    return saved


def is_running() -> bool:
    return any(t for t in _TASKS.values() if not t.done())


async def _run(run: dict[str, Any], resolved: Resolved) -> None:
    run_id = run["id"]
    try:
        for qi, (question, truth) in enumerate(QUESTIONS, start=1):
            for m in run["methods"]:
                run["current"] = f"Question {qi} of {len(QUESTIONS)}  ...  {m['label']}"
                usage = Usage()
                predicted = await answer_with(m["id"], resolved, question, usage)
                m["answered"] += 1
                m["correct"] += 1 if is_correct(predicted, truth) else 0
                m["tokens"] += usage.tokens
                m["seconds"] = round(m["seconds"] + usage.seconds, 1)
            run["done"] = qi
        run["status"] = "done"
        run["current"] = "Finished"
    except asyncio.CancelledError:
        run["status"] = "cancelled"
        run["current"] = "Stopped"
        raise
    except ProviderError as e:
        run["status"] = "failed"
        run["error"] = str(e)
        run["current"] = "Stopped"
    except Exception as e:
        run["status"] = "failed"
        run["error"] = f"Something went wrong: {e.__class__.__name__}"
        run["current"] = "Stopped"
    finally:
        db.save_benchmark(run_id, run["status"], run["model"], snapshot(run), run["created_at"], user_name=run.get("user_name"))


def start(resolved: Resolved, model_label: str, user_name: str | None = None) -> dict[str, Any]:
    if resolved.simulated:
        raise ProviderError("Benchmarks need a real model. Start Ollama and pull a model, or set a cloud model in backend/.env.")
    if is_running():
        raise ProviderError("A benchmark is already running.")
    run_id = uuid.uuid4().hex[:12]
    run = _blank(run_id, model_label)
    run["user_name"] = user_name
    _RUNS.clear()
    _RUNS[run_id] = run
    _TASKS[run_id] = asyncio.create_task(_run(run, resolved))
    return snapshot(run)


def cancel() -> bool:
    for t in _TASKS.values():
        if not t.done():
            t.cancel()
            return True
    return False
