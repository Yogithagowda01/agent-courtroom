import io
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app import db, report
from app.config import settings
from app.main import app

client = TestClient(app)


def _seed_debate(status="done", model="demo", question="Should a startup adopt microservices early?"):
    did = db.create_debate(question, 2, model)
    db.update_debate(
        did,
        status=status,
        verdict={
            "answer": "Not now",
            "summary": "Start with a modular monolith.",
            "confidence": 85,
            "scores": {"advocate": 7.0, "critic": 8.5, "evidence": 7.5, "risk": 6.0},
        },
        tokens=3500,
        cost=0.025,
        seconds=14.2,
    )
    # Add messages with tokens and evidence labels
    msgs = [
        (0, 1, "advocate", "Microservices give independent deploys.", 120, None),
        (1, 1, "critic", "Five engineers cannot handle distributed operational overhead.", 140, None),
        (2, 1, "risk", "Major risk is on-call burnout and telemetry overhead.", 95, None),
        (3, 1, "evidence", "Claim: Scalability needs are urgent. Label: unsupported. No citations given.", 110, "unsupported"),
        (4, 2, "advocate", "Decoupling services allows teams to scale asynchronously.", 130, None),
        (5, 2, "critic", "Over-segmentation causes distributed transactions nightmares.", 150, None),
        (6, 2, "risk", "Cost risk of multiple Kubernetes clusters is excessive.", 100, None),
        (7, 2, "evidence", "Claim: Upkeep costs escalate. Label: supported. Well documented in devops studies.", 115, "supported"),
    ]
    for idx, r, ag, text, tok, elab in msgs:
        db.add_message(did, idx, r, ag, text, model, tokens=tok, evidence_label=elab)
    return did


@pytest.mark.asyncio
async def test_fallback_memo_and_report_data_builder():
    did = _seed_debate()
    data = await report.get_or_create_report_data(did)
    assert data is not None
    assert data["id"] == did
    assert "Should a startup" in data["question"]
    assert data["verdict"]["answer"] == "Not now"

    # Verify memo contents
    memo = data["memo"]
    assert "executive_summary" in memo
    assert 40 <= len(memo["executive_summary"].split()) <= 150
    assert len(memo["arguments_for"]) >= 1
    assert len(memo["arguments_against"]) >= 1
    assert len(memo["risks"]) >= 1
    assert "risk" in memo["risks"][0] and "mitigation" in memo["risks"][0]
    assert len(memo["evidence_notes"]) >= 1
    assert memo["recommendation"]
    assert len(memo["next_steps"]) >= 1
    assert memo["limitations"]
    assert data["disclaimer"] == report.DISCLAIMER_TEXT


def test_chart_data_counts_and_metrics():
    did = _seed_debate()
    debate = db.get_debate(did)
    charts = report.compute_chart_data(debate, debate["messages"], debate["verdict"])

    # 1. Argument Scores
    assert len(charts["scores"]) == 4
    adv = next(s for s in charts["scores"] if s["agent"] == "Advocate")
    assert adv["score"] == 7.0

    # 2. Confidence
    assert charts["confidence"]["confidence"] == 85

    # 3. Evidence counts
    evi = charts["evidence"]
    sup = next(e for e in evi if e["label"] == "Supported")
    unsup = next(e for e in evi if e["label"] == "Unsupported")
    assert sup["value"] == 1
    assert unsup["value"] == 1

    # 4. Token usage by agent
    toks = charts["tokens"]
    adv_tok = next(t for t in toks if t["agent"] == "Advocate")
    assert adv_tok["tokens"] == 120 + 130


@pytest.mark.asyncio
async def test_docx_report_generation_and_structure():
    did = _seed_debate()
    report_data = await report.get_or_create_report_data(did)
    docx_bytes = report.generate_docx_report(report_data)
    assert len(docx_bytes) > 2000

    # Reopen using python-docx
    doc = Document(io.BytesIO(docx_bytes))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                full_text += "\n" + cell.text

    assert report_data["question"] in full_text
    assert "Not now" in full_text
    assert "Executive Summary" in full_text
    assert "Appendix: Full Debate Transcript" in full_text
    assert report.DISCLAIMER_TEXT in full_text

    # Check that an image was added to inline shapes
    images = [s for s in doc.inline_shapes]
    assert len(images) >= 1


