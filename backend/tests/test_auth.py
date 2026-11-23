"""Tests for Register and Login system: auth endpoints, cookies, rate limiting, and user isolation."""
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import db
from app.auth import COOKIE_NAME, login_limiter
from app.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    login_limiter._failures.clear()
    yield
    login_limiter._failures.clear()


def test_register_success():
    client = TestClient(app)
    res = client.post("/api/auth/register", json={"username": "alice", "password": "password123"})
    assert res.status_code == 201
    data = res.json()
    assert "user" in data
    assert data["user"]["username"] == "alice"
    assert "id" in data["user"]
    # Check session cookie set
    assert COOKIE_NAME in res.cookies


def test_register_validation():
    client = TestClient(app)
    # Short username
    r1 = client.post("/api/auth/register", json={"username": "al", "password": "password123"})
    assert r1.status_code == 400
    assert "between 3 and 30" in r1.json()["detail"]

    # Long username
    r2 = client.post("/api/auth/register", json={"username": "a" * 31, "password": "password123"})
    assert r2.status_code == 400

    # Short password
    r3 = client.post("/api/auth/register", json={"username": "bob", "password": "short"})
    assert r3.status_code == 400
    assert "at least 8" in r3.json()["detail"]


def test_register_duplicate_username():
    client = TestClient(app)
    res1 = client.post("/api/auth/register", json={"username": "charlie", "password": "password123"})
    assert res1.status_code == 201

    res2 = client.post("/api/auth/register", json={"username": "charlie", "password": "anotherpassword"})
    assert res2.status_code == 400
    assert "already taken" in res2.json()["detail"].lower()


def test_login_wrong_credentials_same_message():
    client = TestClient(app)
    client.post("/api/auth/register", json={"username": "dan", "password": "password123"})

    # Wrong password
    r_wrong_pw = client.post("/api/auth/login", json={"username": "dan", "password": "wrongpassword"})
    assert r_wrong_pw.status_code == 401
    pw_msg = r_wrong_pw.json()["detail"]

    # Wrong username
    r_wrong_user = client.post("/api/auth/login", json={"username": "unknown_user", "password": "password123"})
    assert r_wrong_user.status_code == 401
    user_msg = r_wrong_user.json()["detail"]

    # Friendly message is identical for both
    assert pw_msg == user_msg == "Invalid username or password."


