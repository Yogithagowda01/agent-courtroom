import time

from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app

client = TestClient(app)


def test_models_lists_auto_and_demo():
    ids = [m["id"] for m in client.get("/api/models").json()["models"]]
    assert ids[:2] == ["auto", "demo"]


def test_validation_errors():
    assert client.post("/api/debates", json={"question": "short", "rounds": 3, "model": "demo"}).status_code == 400
    assert client.post("/api/debates", json={"question": "Is this long enough to pass?", "rounds": 9, "model": "demo"}).status_code == 400
    r = client.post("/api/debates", json={"question": "Is this long enough to pass?", "rounds": 3, "model": "ollama:nope"})
    assert r.status_code == 400 and "Ollama" in r.json()["detail"]


def _run(model="demo", rounds=2):
    did = client.post("/api/debates", json={"question": "Should a 5-person startup use microservices?", "rounds": rounds, "model": model}).json()["id"]
    events = []
    with client.websocket_connect(f"/ws/debates/{did}") as ws:
        while True:
            e = ws.receive_json()
            events.append(e)
            if e["type"] in ("debate.completed", "debate.error"):
                break
    return did, events


def test_full_debate_over_websocket_and_history():
    did, events = _run(rounds=2)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "debate.started" and kinds[-1] == "debate.completed"
    verdict = next(e for e in events if e["type"] == "verdict.ready")
    assert verdict["note"] == "demo mode (simulated)" and 0 <= verdict["confidence"] <= 100
    d = client.get(f"/api/debates/{did}").json()
    assert d["status"] == "done" and len(d["messages"]) == 8 and d["verdict"]["answer"]
    assert any(x["id"] == did for x in client.get("/api/debates").json()["debates"])
    assert client.delete(f"/api/debates/{did}").status_code == 200
    assert client.get(f"/api/debates/{did}").status_code == 404


def test_cancel_over_websocket():
    settings.demo_word_delay = 0.02
    try:
        did = client.post("/api/debates", json={"question": "Should a 5-person startup use microservices?", "rounds": 5, "model": "demo"}).json()["id"]
        with client.websocket_connect(f"/ws/debates/{did}") as ws:
            while ws.receive_json()["type"] != "turn.started":
                pass
            ws.send_json({"type": "cancel"})
            last = None
            while True:
                last = ws.receive_json()
                if last["type"] == "debate.completed":
                    break
        assert last["status"] == "cancelled"
        time.sleep(0.1)
        assert db.get_debate(did)["status"] == "cancelled"
    finally:
        settings.demo_word_delay = 0.0


def test_started_debate_cannot_be_restarted():
    did, _ = _run(rounds=1)
    with client.websocket_connect(f"/ws/debates/{did}") as ws:
        assert ws.receive_json()["type"] == "debate.error"


def test_benchmark_needs_real_model():
    r = client.post("/api/benchmarks", json={"model": "demo"})
    assert r.status_code == 400 and "real model" in r.json()["detail"]
