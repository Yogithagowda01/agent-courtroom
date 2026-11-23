import asyncio
import json
import re

from app.llm import Delta, Provider, ProviderError


class FakeProvider(Provider):
    """Scripted model used by the tests (no network)."""

    def __init__(self, delay=0.0, judge_text=None, fail=False):
        self.delay = delay
        self.calls = 0
        self.judge_text = judge_text
        self.fail = fail

    async def stream(self, model, messages, *, temperature=0.7, max_tokens=120, json_mode=False):
        self.calls += 1
        if self.fail:
            raise ProviderError("boom")
        system = messages[0]["content"]
        role = re.search(r"\[ROLE:(\w+)\]", system)
        role = role.group(1) if role else None
        if role == "judge":
            text = self.judge_text if self.judge_text is not None else json.dumps(
                {"answer": "Not now", "summary": "Start small.", "confidence": 80,
                 "scores": {"advocate": 6, "critic": 8, "evidence": 7, "risk": 5}})
        else:
            text = f"{role or 'solver'} says something short."
        for w in text.split(" "):
            yield Delta(text=w + " ")
            if self.delay:
                await asyncio.sleep(self.delay)
        yield Delta(prompt_tokens=10, completion_tokens=5)
