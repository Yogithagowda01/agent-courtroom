"""Small SQLite layer (standard library only)."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

CREATE TABLE IF NOT EXISTS debates (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    rounds INTEGER NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    first_speaker TEXT,
    judge_model TEXT,
    note TEXT,
    verdict_json TEXT,
    report_json TEXT,
    tokens INTEGER DEFAULT 0,
    cost REAL DEFAULT 0,
    seconds REAL DEFAULT 0,
    created_at REAL NOT NULL,
    finished_at REAL,
    user_name TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    debate_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    round INTEGER NOT NULL,
    agent TEXT NOT NULL,
    model TEXT,
    content TEXT NOT NULL,
    tokens INTEGER,
    evidence_label TEXT,
    FOREIGN KEY (debate_id) REFERENCES debates(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_debate ON messages(debate_id, idx);
CREATE TABLE IF NOT EXISTS benchmarks (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    status TEXT NOT NULL,
    model TEXT NOT NULL,
    data_json TEXT NOT NULL,
    user_name TEXT
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, "
        "password_hash TEXT NOT NULL, created_at REAL NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")

    debates_cols = {row["name"] for row in conn.execute("PRAGMA table_info(debates)").fetchall()}
    if debates_cols and "report_json" not in debates_cols:
        conn.execute("ALTER TABLE debates ADD COLUMN report_json TEXT")
    if debates_cols and "user_name" not in debates_cols:
        conn.execute("ALTER TABLE debates ADD COLUMN user_name TEXT")

    messages_cols = {row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if messages_cols and "tokens" not in messages_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN tokens INTEGER")
    if messages_cols and "evidence_label" not in messages_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN evidence_label TEXT")

    benchmarks_cols = {row["name"] for row in conn.execute("PRAGMA table_info(benchmarks)").fetchall()}
    if benchmarks_cols and "user_name" not in benchmarks_cols:
        conn.execute("ALTER TABLE benchmarks ADD COLUMN user_name TEXT")


def init() -> None:
    with connect() as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.executescript(SCHEMA)
        _migrate(c)
        # A debate left "running" by a crash can never finish: mark it.
        c.execute("UPDATE debates SET status = 'failed' WHERE status IN ('running', 'pending')")
        c.execute("UPDATE benchmarks SET status = 'failed' WHERE status = 'running'")


# ---------------------------------------------------------------- users
def create_user(username: str, password_hash: str) -> dict[str, Any]:
    user_id = uuid.uuid4().hex[:12]
    now = time.time()
    with connect() as c:
        c.execute(
            "INSERT INTO users (id, username, password_hash, created_at) VALUES (?,?,?,?)",
            (user_id, username, password_hash, now),
        )
    return {"id": user_id, "username": username, "created_at": now}


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------- debates
def create_debate(question: str, rounds: int, model: str, user_name: str | None = None) -> str:
    debate_id = uuid.uuid4().hex[:12]
    with connect() as c:
        c.execute(
            "INSERT INTO debates (id, question, rounds, model, status, created_at, user_name) VALUES (?,?,?,?,?,?,?)",
            (debate_id, question, rounds, model, "pending", time.time(), user_name),
        )
    return debate_id


def get_debate(debate_id: str, user_name: str | None = None) -> dict[str, Any] | None:
    with connect() as c:
        if user_name is not None:
            row = c.execute(
                "SELECT * FROM debates WHERE id = ? AND (user_name = ? OR user_name IS NULL)",
                (debate_id, user_name),
            ).fetchone()
        else:
            row = c.execute("SELECT * FROM debates WHERE id = ?", (debate_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        msgs = c.execute(
            "SELECT round, agent, content, model, tokens, evidence_label FROM messages WHERE debate_id = ? ORDER BY idx", (debate_id,)
        ).fetchall()
    d["messages"] = [dict(m) for m in msgs]
    d["verdict"] = json.loads(d["verdict_json"]) if d.get("verdict_json") else None
    d["report"] = json.loads(d["report_json"]) if d.get("report_json") else None
    return d


def list_debates(user_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with connect() as c:
        if user_name is not None:
            rows = c.execute(
                "SELECT id, question, rounds, model, status, judge_model, note, verdict_json, tokens, cost, seconds, created_at "
                "FROM debates WHERE status != 'pending' AND (user_name = ? OR user_name IS NULL) ORDER BY created_at DESC LIMIT ?",
                (user_name, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id, question, rounds, model, status, judge_model, note, verdict_json, tokens, cost, seconds, created_at "
                "FROM debates WHERE status != 'pending' ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        v = json.loads(d.pop("verdict_json")) if d.get("verdict_json") else None
        d["answer"] = v["answer"] if v else None
        d["confidence"] = v["confidence"] if v else None
        out.append(d)
    return out


def delete_debate(debate_id: str, user_name: str | None = None) -> bool:
    with connect() as c:
        if user_name is not None:
            cur = c.execute(
                "DELETE FROM debates WHERE id = ? AND (user_name = ? OR user_name IS NULL)",
                (debate_id, user_name),
            )
        else:
            cur = c.execute("DELETE FROM debates WHERE id = ?", (debate_id,))
        return cur.rowcount > 0


def update_debate(debate_id: str, **fields: Any) -> None:
    if not fields:
        return
    if "verdict" in fields:
        fields["verdict_json"] = json.dumps(fields.pop("verdict"))
    if "report" in fields:
        fields["report_json"] = json.dumps(fields.pop("report"))
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE debates SET {cols} WHERE id = ?", (*fields.values(), debate_id))


def add_message(debate_id: str, idx: int, round_no: int, agent: str, content: str, model: str | None, tokens: int | None = None, evidence_label: str | None = None) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO messages (debate_id, idx, round, agent, model, content, tokens, evidence_label) VALUES (?,?,?,?,?,?,?,?)",
            (debate_id, idx, round_no, agent, model, content, tokens, evidence_label),
        )


# ---------------------------------------------------------------- benchmarks
def save_benchmark(run_id: str, status: str, model: str, data: dict[str, Any], created_at: float, user_name: str | None = None) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO benchmarks (id, created_at, status, model, data_json, user_name) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET status = excluded.status, data_json = excluded.data_json, user_name = excluded.user_name",
            (run_id, created_at, status, model, json.dumps(data), user_name),
        )


def latest_benchmark(user_name: str | None = None) -> dict[str, Any] | None:
    with connect() as c:
        if user_name is not None:
            row = c.execute("SELECT * FROM benchmarks WHERE user_name = ? ORDER BY created_at DESC LIMIT 1", (user_name,)).fetchone()
        else:
            row = c.execute("SELECT * FROM benchmarks ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        return None
    data = json.loads(row["data_json"])
    data.update({"id": row["id"], "status": row["status"], "model": row["model"]})
    return data