def test_login_success_and_me():
    client = TestClient(app)
    client.post("/api/auth/register", json={"username": "eve", "password": "password123"})

    # Log in
    login_res = client.post("/api/auth/login", json={"username": "eve", "password": "password123"})
    assert login_res.status_code == 200
    assert COOKIE_NAME in login_res.cookies

    # GET /api/auth/me
    me_res = client.get("/api/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["user"]["username"] == "eve"


def test_protected_routes_return_401():
    client = TestClient(app)  # fresh client without cookies

    # /api/health is exempt
    assert client.get("/api/health").status_code == 200

    # Protected routes must return 401
    assert client.get("/api/models").status_code == 401
    assert client.get("/api/debates").status_code == 401
    assert client.post("/api/debates", json={"question": "Test question here?", "rounds": 2, "model": "demo"}).status_code == 401
    assert client.get("/api/debates/some-id").status_code == 401
    assert client.delete("/api/debates/some-id").status_code == 401
    assert client.post("/api/debates/some-id/report").status_code == 401
    assert client.get("/api/debates/some-id/report/download?format=docx").status_code == 401
    assert client.post("/api/benchmarks", json={"model": "demo"}).status_code == 401
    assert client.get("/api/benchmarks/latest").status_code == 401
    assert client.post("/api/benchmarks/cancel").status_code == 401


def test_websocket_rejected_without_cookie():
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/debates/some-debate-id"):
            pass
    assert exc.value.code == 1008


def test_each_user_sees_only_own_debates():
    # User 1: Frank
    client1 = TestClient(app)
    client1.post("/api/auth/register", json={"username": "frank", "password": "password123"})
    did1 = client1.post("/api/debates", json={"question": "Should Frank use microservices?", "rounds": 2, "model": "demo"}).json()["id"]
    db.update_debate(did1, status="done")

    # User 2: Grace
    client2 = TestClient(app)
    client2.post("/api/auth/register", json={"username": "grace", "password": "password123"})
    did2 = client2.post("/api/debates", json={"question": "Should Grace use microservices?", "rounds": 2, "model": "demo"}).json()["id"]
    db.update_debate(did2, status="done")

    # Frank lists debates: sees Frank's debate, not Grace's
    frank_debates = [d["id"] for d in client1.get("/api/debates").json()["debates"]]
    assert did1 in frank_debates
    assert did2 not in frank_debates

    # Grace lists debates: sees Grace's debate, not Frank's
    grace_debates = [d["id"] for d in client2.get("/api/debates").json()["debates"]]
    assert did2 in grace_debates
    assert did1 not in grace_debates

    # Grace cannot open Frank's debate
    assert client2.get(f"/api/debates/{did1}").status_code == 404

    # Grace cannot delete Frank's debate
    assert client2.delete(f"/api/debates/{did1}").status_code == 404

    # Frank can open and delete Frank's debate
    assert client1.get(f"/api/debates/{did1}").status_code == 200
    assert client1.delete(f"/api/debates/{did1}").status_code == 200
    assert client1.get(f"/api/debates/{did1}").status_code == 404


def test_logout():
    client = TestClient(app)
    client.post("/api/auth/register", json={"username": "heidi", "password": "password123"})
    assert client.get("/api/auth/me").status_code == 200

    # Logout
    logout_res = client.post("/api/auth/logout")
    assert logout_res.status_code == 200

    # Cookie deleted or empty
    assert client.get("/api/auth/me").status_code == 401


def test_login_rate_limiting():
    client = TestClient(app)
    username = "target_user"

    # 5 failed attempts allowed
    for _ in range(5):
        res = client.post("/api/auth/login", json={"username": username, "password": "wrongpassword"})
        assert res.status_code == 401
        assert res.json()["detail"] == "Invalid username or password."

    # 6th attempt is rate-limited
    res_limited = client.post("/api/auth/login", json={"username": username, "password": "wrongpassword"})
    assert res_limited.status_code == 429
    assert "Too many failed login attempts" in res_limited.json()["detail"]


def test_migration_with_old_database():
    """Verify safe migration of an old database without users table or user_name columns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        old_db_path = str(Path(tmpdir) / "v1_courtroom.db")
        conn = sqlite3.connect(old_db_path)
        conn.row_factory = sqlite3.Row

        # Create original legacy schema
        conn.executescript("""
        CREATE TABLE debates (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            rounds INTEGER NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL,
            first_speaker TEXT,
            judge_model TEXT,
            note TEXT,
            verdict_json TEXT,
            tokens INTEGER DEFAULT 0,
            cost REAL DEFAULT 0,
            seconds REAL DEFAULT 0,
            created_at REAL NOT NULL,
            finished_at REAL
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            debate_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            round INTEGER NOT NULL,
            agent TEXT NOT NULL,
            model TEXT,
            content TEXT NOT NULL
        );
        CREATE TABLE benchmarks (
            id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            status TEXT NOT NULL,
            model TEXT NOT NULL,
            data_json TEXT NOT NULL
        );
        """)
        conn.execute(
            "INSERT INTO debates (id, question, rounds, model, status, created_at) "
            "VALUES ('legacy1', 'Legacy question?', 1, 'demo', 'done', 1000)"
        )
        conn.commit()
        conn.close()

        # Run migration on the old DB
        orig_db_path = settings.db_path
        try:
            settings.db_path = old_db_path
            db.init()

            # Verify users table exists
            u = db.create_user("migrated_user", "some_hash")
            assert u["username"] == "migrated_user"

            # Verify legacy debate still exists
            d = db.get_debate("legacy1")
            assert d is not None
            assert d["question"] == "Legacy question?"

            # Verify user_name column is queryable
            debates = db.list_debates(user_name="migrated_user")
            assert len(debates) >= 1  # includes legacy debate since user_name IS NULL
        finally:
            settings.db_path = orig_db_path
