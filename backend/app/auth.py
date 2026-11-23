"""Authentication: password hashing (bcrypt), JWT sessions (PyJWT), and rate limiting."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request

from . import db
from .config import settings

COOKIE_NAME = "session_token"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 12


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_session_token(user_id: str, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_EXPIRY_HOURS)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_session_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


class LoginRateLimiter:
    """Limits failed login attempts (5 failures per 10 minutes per username)."""

    def __init__(self, max_failures: int = 5, window_seconds: float = 600.0) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, list[float]] = {}

    def is_limited(self, username: str) -> bool:
        key = username.strip().lower()
        now = time.time()
        attempts = [t for t in self._failures.get(key, []) if now - t < self.window_seconds]
        self._failures[key] = attempts
        return len(attempts) >= self.max_failures

    def record_failure(self, username: str) -> None:
        key = username.strip().lower()
        now = time.time()
        attempts = [t for t in self._failures.get(key, []) if now - t < self.window_seconds]
        attempts.append(now)
        self._failures[key] = attempts

    def clear(self, username: str) -> None:
        key = username.strip().lower()
        self._failures.pop(key, None)


login_limiter = LoginRateLimiter()


def get_current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        # Also allow Authorization: Bearer <token> for testing or API clients
        auth_hdr = request.headers.get("Authorization")
        if auth_hdr and auth_hdr.startswith("Bearer "):
            token = auth_hdr[7:].strip()

    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")

    payload = decode_session_token(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid or expired session.")

    user = db.get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    return user
