"""The debate engine: runs the rounds, streams events, asks the Judge for a verdict."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from typing import Any, Awaitable, Callable

import httpx

from . import db, prompts
from .config import settings
from .llm import ProviderError, Resolved, estimate_tokens

log = logging.getLogger("courtroom")

Emit = Callable[[dict], Awaitable[None]]

TEMPERATURE = {"advocate": 0.7, "critic": 0.7, "risk": 0.5, "evidence": 0.2}


class ClientGone(Exception):
    """The browser closed the connection."""


class Usage:
    def __init__(self) -> None:
        self.prompt = 0
        self.completion = 0
        self.started = time.monotonic()

    def add(self, prompt: int | None, completion: int | None) -> None:
        self.prompt += prompt or 0
        self.completion += completion or 0

    @property
    def tokens(self) -> int:
        return self.prompt + self.completion

    @property
    def cost(self) -> float:
        return (self.prompt * settings.price_in_per_1m + self.completion * settings.price_out_per_1m) / 1_000_000

    @property
    def seconds(self) -> float:
        return time.monotonic() - self.started

    def event(self) -> dict:
        return {"type": "usage.updated", "tokens": self.tokens, "cost": round(self.cost, 4), "seconds": round(self.seconds, 1)}


# --------------------------------------------------------------------- text helpers
def classify_evidence(text: str) -> str:
    lower = (text or "").lower()
    if "unsupported" in lower:
        return "unsupported"
    if "contradicted" in lower:
        return "contradicted"
    if "supported" in lower:
        return "supported"
    return "unclear"


def tidy(text: str, limit: int | None = None) -> str:
    if limit is None:
        limit = 650 if getattr(settings, "answer_detail", "brief") == "detailed" else 260
    t = re.sub(r"[*`#]+", "", text or "")
    t = re.sub(r"\s+", " ", t).strip().strip('"').strip()
    t = re.sub(r"^(advocate|critic|risk analyst|risk|evidence agent|evidence|judge)\s*[:\-]\s*", "", t, flags=re.I)
    if len(t) > limit:
        cut = max(t.rfind(". ", 0, limit), t.rfind("! ", 0, limit), t.rfind("? ", 0, limit))
        t = t[: cut + 1] if cut > 40 else t[:limit].rsplit(" ", 1)[0] + "..."
    if t and t[-1] not in ".!?\"')" and not re.search(r"answer:\s*-?[\d.,]+$", t, flags=re.I):
        cut = max(t.rfind(". "), t.rfind("! "), t.rfind("? "))
        if cut > 10:
            t = t[: cut + 1]
    return t


def _extract_json(text: str) -> Any:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    for candidate in (t, t[t.find("{"): t.rfind("}") + 1] if "{" in t and "}" in t else ""):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _num(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def parse_verdict(text: str) -> dict | None:
    obj = _extract_json(text)
    if not isinstance(obj, dict):
        return None
    answer = str(obj.get("answer", "")).strip()[:40]
    summary = str(obj.get("summary", "")).strip()[:120]
    if not answer and not summary:
        return None
    scores = obj.get("scores") if isinstance(obj.get("scores"), dict) else {}
    return {
        "answer": answer or "See summary",
        "summary": summary or "No summary given.",
        "confidence": int(round(_num(obj.get("confidence"), 50, 0, 100))),
        "scores": {k: round(_num(scores.get(k), 5, 0, 10), 1) for k in ("advocate", "critic", "evidence", "risk")},
    }


def fallback_verdict() -> dict:
    return {
        "answer": "Unclear",
        "summary": "The judge reply could not be read.",
        "confidence": 50,
        "scores": {"advocate": 5, "critic": 5, "evidence": 5, "risk": 5},
    }


def parse_final_answer(text: str) -> str | None:
    obj = _extract_json(text)
    if isinstance(obj, dict) and obj.get("final_answer") is not None:
        return str(obj["final_answer"])
    return None


# --------------------------------------------------------------------- model call
async def _call(provider, model, messages, *, temperature, max_tokens, usage: Usage, json_mode=False, on_text=None) -> str:
    parts: list[str] = []
    reported = False
    async for d in provider.stream(model, messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode):
        if d.text:
            parts.append(d.text)
            if on_text:
                await on_text(d.text)
        if d.prompt_tokens is not None or d.completion_tokens is not None:
            usage.add(d.prompt_tokens, d.completion_tokens)
            reported = True
    text = "".join(parts)
    if not reported:  # provider gave no counts: estimate
        usage.add(sum(estimate_tokens(m["content"]) for m in messages), estimate_tokens(text))
    return text


async def evidence_snippets(question: str) -> str:
    if not settings.enable_wikipedia:
        return ""
    query = " ".join(re.findall(r"[A-Za-z0-9\-]+", question)[:8])
    try:
        async with httpx.AsyncClient(timeout=3.0, headers={"User-Agent": "AgentCourtroom/0.1"}) as c:
            r = await c.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 2},
            )
            items = r.json()["query"]["search"]
        return "\n".join(f"- {i['title']}: {re.sub('<[^>]+>', '', i['snippet'])}" for i in items)
    except Exception:
        return ""


async def _noop(_: dict) -> None:
    return None


# --------------------------------------------------------------------- the debate
async def run_debate(debate: dict, resolved: Resolved, emit: Emit = _noop, *, persist: bool = True, mode: str = "opinion") -> dict | None:
    question, rounds, did = debate["question"], int(debate["rounds"]), debate.get("id")
    usage = Usage()
    first = random.choice(["advocate", "critic"])
    second = "critic" if first == "advocate" else "advocate"
    order = [first, second, "risk", "evidence"] if mode == "opinion" else ["advocate", "critic", "evidence"]

    def save(**fields: Any) -> None:
        if persist and did:
            db.update_debate(did, **fields)

    def finish(status: str, **extra: Any) -> None:
        save(status=status, finished_at=time.time(), tokens=usage.tokens, cost=round(usage.cost, 6), seconds=round(usage.seconds, 1), **extra)

    save(status="running", first_speaker=first, judge_model=resolved.judge_model, note=resolved.note)
    transcript: list[dict] = []
    try:
        await emit({"type": "debate.started", "debate_id": did, "rounds": rounds, "first_speaker": first,
                    "note": resolved.note, "simulated": resolved.simulated})
        idx = 0
        for r in range(1, rounds + 1):
            for agent in order:
                await emit({"type": "turn.started", "round": r, "agent": agent})
                snippets = await evidence_snippets(question) if agent == "evidence" else ""
                messages = prompts.turn_messages(agent, mode, question, transcript, r, rounds, snippets)

                async def on_text(t: str, _r=r, _a=agent) -> None:
                    await emit({"type": "turn.delta", "round": _r, "agent": _a, "text": t})

                before_tokens = usage.tokens
                raw = await _call(
                    resolved.debater,
                    resolved.debater_model,
                    messages,
                    temperature=TEMPERATURE[agent],
                    max_tokens=130 if mode == "qa" else (180 if getattr(settings, "answer_detail", "brief") == "detailed" else 80),
                    usage=usage,
                    on_text=on_text,
                )
                text = tidy(raw) or "(no reply)"
                msg_tokens = max(0, usage.tokens - before_tokens)
                label = classify_evidence(text) if agent == "evidence" else None
                transcript.append({"agent": agent, "round": r, "text": text, "tokens": msg_tokens, "evidence_label": label})
                if persist and did:
                    db.add_message(did, idx, r, agent, text, resolved.debater_model, tokens=msg_tokens, evidence_label=label)
                idx += 1
                await emit({"type": "turn.completed", "round": r, "agent": agent, "text": text})
                await emit(usage.event())

        await emit({"type": "judge.started"})
        verdict = await _judge(resolved, question, transcript, mode, usage)
        await emit(usage.event())

        if mode == "opinion":
            verdict["note"] = resolved.note
            await emit({"type": "verdict.ready", **verdict})
        finish("done", verdict=verdict)
        await emit({"type": "debate.completed", "status": "done"})
        return {"verdict": verdict, "usage": usage, "transcript": transcript}

    except asyncio.CancelledError:
        finish("cancelled")
        raise
    except ClientGone:
        finish("cancelled")
        return None
    except ProviderError as e:
        finish("failed")
        await _safe_emit(emit, {"type": "debate.error", "message": str(e)})
        return None
    except Exception as e:  # a bug: log it, tell the user, never crash the server
        log.exception("debate failed")
        finish("failed")
        await _safe_emit(emit, {"type": "debate.error", "message": f"Something went wrong: {e.__class__.__name__}"})
        return None


async def _safe_emit(emit: Emit, event: dict) -> None:
    try:
        await emit(event)
    except Exception:
        pass


async def _judge(resolved: Resolved, question: str, transcript: list[dict], mode: str, usage: Usage) -> dict:
    messages = prompts.judge_messages(mode, question, transcript)
    raw = await _call(resolved.judge, resolved.judge_model, messages, temperature=0.2, max_tokens=220, usage=usage, json_mode=True)
    if mode == "qa":
        answer = parse_final_answer(raw)
        if answer is None:  # one repair attempt
            messages = messages + [{"role": "assistant", "content": raw},
                                   {"role": "user", "content": 'Return ONLY valid JSON like {"final_answer": 42}.'}]
            raw = await _call(resolved.judge, resolved.judge_model, messages, temperature=0.0, max_tokens=60, usage=usage, json_mode=True)
            answer = parse_final_answer(raw)
        return {"final_answer": answer}
    verdict = parse_verdict(raw)
    if verdict is None:  # one repair attempt
        messages = messages + [{"role": "assistant", "content": raw},
                               {"role": "user", "content": "Return ONLY valid JSON with the keys answer, summary, confidence and scores."}]
        raw = await _call(resolved.judge, resolved.judge_model, messages, temperature=0.0, max_tokens=220, usage=usage, json_mode=True)
        verdict = parse_verdict(raw)
    return verdict or fallback_verdict()
