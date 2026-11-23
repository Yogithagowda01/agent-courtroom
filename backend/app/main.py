"""FastAPI app: REST endpoints, the debate WebSocket, and the built frontend."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, benchmark, db, engine, llm, report
from .auth import (
    COOKIE_NAME,
    create_session_token,
    decode_session_token,
    get_current_user,
    hash_password,
    login_limiter,
    verify_password,
)
from .config import settings
from .llm import ProviderError

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("courtroom")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    yield


app = FastAPI(title="Agent Courtroom", lifespan=lifespan)


class AuthIn(BaseModel):
    username: str
    password: str


class DebateIn(BaseModel):
    question: str
    rounds: int = 3
    model: str = "auto"


class BenchmarkIn(BaseModel):
    model: str = "auto"


@app.get("/api/health")
async def health():
    return {"ok": True}


# ---- Auth endpoints -----------------------------------------------------------------
@app.post("/api/auth/register", status_code=201)
async def register(body: AuthIn, response: Response):
    username = body.username.strip()
    if not (3 <= len(username) <= 30):
        raise HTTPException(400, "Username must be between 3 and 30 characters.")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if db.get_user_by_username(username):
        raise HTTPException(400, "Username already taken.")

    pw_hash = hash_password(body.password)
    user = db.create_user(username, pw_hash)
    token = create_session_token(user["id"], user["username"])
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=12 * 3600,
        path="/",
    )
    return {"user": {"id": user["id"], "username": user["username"]}}


@app.post("/api/auth/login")
async def login(body: AuthIn, response: Response):
    username = body.username.strip()
    if login_limiter.is_limited(username):
        raise HTTPException(
            429,
            "Too many failed login attempts. Please wait a few minutes before trying again.",
        )

    user = db.get_user_by_username(username)
    if not user or not verify_password(body.password, user["password_hash"]):
        login_limiter.record_failure(username)
        raise HTTPException(401, "Invalid username or password.")

    login_limiter.clear(username)
    token = create_session_token(user["id"], user["username"])
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=12 * 3600,
        path="/",
    )
    return {"user": {"id": user["id"], "username": user["username"]}}


@app.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
async def me(user: dict[str, Any] = Depends(get_current_user)):
    return {"user": {"id": user["id"], "username": user["username"]}}


# ---- Protected API endpoints --------------------------------------------------------
@app.get("/api/models")
async def models(user: dict[str, Any] = Depends(get_current_user)):
    return {"models": await llm.available_models()}


@app.post("/api/debates", status_code=201)
async def create_debate(body: DebateIn, user: dict[str, Any] = Depends(get_current_user)):
    question = " ".join(body.question.split())
    if len(question) < settings.min_question_len:
        raise HTTPException(400, f"Please type a question of at least {settings.min_question_len} characters.")
    if len(question) > settings.max_question_len:
        raise HTTPException(400, f"Please keep the question under {settings.max_question_len} characters.")
    if not 1 <= body.rounds <= settings.max_rounds:
        raise HTTPException(400, f"Rounds must be between 1 and {settings.max_rounds}.")
    try:
        await llm.resolve(body.model)  # fail early with a clear message
    except ProviderError as e:
        raise HTTPException(400, str(e))
    return {"id": db.create_debate(question, body.rounds, body.model, user_name=user["username"])}


@app.get("/api/debates")
async def list_debates(user: dict[str, Any] = Depends(get_current_user)):
    return {"debates": db.list_debates(user_name=user["username"])}


@app.get("/api/debates/{debate_id}")
async def get_debate(debate_id: str, user: dict[str, Any] = Depends(get_current_user)):
    d = db.get_debate(debate_id, user_name=user["username"])
    if not d:
        raise HTTPException(404, "Debate not found.")
    d.pop("verdict_json", None)
    d.pop("report_json", None)
    return d


@app.delete("/api/debates/{debate_id}")
async def delete_debate(debate_id: str, user: dict[str, Any] = Depends(get_current_user)):
    if not db.delete_debate(debate_id, user_name=user["username"]):
        raise HTTPException(404, "Debate not found.")
    return {"ok": True}


@app.post("/api/debates/{debate_id}/report")
async def generate_debate_report(debate_id: str, user: dict[str, Any] = Depends(get_current_user)):
    d = db.get_debate(debate_id, user_name=user["username"])
    if not d:
        raise HTTPException(404, "Debate not found.")
    data = await report.get_or_create_report_data(debate_id)
    if not data:
        raise HTTPException(404, "Debate not found.")
    return data


@app.get("/api/debates/{debate_id}/report/download")
async def download_debate_report(debate_id: str, format: str = "docx", user: dict[str, Any] = Depends(get_current_user)):
    d = db.get_debate(debate_id, user_name=user["username"])
    if not d:
        raise HTTPException(404, "Debate not found.")
    data = await report.get_or_create_report_data(debate_id)
    if not data:
        raise HTTPException(404, "Debate not found.")

    fmt = format.lower().strip()
    if fmt not in ("docx", "pdf"):
        raise HTTPException(400, "Format must be docx or pdf.")

    short_q = report.sanitize_filename(data.get("question", "Debate"))
    date_str = data.get("date_ymd", "report")
    filename = f"Agent-Courtroom-Report-{short_q}-{date_str}.{fmt}"
    if fmt == "docx":
        content = report.generate_docx_report(data)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        content = report.generate_pdf_report(data)
        media_type = "application/pdf"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.websocket("/ws/debates/{debate_id}")
async def ws_debate(ws: WebSocket, debate_id: str):
    token = ws.cookies.get(COOKIE_NAME)
    user = None
    if token:
        payload = decode_session_token(token)
        if payload and payload.get("sub"):
            user = db.get_user_by_id(payload["sub"])

    if not user:
        await ws.close(code=1008, reason="Authentication required.")
        return

    debate = db.get_debate(debate_id, user_name=user["username"])
    if not debate:
        await ws.close(code=1008, reason="Debate not found or access denied.")
        return

    await ws.accept()
    if debate["status"] != "pending":
        await ws.send_json({"type": "debate.error", "message": "This debate was already started."})
        await ws.close()
        return
    try:
        resolved = await llm.resolve(debate["model"])
    except ProviderError as e:
        db.update_debate(debate_id, status="failed")
        await ws.send_json({"type": "debate.error", "message": str(e)})
        await ws.close()
        return

    async def emit(event: dict) -> None:
        try:
            await ws.send_json(event)
        except Exception:
            raise engine.ClientGone()

    runner = asyncio.create_task(engine.run_debate(debate, resolved, emit))

    async def listen() -> None:
        try:
            while True:
                msg = await ws.receive_json()
                if isinstance(msg, dict) and msg.get("type") == "cancel":
                    return
        except Exception:
            return

    listener = asyncio.create_task(listen())
    try:
        await asyncio.wait({runner, listener}, return_when=asyncio.FIRST_COMPLETED)
        if not runner.done():  # the user pressed Stop, or left the page
            runner.cancel()
            try:
                await runner
            except asyncio.CancelledError:
                pass
            try:
                await ws.send_json({"type": "debate.completed", "status": "cancelled"})
            except Exception:
                pass
    finally:
        listener.cancel()
        try:
            await ws.close()
        except Exception:
            pass


@app.post("/api/benchmarks", status_code=201)
async def start_benchmark(body: BenchmarkIn, user: dict[str, Any] = Depends(get_current_user)):
    try:
        resolved = await llm.resolve(body.model)
        label = resolved.debater_model
        return benchmark.start(resolved, label, user_name=user["username"])
    except ProviderError as e:
        raise HTTPException(400, str(e))


@app.get("/api/benchmarks/latest")
async def latest_benchmark(user: dict[str, Any] = Depends(get_current_user)):
    return {
        "run": benchmark.get_latest(user_name=user["username"]),
        "questions": len(benchmark.QUESTIONS),
        "methods": benchmark.METHODS,
    }


@app.post("/api/benchmarks/cancel")
async def cancel_benchmark(user: dict[str, Any] = Depends(get_current_user)):
    return {"cancelled": benchmark.cancel()}


# ---- the built frontend (run `npm run build` in ../frontend) --------------------------
_dist = settings.frontend_dist
if (_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/")
    async def index():
        return FileResponse(_dist / "index.html")
else:

    @app.get("/")
    async def index_missing():
        return {
            "message": "Backend is running. Start the frontend with 'npm run dev' in the frontend folder, or run 'npm run build' there."
        }
