"""Runs the real Ollama code path against a tiny fake Ollama server."""
import threading
import time

import pytest
import uvicorn

from app import db, engine, llm
from app.config import settings
from tests.mock_ollama import app as mock_app

PORT = 11499


@pytest.fixture(scope="module")
def ollama_server():
    server = uvicorn.Server(uvicorn.Config(mock_app, host="127.0.0.1", port=PORT, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    old = settings.ollama_base_url
    settings.ollama_base_url = f"http://127.0.0.1:{PORT}"
    llm.OllamaProvider._cache = None
    yield
    server.should_exit = True
    thread.join(3)
    settings.ollama_base_url = old
    llm.OllamaProvider._cache = None


async def test_auto_prefers_small_model_and_hides_embeddings(ollama_server):
    models = [m["label"] for m in await llm.available_models()]
    assert "nomic-embed-text:latest" not in models and "llama3.2:3b" in models
    r = await llm.resolve("auto")
    assert (r.debater_model, r.judge_model, r.simulated) == ("llama3.2:3b", "qwen2.5:3b", False)
    assert r.note == "judge: qwen2.5:3b"


async def test_full_debate_through_ollama(ollama_server):
    r = await llm.resolve("auto")
    did = db.create_debate("Should a 5-person startup use microservices?", 1, "auto")
    events = []

    async def emit(e):
        events.append(e)

    await engine.run_debate(db.get_debate(did), r, emit)
    d = db.get_debate(did)
    assert d["status"] == "done" and len(d["messages"]) == 4
    assert d["verdict"]["answer"] == "Not now" and d["verdict"]["confidence"] == 78  # fenced JSON was parsed
    assert d["tokens"] > 0 and "**" not in d["messages"][0]["content"]
    assert any(e["type"] == "turn.delta" for e in events)


async def test_unknown_model_gives_a_helpful_message(ollama_server):
    with pytest.raises(llm.ProviderError) as e:
        await llm.resolve("ollama:nope")
    assert "ollama pull nope" in str(e.value)


async def test_ollama_not_running_gives_a_helpful_message():
    old = settings.ollama_base_url
    settings.ollama_base_url = "http://127.0.0.1:9"
    llm.OllamaProvider._cache = None
    try:
        with pytest.raises(llm.ProviderError) as e:
            await llm.resolve("ollama:llama3.2:3b")
        assert "Cannot reach Ollama" in str(e.value)
        with pytest.raises(llm.ProviderError):
            async for _ in llm.ollama.stream("x", [{"role": "user", "content": "hi"}]):
                pass
        r = await llm.resolve("auto")  # nothing available -> Demo, never a crash
        assert r.simulated
    finally:
        settings.ollama_base_url = old
        llm.OllamaProvider._cache = None
