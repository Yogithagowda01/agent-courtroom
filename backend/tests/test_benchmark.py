import asyncio
import json
import re

import pytest

from app import benchmark
from app.llm import Delta, Provider, Resolved

TRUTH = {q: a for q, a in benchmark.QUESTIONS}


class MathFake(Provider):
    """Answers correctly, except 'direct' mode gets the first question wrong."""

    async def stream(self, model, messages, *, temperature=0.7, max_tokens=120, json_mode=False):
        system, user = messages[0]["content"], messages[-1]["content"]
        question = next((q for q in TRUTH if q in user), None)
        truth = TRUTH[question] if question else 0
        if "[ROLE:judge]" in system:
            text = json.dumps({"final_answer": truth})
        elif "ONLY the final number" in system:
            text = str(truth + 1 if question == benchmark.QUESTIONS[0][0] else truth)
        else:
            text = f"Working it out. Answer: {truth:g}"
        yield Delta(text=text)
        yield Delta(prompt_tokens=20, completion_tokens=10)


def test_extract_number():
    assert benchmark.extract_number("so it is 1,250. Answer: 1,250") == 1250
    assert benchmark.extract_number("The total is 41 stickers") == 41
    assert benchmark.extract_number("no digits") is None


@pytest.mark.asyncio
async def test_benchmark_scores_methods():
    r = Resolved(MathFake(), "fake", MathFake(), "fake", False, "n")
    run = benchmark.start(r, "fake")
    await asyncio.wait_for(list(benchmark._TASKS.values())[0], timeout=10)
    latest = benchmark.get_latest()
    assert latest["status"] == "done" and latest["done"] == len(benchmark.QUESTIONS)
    by = {m["id"]: m for m in latest["methods"]}
    assert by["direct"]["correct"] == len(benchmark.QUESTIONS) - 1
    assert by["step"]["correct"] == by["majority"]["correct"] == by["courtroom"]["correct"] == len(benchmark.QUESTIONS)
    assert by["courtroom"]["tokens"] > by["direct"]["tokens"]


def test_demo_mode_is_rejected():
    from app import llm
    r = Resolved(llm.demo, "demo", llm.demo, "demo", True, "demo")
    with pytest.raises(llm.ProviderError):
        benchmark.start(r, "demo")