@pytest.mark.asyncio
async def test_pdf_report_generation_and_header():
    did = _seed_debate()
    report_data = await report.get_or_create_report_data(did)
    pdf_bytes = report.generate_pdf_report(report_data)
    assert len(pdf_bytes) > 5000
    assert pdf_bytes.startswith(b"%PDF")


def test_report_endpoints_and_caching():
    did = _seed_debate()

    # 1. POST /api/debates/{id}/report
    res = client.post(f"/api/debates/{did}/report")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == did
    assert data["verdict"]["answer"] == "Not now"
    assert "charts" in data
    assert "memo" in data

    # Verify cached in DB
    d = db.get_debate(did)
    assert d.get("report") is not None
    assert d["report"]["id"] == did

    # Subsequent POST hits cache
    res2 = client.post(f"/api/debates/{did}/report")
    assert res2.status_code == 200
    assert res2.json()["id"] == did

    # 2. 404 Case
    res_404 = client.post("/api/debates/nonexistent123/report")
    assert res_404.status_code == 404

    # 3. Download DOCX
    dl_docx = client.get(f"/api/debates/{did}/report/download?format=docx")
    assert dl_docx.status_code == 200
    assert "application/vnd.openxmlformats" in dl_docx.headers["content-type"]
    assert "attachment; filename=" in dl_docx.headers["content-disposition"]
    assert ".docx" in dl_docx.headers["content-disposition"]
    assert len(dl_docx.content) > 2000

    # 4. Download PDF
    dl_pdf = client.get(f"/api/debates/{did}/report/download?format=pdf")
    assert dl_pdf.status_code == 200
    assert dl_pdf.headers["content-type"] == "application/pdf"
    assert "attachment; filename=" in dl_pdf.headers["content-disposition"]
    assert ".pdf" in dl_pdf.headers["content-disposition"]
    assert dl_pdf.content.startswith(b"%PDF")

    # 5. Download 404 and invalid format
    assert client.get("/api/debates/nonexistent123/report/download?format=docx").status_code == 404
    assert client.get(f"/api/debates/{did}/report/download?format=xyz").status_code == 400


def test_sanitize_filename():
    assert report.sanitize_filename("Should we use AI? Yes / No : Maybe*") == "Should-we-use-AI-Yes-No-Maybe"
    assert report.sanitize_filename("  test  name  ") == "test-name"
    assert report.sanitize_filename("") == "Debate"


def test_migration_from_old_database():
    """Test safe migration against an old database missing report_json, tokens, and evidence_label."""
    with tempfile.TemporaryDirectory() as tmpdir:
        old_db_path = str(Path(tmpdir) / "old_courtroom.db")
        conn = sqlite3.connect(old_db_path)
        conn.row_factory = sqlite3.Row

        # Create old schema
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
        """)

        # Insert old data
        conn.execute(
            "INSERT INTO debates (id, question, rounds, model, status, created_at) VALUES ('old1', 'Old question here?', 1, 'demo', 'done', 1000)"
        )
        conn.execute(
            "INSERT INTO messages (debate_id, idx, round, agent, model, content) VALUES ('old1', 0, 1, 'advocate', 'demo', 'Old content')"
        )
        conn.commit()
        conn.close()

        # Run migration on the old db
        orig_db_path = settings.db_path
        try:
            settings.db_path = old_db_path
            db.init()

            # Verify columns exist
            d = db.get_debate("old1")
            assert d is not None
            assert d["id"] == "old1"
            assert d["question"] == "Old question here?"
            assert d["report"] is None
            assert len(d["messages"]) == 1
            assert d["messages"][0]["tokens"] is None
            assert d["messages"][0]["evidence_label"] is None

            # Verify update works with new columns
            db.update_debate("old1", report={"test": True})
            d2 = db.get_debate("old1")
            assert d2["report"] == {"test": True}

            db.add_message("old1", 1, 1, "critic", "demo", "New content", tokens=80, evidence_label=None)
            d3 = db.get_debate("old1")
            assert len(d3["messages"]) == 2
            assert d3["messages"][1]["tokens"] == 80
        finally:
            settings.db_path = orig_db_path
