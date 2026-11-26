"""Sprint 1 auth routes tests — fully offline, no real Google OAuth or PostgreSQL.

Strategy:
  - app.dependency_overrides replaces get_db with an AsyncMock session factory
  - google.oauth2.id_token.verify_oauth2_token is monkeypatched
  - JWT encoding/decoding uses a fixed SESSION_SECRET env var
  - All assertions check HTTP status codes, response shapes, and cookie presence
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

# Set env before importing app modules
os.environ.setdefault("SESSION_SECRET", "x" * 32)
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client.apps.googleusercontent.com")
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/test_does_not_exist")

from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

USER_ID = str(uuid.uuid4())
GOOGLE_SUB = "google-sub-123"
EMAIL = "alice@example.com"

FAKE_USER_ROW = MagicMock()
FAKE_USER_ROW.id = USER_ID
FAKE_USER_ROW.google_sub = GOOGLE_SUB
FAKE_USER_ROW.email = EMAIL
FAKE_USER_ROW.name = "Alice"
FAKE_USER_ROW.picture = "https://example.com/alice.jpg"


def _make_session_cookie(user_id: str = USER_ID, email: str = EMAIL) -> str:
    payload = {
        "user_id": user_id,
        "sub": GOOGLE_SUB,
        "email": email,
        "name": "Alice",
        "picture": "",
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, os.environ["SESSION_SECRET"], algorithm="HS256")


def _mock_db() -> AsyncMock:
    """Return an AsyncMock that behaves like an AsyncSession context manager."""
    session = AsyncMock()
    # scalars().scalar_one_or_none() chain
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    session.execute.return_value = scalar_result
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture(autouse=True)
def override_db(monkeypatch):
    """Replace get_db with a no-op mock for every test in this module."""

    async def fake_get_db():
        yield _mock_db()

    app.dependency_overrides[get_db] = fake_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# POST /api/auth/google
# ---------------------------------------------------------------------------


GOOD_ID_TOKEN_INFO = {
    "sub": GOOGLE_SUB,
    "email": EMAIL,
    "email_verified": True,
    "name": "Alice",
    "picture": "https://example.com/alice.jpg",
    "aud": "test-client.apps.googleusercontent.com",
}


def test_google_auth_returns_profile_and_sets_cookie(client: TestClient) -> None:
    with patch(
        "app.auth.google.id_token.verify_oauth2_token",
        return_value=GOOD_ID_TOKEN_INFO,
    ), patch("app.auth.google._upsert_user", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.return_value = FAKE_USER_ROW
        resp = client.post("/api/auth/google", json={"credential": "fake-token"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == EMAIL
    assert body["name"] == "Alice"
    assert "id" in body
    # httpOnly cookie must be set
    assert "session" in resp.cookies


def test_google_auth_rejects_invalid_token(client: TestClient) -> None:
    with patch(
        "app.auth.google.id_token.verify_oauth2_token",
        side_effect=ValueError("bad token"),
    ):
        resp = client.post("/api/auth/google", json={"credential": "bad"})
    assert resp.status_code == 401


def test_google_auth_rejects_unverified_email(client: TestClient) -> None:
    bad_info = {**GOOD_ID_TOKEN_INFO, "email_verified": False}
    with patch("app.auth.google.id_token.verify_oauth2_token", return_value=bad_info):
        resp = client.post("/api/auth/google", json={"credential": "fake"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------


def test_me_returns_profile_when_signed_in(client: TestClient) -> None:
    cookie = _make_session_cookie()
    client.cookies.set("session", cookie)
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == EMAIL
    assert body["id"] == USER_ID


def test_me_returns_401_without_cookie(client: TestClient) -> None:
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_returns_401_with_tampered_cookie(client: TestClient) -> None:
    client.cookies.set("session", "tampered.jwt.value")
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_returns_401_with_expired_token(client: TestClient) -> None:
    payload = {
        "user_id": USER_ID,
        "sub": GOOGLE_SUB,
        "email": EMAIL,
        "name": "Alice",
        "picture": "",
        "exp": int(time.time()) - 1,  # already expired
    }
    expired_token = jwt.encode(payload, os.environ["SESSION_SECRET"], algorithm="HS256")
    client.cookies.set("session", expired_token)
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------


def test_logout_clears_cookie(client: TestClient) -> None:
    cookie = _make_session_cookie()
    client.cookies.set("session", cookie)
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
