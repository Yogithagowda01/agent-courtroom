import asyncio

import pytest

from app import db, engine
from app.llm import Resolved
from tests.fakes import FakeProvider


def resolved(p):
    return Resolved(p, "fake", p, "fake-judge", False, "judge: fake-judge")


def test_tidy_cleans_markdown_and_labels():
    assert engine.tidy("**Advocate:** It is *good*.\n\nReally.") == "It is good. Really."
    assert engine.tidy("A full sentence. Then a cut off frag") == "A full sentence."
    assert engine.tidy("") == ""


def test_parse_verdict_variants():
    ok = engine.parse_verdict('Sure!\n```json\n{"answer":"Yes","summary":"Go.","confidence":"90","scores":{"advocate":11}}\n```')
    assert ok["answer"] == "Yes" and ok["confidence"] == 90
    assert ok["scores"]["advocate"] == 10 and ok["scores"]["critic"] == 5
    assert engine.parse_verdict("not json at all") is None
    assert engine.parse_verdict('{"confidence": 40}') is None


@pytest.mark.asyncio
async def test_full_debate_events_and_persistence():
    provider = FakeProvider()
    did = db.create_debate("Should we adopt microservices now?", 2, "fake")
    events = []

    async def emit(e):
        events.append(e)

    result = await engine.run_debate(db.get_debate(did), resolved(provider), emit)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "debate.started" and kinds[-1] == "debate.completed"
    assert kinds.count("turn.started") == 8 and kinds.count("turn.completed") == 8
    assert kinds.count("verdict.ready") == 1 and "judge.started" in kinds
    assert provider.calls == 9  # 4 per round x 2 + 1 judge
    d = db.get_debate(did)
    assert d["status"] == "done" and len(d["messages"]) == 8
    assert d["verdict"]["answer"] == "Not now" and d["tokens"] > 0
    assert result["verdict"]["confidence"] == 80
    first_two = [m["agent"] for m in d["messages"][:2]]
    assert sorted(first_two) == ["advocate", "critic"]


@pytest.mark.asyncio
async def test_judge_garbage_uses_fallback():
    provider = FakeProvider(judge_text="I cannot comply")
    did = db.create_debate("Should we adopt microservices now?", 1, "fake")
    result = await engine.run_debate(db.get_debate(did), resolved(provider))
    assert result["verdict"]["answer"] == "Unclear"


@pytest.mark.asyncio
async def test_cancel_marks_cancelled():
    provider = FakeProvider(delay=0.02)
    did = db.create_debate("Should we adopt microservices now?", 5, "fake")
    task = asyncio.create_task(engine.run_debate(db.get_debate(did), resolved(provider)))
    await asyncio.sleep(0.15)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert db.get_debate(did)["status"] == "cancelled"


@pytest.mark.asyncio
async def test_provider_error_reports_and_fails():
    provider = FakeProvider(fail=True)
    did = db.create_debate("Should we adopt microservices now?", 1, "fake")
    events = []

    async def emit(e):
        events.append(e)

    result = await engine.run_debate(db.get_debate(did), resolved(provider), emit)
    assert result is None
    assert events[-1] == {"type": "debate.error", "message": "boom"}
    assert db.get_debate(did)["status"] == "failed"
