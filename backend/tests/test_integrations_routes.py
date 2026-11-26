"""Sprint 2 — Tests for /api/integrations/* routes (all offline, DB mocked)."""
from __future__ import annotations

import io
import os
import sqlite3
import tempfile
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession


# ── Env setup (must happen before app import) ─────────────────────────────────

FERNET_KEY = Fernet.generate_key().decode()

os.environ.setdefault("SESSION_SECRET", "x" * 32)
os.environ.setdefault("GOOGLE_CLIENT_ID", "test.apps.googleusercontent.com")
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/test_does_not_exist")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", FERNET_KEY)
os.environ.setdefault("APP_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_ID", "gh_test_id")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_SECRET", "gh_test_secret")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "g_test_secret")
os.environ.setdefault("NOTION_OAUTH_CLIENT_ID", "notion_test_id")
os.environ.setdefault("NOTION_OAUTH_CLIENT_SECRET", "notion_test_secret")


# ── Fake user ─────────────────────────────────────────────────────────────────

FAKE_USER = {
    "user_id": "user-uuid-1234",
    "sub": "google-sub-1234",
    "email": "test@example.com",
    "name": "Test User",
    "picture": "https://example.com/pic.jpg",
}


def _make_fake_db(scalar_result=None):
    """Return a dependency-override function that yields a mocked AsyncSession."""
    async def fake_db() -> AsyncGenerator[AsyncSession, None]:
        db = AsyncMock(spec=AsyncSession)
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        result_mock.scalar_one_or_none.return_value = scalar_result
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        yield db
    return fake_db


def _make_client(scalar_result=None, authenticated: bool = True):
    """Create a TestClient with optional auth + DB mocks."""
    from app.main import app
    from app.db.session import get_db
    from app.auth.google import current_user

    app.dependency_overrides[get_db] = _make_fake_db(scalar_result)
    if authenticated:
        app.dependency_overrides[current_user] = lambda: FAKE_USER
    elif current_user in app.dependency_overrides:
        del app.dependency_overrides[current_user]

    return app


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_list_integrations_returns_catalog() -> None:
    app = _make_client()
    with TestClient(app, raise_server_exceptions=True) as c:
        resp = c.get("/api/integrations")
    assert resp.status_code == 200
    body = resp.json()
    assert "integrations" in body
    providers = [i["provider"] for i in body["integrations"]]
    for expected in ["github", "gmail", "notion", "sqlite", "google_sheets", "google_calendar"]:
        assert expected in providers, f"Missing provider: {expected}"
    app.dependency_overrides.clear()


def test_list_integrations_requires_auth() -> None:
    from app.main import app
    from app.db.session import get_db
    from app.auth.google import current_user

    app.dependency_overrides[get_db] = _make_fake_db()
    # Explicitly remove auth override to get the real 401 behaviour
    app.dependency_overrides.pop(current_user, None)

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get("/api/integrations")
    assert resp.status_code == 401
    app.dependency_overrides.clear()


def test_connect_redirects_for_known_provider() -> None:
    app = _make_client()
    with TestClient(app, raise_server_exceptions=True) as c:
        for provider in ("github", "notion"):
            resp = c.get(f"/api/integrations/{provider}/connect", follow_redirects=False)
            assert resp.status_code in (302, 307), (
                f"{provider}: expected redirect, got {resp.status_code}"
            )
    app.dependency_overrides.clear()


def test_connect_404_for_unknown_provider() -> None:
    app = _make_client()
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get("/api/integrations/fakeprovider/connect", follow_redirects=False)
    assert resp.status_code == 404
    app.dependency_overrides.clear()


def test_config_update_returns_ok() -> None:
    from app.db.models import UserIntegration
    import datetime

    fake_integ = MagicMock(spec=UserIntegration)
    fake_integ.user_id = "user-uuid-1234"
    fake_integ.provider = "github"
    fake_integ.status = "connected"
    fake_integ.config = {}
    fake_integ.connected_at = datetime.datetime.utcnow()

    app = _make_client(scalar_result=fake_integ)
    with TestClient(app, raise_server_exceptions=True) as c:
        # Body must be {"config": {...}} per ConfigBody schema
        resp = c.patch("/api/integrations/github/config", json={"config": {"repos": ["owner/repo"]}})
    assert resp.status_code == 200, resp.text
    assert resp.json().get("ok") is True
    app.dependency_overrides.clear()


def test_delete_integration_returns_ok() -> None:
    from app.db.models import UserIntegration

    fake_integ = MagicMock(spec=UserIntegration)
    fake_integ.user_id = "user-uuid-1234"
    fake_integ.provider = "github"
    fake_integ.encrypted_tokens = None
    fake_integ.config = {}

    app = _make_client(scalar_result=fake_integ)
    with TestClient(app, raise_server_exceptions=True) as c:
        resp = c.delete("/api/integrations/github")
    assert resp.status_code == 200
    assert resp.json().get("ok") is True
    app.dependency_overrides.clear()


def test_delete_404_for_missing_integration() -> None:
    app = _make_client(scalar_result=None)
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.delete("/api/integrations/github")
    assert resp.status_code == 404
    app.dependency_overrides.clear()


def test_sqlite_upload_valid_file() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_tmp = f.name
    try:
        conn = sqlite3.connect(db_tmp)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.commit()
        conn.close()
        with open(db_tmp, "rb") as f:
            db_bytes = f.read()
    finally:
        os.unlink(db_tmp)

    app = _make_client()

    with (
        patch("app.integrations.sqlite_upload.store_sqlite_file", return_value="/tmp/fake.db"),
        patch("app.integrations.sqlite_upload.introspect_schema", return_value=[{"table": "items", "columns": ["id", "name"]}]),
        # Patch out the postgres upsert — replace with a no-op
        patch("app.routes.integrations._upsert_integration", new=AsyncMock()),
    ):
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.post(
                "/api/integrations/sqlite/upload",
                files={"file": ("test.db", io.BytesIO(db_bytes), "application/octet-stream")},
            )
    assert resp.status_code == 200, resp.text
    app.dependency_overrides.clear()


def test_sqlite_upload_rejects_non_sqlite() -> None:
    app = _make_client()
    bad_bytes = b"This is definitely not a SQLite file at all!"
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post(
            "/api/integrations/sqlite/upload",
            files={"file": ("bad.db", io.BytesIO(bad_bytes), "application/octet-stream")},
        )
    assert resp.status_code == 400
    app.dependency_overrides.clear()


def test_sqlite_upload_rejects_oversized() -> None:
    app = _make_client()
    magic = b"SQLite format 3\x00"
    oversized = magic + b"\x00" * (26 * 1024 * 1024)
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post(
            "/api/integrations/sqlite/upload",
            files={"file": ("big.db", io.BytesIO(oversized), "application/octet-stream")},
        )
    assert resp.status_code == 400
    app.dependency_overrides.clear()


def test_callback_invalid_state_returns_400() -> None:
    app = _make_client()
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get(
            "/api/integrations/github/callback",
            params={"code": "some_code", "state": "invalid_jwt_state"},
            follow_redirects=False,
        )
    assert resp.status_code == 400
    app.dependency_overrides.clear()
