"""Multi-tenant conversation routes tests — fully offline.

Key isolation invariant tested:
  User A must receive 404 (never 403) on User B's thread_id.
  DELETE on a non-owned thread must also return 404.
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

os.environ.setdefault("SESSION_SECRET", "x" * 32)
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client.apps.googleusercontent.com")
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/test_does_not_exist")

from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_A_ID = str(uuid.uuid4())
USER_B_ID = str(uuid.uuid4())


def _cookie(user_id: str, email: str = "user@example.com") -> str:
    payload = {
        "user_id": user_id,
        "sub": f"sub-{user_id}",
        "email": email,
        "name": "Test",
        "picture": "",
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, os.environ["SESSION_SECRET"], algorithm="HS256")


COOKIE_A = _cookie(USER_A_ID, "alice@example.com")
COOKIE_B = _cookie(USER_B_ID, "bob@example.com")


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/conversations
# ---------------------------------------------------------------------------


def test_list_conversations_returns_empty_for_new_user(client: TestClient) -> None:
    async def fake_get_db():
        session = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        session.execute.return_value = result
        yield session

    app.dependency_overrides[get_db] = fake_get_db

    with patch(
        "app.routes.conversations.get_conversations",
        new_callable=AsyncMock,
        return_value=[],
    ):
        client.cookies.set("session", COOKIE_A)
        resp = client.get("/api/conversations")

    app.dependency_overrides.pop(get_db, None)
    assert resp.status_code == 200
    assert resp.json() == {"conversations": []}


def test_list_conversations_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/conversations")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/conversations/{thread_id}
# ---------------------------------------------------------------------------


THREAD_ID = "thread-abc123"

FAKE_CONV = {
    "thread_id": THREAD_ID,
    "title": "Hello world",
    "messages": [
        {"id": str(uuid.uuid4()), "role": "user", "content": "hi", "evidence": None, "trace_url": None, "created_at": "2026-01-01T00:00:00+00:00"},
        {"id": str(uuid.uuid4()), "role": "assistant", "content": "hello!", "evidence": None, "trace_url": None, "created_at": "2026-01-01T00:00:01+00:00"},
    ],
}


def test_get_conversation_returns_data_for_owner(client: TestClient) -> None:
    with patch(
        "app.routes.conversations.get_conversation",
        new_callable=AsyncMock,
        return_value=FAKE_CONV,
    ):
        client.cookies.set("session", COOKIE_A)
        resp = client.get(f"/api/conversations/{THREAD_ID}")
    assert resp.status_code == 200
    assert resp.json()["thread_id"] == THREAD_ID
    assert len(resp.json()["messages"]) == 2


def test_get_conversation_returns_404_for_nonexistent_thread(client: TestClient) -> None:
    """User A asking for a thread that does not exist → 404."""
    with patch(
        "app.routes.conversations.get_conversation",
        new_callable=AsyncMock,
        return_value=None,
    ):
        client.cookies.set("session", COOKIE_A)
        resp = client.get(f"/api/conversations/{THREAD_ID}")
    assert resp.status_code == 404


def test_multitenant_isolation_user_b_cannot_read_user_a_thread(client: TestClient) -> None:
    """CORE ISOLATION TEST: User B gets 404 on User A's thread_id.

    get_conversation is called with User B's user_id — returns None because
    the WHERE user_id = :user_id filter finds no match.
    """
    with patch(
        "app.routes.conversations.get_conversation",
        new_callable=AsyncMock,
        return_value=None,  # DB returns nothing for wrong user_id
    ) as mock_gc:
        client.cookies.set("session", COOKIE_B)
        resp = client.get(f"/api/conversations/{THREAD_ID}")

        # Assert the route called get_conversation with User B's id, not User A's
        called_user_id = mock_gc.call_args[0][1]  # positional arg 2
        assert called_user_id == USER_B_ID

    assert resp.status_code == 404  # never 403


# ---------------------------------------------------------------------------
# DELETE /api/conversations/{thread_id}
# ---------------------------------------------------------------------------


def test_delete_conversation_returns_ok_for_owner(client: TestClient) -> None:
    with patch(
        "app.routes.conversations.delete_conversation",
        new_callable=AsyncMock,
        return_value=True,
    ):
        client.cookies.set("session", COOKIE_A)
        resp = client.delete(f"/api/conversations/{THREAD_ID}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_multitenant_isolation_user_b_cannot_delete_user_a_thread(client: TestClient) -> None:
    """CORE ISOLATION TEST: User B gets 404 trying to delete User A's thread."""
    with patch(
        "app.routes.conversations.delete_conversation",
        new_callable=AsyncMock,
        return_value=False,  # DB found no matching row for User B
    ) as mock_del:
        client.cookies.set("session", COOKIE_B)
        resp = client.delete(f"/api/conversations/{THREAD_ID}")

        called_user_id = mock_del.call_args[0][1]
        assert called_user_id == USER_B_ID

    assert resp.status_code == 404


def test_delete_requires_auth(client: TestClient) -> None:
    resp = client.delete(f"/api/conversations/{THREAD_ID}")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# thread_id validation
# ---------------------------------------------------------------------------


def test_invalid_thread_id_returns_422(client: TestClient) -> None:
    client.cookies.set("session", COOKIE_A)
    for bad in ["../../etc/passwd", "a" * 65, "has spaces", "has/slash"]:
        resp = client.get(f"/api/conversations/{bad}")
        assert resp.status_code in (404, 422), f"Expected 404/422 for {bad!r}, got {resp.status_code}"
