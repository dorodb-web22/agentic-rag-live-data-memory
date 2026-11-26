"""Google sign-in authentication — production-grade, multi-tenant.

Flow:
  1. Browser signs in with Google Identity Services → gets an ID token.
  2. POST /api/auth/google { "credential": "<id_token>" }
  3. We verify the token cryptographically against Google's public keys.
  4. We upsert the user row in PostgreSQL (google_sub is the stable key).
  5. We issue our own signed 7-day JWT in an httpOnly SameSite=Lax cookie.
  6. All subsequent API calls read the cookie and call current_user().

Environment variables required:
  GOOGLE_CLIENT_ID   — OAuth 2.0 Web client ID (public, safe to log)
  SESSION_SECRET     — 32+ char random string (keep secret, rotate via key-id prefix in Sprint 2)
  COOKIE_SECURE      — set to "1" in production (HTTPS)
"""
from __future__ import annotations

import logging
import os
import time

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, _now, _uuid
from app.db.session import get_db

logger = logging.getLogger(__name__)

COOKIE_NAME = "session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _client_id() -> str:
    cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    if not cid:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "GOOGLE_CLIENT_ID is not configured.",
        )
    return cid


def _session_secret() -> str:
    sec = os.environ.get("SESSION_SECRET", "").strip()
    if len(sec) < 32:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "SESSION_SECRET must be at least 32 characters.",
        )
    return sec


# ---------------------------------------------------------------------------
# Token verification (mockable in tests)
# ---------------------------------------------------------------------------


def _verify_google_token(credential: str, client_id: str) -> dict:
    """Verify Google ID token; raises HTTPException on failure."""
    try:
        info = id_token.verify_oauth2_token(
            credential, g_requests.Request(), client_id
        )
    except (ValueError, Exception) as exc:
        logger.warning("Google token verification failed: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Google ID token.")
    if not info.get("email_verified"):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Google account email is not verified."
        )
    return info


# ---------------------------------------------------------------------------
# User upsert
# ---------------------------------------------------------------------------


async def _upsert_user(db: AsyncSession, info: dict) -> User:
    """Get-or-create user by google_sub; always updates last_login_at."""
    result = await db.execute(
        select(User).where(User.google_sub == info["sub"])
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            id=_uuid(),
            google_sub=info["sub"],
            email=info["email"],
            name=info.get("name", ""),
            picture=info.get("picture", ""),
        )
        db.add(user)
        await db.flush()
        logger.info("New user created: %s", user.email)
    else:
        # Keep profile picture / name in sync with Google account
        user.name = info.get("name", user.name)
        user.picture = info.get("picture", user.picture)
        user.last_login_at = _now()

    return user


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _make_session_jwt(user: User) -> str:
    payload = {
        "user_id": user.id,
        "sub": user.google_sub,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "exp": int(time.time()) + SESSION_MAX_AGE,
    }
    return jwt.encode(payload, _session_secret(), algorithm="HS256")


def _decode_session_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, _session_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired.")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session token.")


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("COOKIE_SECURE", "") == "1",
        path="/",
    )


# ---------------------------------------------------------------------------
# FastAPI dependency — used by all protected routes
# ---------------------------------------------------------------------------


async def current_user(request: Request) -> dict:
    """Dependency: decode session cookie → user payload dict.

    Raises HTTP 401 if cookie is missing or invalid.
    Usage:
        from app.auth.google import current_user
        async def my_route(user: dict = Depends(current_user)):
            user["user_id"]  # UUID string
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")
    return _decode_session_jwt(token)


# ---------------------------------------------------------------------------
# Public auth functions used by routes/auth.py
# ---------------------------------------------------------------------------


async def google_sign_in(
    credential: str, response: Response, db: AsyncSession
) -> dict:
    """Verify Google ID token, upsert user, set session cookie, return profile."""
    info = _verify_google_token(credential, _client_id())
    user = await _upsert_user(db, info)
    token = _make_session_jwt(user)
    _set_session_cookie(response, token)
    return {"id": user.id, "name": user.name, "email": user.email, "picture": user.picture}
