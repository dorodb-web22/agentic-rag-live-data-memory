"""Sprint 2 — Tests for individual connector fetch() methods (all offline, httpx mocked)."""
from __future__ import annotations

import os
import sqlite3
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

# ── Env setup ────────────────────────────────────────────────────────────────

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db_integration(provider: str, status: str = "connected") -> MagicMock:
    from app.db.models import UserIntegration
    integ = MagicMock(spec=UserIntegration)
    integ.provider = provider
    integ.status = status
    integ.config = {}
    integ.scope_summary = None
    integ.connected_at = None
    return integ


# ── GitHub ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_github_connector_fetch_returns_issues() -> None:
    from app.integrations.github import GitHubConnector

    integ = _make_db_integration("github")
    integ.config = {"repos": ["owner/repo"]}
    tokens = {"access_token": "ghs_test_token"}

    mock_issues = [
        {
            "number": 42,
            "title": "Fix the bug",
            "state": "open",
            "html_url": "https://github.com/owner/repo/issues/42",
            "user": {"login": "dorothy"},
            "body": "Description of the bug that needs fixing urgently.",
        }
    ]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_issues
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    connector = GitHubConnector(integration=integ, tokens=tokens)

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await connector.fetch("open bugs")

    assert len(results) >= 1
    first = results[0]
    assert first["source"] == "github"
    assert first["citation_key"].startswith("GitHub-")
    assert first["number"] == 42
    assert first["title"] == "Fix the bug"


@pytest.mark.asyncio
async def test_github_connector_returns_empty_when_disconnected() -> None:
    from app.integrations.github import GitHubConnector

    integ = _make_db_integration("github", status="disconnected")
    connector = GitHubConnector(integration=integ, tokens={})
    results = await connector.fetch("anything")
    assert results == []


@pytest.mark.asyncio
async def test_github_connector_extracts_repo_from_url_and_fetches_commits() -> None:
    from app.integrations.github import GitHubConnector

    integ = _make_db_integration("github")
    integ.config = {}  # no repos configured!
    tokens = {"access_token": "ghs_test_token"}

    commits_resp = MagicMock()
    commits_resp.status_code = 200
    commits_resp.json.return_value = [
        {
            "sha": "15e0bc42ef964d75",
            "html_url": "https://github.com/dorodb-web22/agentic-rag-live-data-memory/commit/15e0bc4",
            "author": {"login": "cannonerd007"},
            "commit": {
                "message": "chore(deploy): add Railway single-origin Docker stage",
                "author": {"name": "Alok", "date": "2026-11-26T18:00:00Z"},
            },
        }
    ]
    commits_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=commits_resp)

    connector = GitHubConnector(integration=integ, tokens=tokens)
    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await connector.fetch(
            "how many recent commits in https://github.com/dorodb-web22/agentic-rag-live-data-memory.git"
        )

    assert len(results) == 1
    assert results[0]["citation_key"] == "GitHub-15e0bc4"
    assert results[0]["repo"] == "dorodb-web22/agentic-rag-live-data-memory"
    assert results[0]["state"] == "committed"


@pytest.mark.asyncio
async def test_github_connector_auto_discovers_repos_when_config_empty() -> None:
    from app.integrations.github import GitHubConnector

    integ = _make_db_integration("github")
    integ.config = {}  # empty repos config -> should call /user/repos
    tokens = {"access_token": "ghs_test_token"}

    repos_resp = MagicMock()
    repos_resp.status_code = 200
    repos_resp.json.return_value = [{"full_name": "dorodb-web22/agentic-rag-live-data-memory"}]
    repos_resp.raise_for_status = MagicMock()

    pulls_resp = MagicMock()
    pulls_resp.status_code = 200
    pulls_resp.json.return_value = [
        {
            "number": 40,
            "title": "chore(deploy): add Railway single-origin Docker target",
            "state": "closed",
            "merged_at": "2026-11-26T18:10:00Z",
            "html_url": "https://github.com/dorodb-web22/agentic-rag-live-data-memory/pull/40",
            "user": {"login": "cannonerd007"},
            "body": "Adds all-in-one Docker stage.",
        }
    ]
    pulls_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=[repos_resp, pulls_resp])

    connector = GitHubConnector(integration=integ, tokens=tokens)
    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await connector.fetch("is there any new PR on our project?")

    assert len(results) == 1
    assert results[0]["citation_key"] == "GitHub-40"
    assert results[0]["state"] == "merged"


def test_github_rejects_dot_segment_repo_slugs() -> None:
    """`../..` must never be accepted: httpx would normalise it to `/user/...`."""
    from app.integrations.github import _extract_repos_from_query, _is_safe_repo

    assert not _is_safe_repo("../..")
    assert not _is_safe_repo("./.")
    assert not _is_safe_repo("owner/..")
    assert _is_safe_repo("dorodb-web22/agentic-rag-live-data-memory")
    assert _is_safe_repo("owner/repo.js")
    assert _extract_repos_from_query("see github.com/../.. now") == []


def test_github_keyword_detection_has_no_false_positives() -> None:
    from app.integrations.github import (
        _COMMIT_KEYWORDS,
        _WANTS_ALL_PR_STATES,
        _has_keyword,
    )

    assert not _has_keyword("show my chat history", _COMMIT_KEYWORDS)
    assert _has_keyword("how many commits are there", _COMMIT_KEYWORDS)
    # "all" must match as a word, not inside "small"
    assert not _has_keyword("any small prs", _WANTS_ALL_PR_STATES)
    assert _has_keyword("show all prs", _WANTS_ALL_PR_STATES)


def test_github_citation_keys_are_unique_across_repos() -> None:
    from app.integrations.github import _dedupe_citation_keys

    records = [
        {"citation_key": "GitHub-12", "repo": "acme/alpha", "number": 12},
        {"citation_key": "GitHub-12", "repo": "acme/beta", "number": 12},
        {"citation_key": "GitHub-7", "repo": "acme/beta", "number": 7},
    ]
    _dedupe_citation_keys(records)
    keys = [r["citation_key"] for r in records]
    assert keys == ["GitHub-12", "GitHub-beta-12", "GitHub-7"]
    assert len(set(keys)) == len(keys)


@pytest.mark.asyncio
async def test_github_issues_exclude_pull_requests() -> None:
    from app.integrations.github import GitHubConnector

    integ = _make_db_integration("github")
    integ.config = {"repos": ["acme/alpha"]}

    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = [
        {"number": 1, "title": "Real issue", "state": "open", "html_url": "u1", "user": {"login": "a"}, "body": ""},
        {
            "number": 2,
            "title": "A PR listed by the issues API",
            "state": "open",
            "html_url": "u2",
            "user": {"login": "b"},
            "body": "",
            "pull_request": {"url": "https://api.github.com/repos/acme/alpha/pulls/2"},
        },
    ]

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=resp)

    connector = GitHubConnector(integration=integ, tokens={"access_token": "t"})
    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await connector.fetch("which issues are open?")

    assert [r["number"] for r in results] == [1]


# ── Gmail ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gmail_connector_fetch_returns_messages() -> None:
    from app.integrations.gmail import GmailConnector

    integ = _make_db_integration("gmail")
    tokens = {"access_token": "ya29.test_token"}

    # Mock the messages.list response
    list_response = MagicMock()
    list_response.status_code = 200
    list_response.json.return_value = {
        "messages": [{"id": "msg001", "threadId": "thread001"}]
    }
    list_response.raise_for_status = MagicMock()

    # Mock the message detail response
    detail_response = MagicMock()
    detail_response.status_code = 200
    detail_response.json.return_value = {
        "id": "msg001",
        "threadId": "thread001",
        "snippet": "Invoice for October is attached",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Invoice October"},
                {"name": "From", "value": "billing@example.com"},
                {"name": "Date", "value": "Thu, 01 Jan 2026 10:00:00 +0000"},
            ]
        },
    }
    detail_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=[list_response, detail_response])

    connector = GmailConnector(integration=integ, tokens=tokens)

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await connector.fetch("invoice")

    assert len(results) >= 1
    first = results[0]
    assert first["source"] == "gmail"
    assert first["citation_key"].startswith("Gmail-")
    assert first["subject"] == "Invoice October"


# ── Notion ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notion_connector_fetch_returns_pages() -> None:
    from app.integrations.notion import NotionConnector

    integ = _make_db_integration("notion")
    tokens = {"access_token": "secret_notion_test"}

    search_response = MagicMock()
    search_response.status_code = 200
    search_response.json.return_value = {
        "results": [
            {
                "id": "page-abc-123",
                "last_edited_time": "2026-11-01T12:00:00.000Z",
                "properties": {
                    "title": {
                        "title": [{"plain_text": "Product Roadmap Q4"}]
                    }
                },
                "url": "https://www.notion.so/page-abc-123",
            }
        ]
    }
    search_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=search_response)

    connector = NotionConnector(integration=integ, tokens=tokens)

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await connector.fetch("roadmap")

    assert len(results) >= 1
    first = results[0]
    assert first["source"] == "notion"
    assert first["citation_key"].startswith("Notion-")
    assert first["title"] == "Product Roadmap Q4"


# ── SQLite ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sqlite_connector_fetch_reads_tables() -> None:
    from app.integrations.sqlite_upload import SQLiteConnector

    # Create a real temporary SQLite database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL)")
        conn.execute("INSERT INTO products VALUES (1, 'Widget', 9.99)")
        conn.execute("INSERT INTO products VALUES (2, 'Gadget', 19.99)")
        conn.commit()
        conn.close()

        integ = _make_db_integration("sqlite")
        integ.config = {"db_path": db_path, "tables": ["products"]}  # connector uses "db_path"

        connector = SQLiteConnector(integration=integ, tokens={})
        results = await connector.fetch("products")

        assert len(results) >= 1
        assert results[0]["source"] == "sqlite"
        assert results[0]["citation_key"].startswith("SQL-")  # format: SQL-{table}-{rowid}
        assert "table" in results[0]
    finally:
        os.unlink(db_path)


# ── Crypto roundtrip in registry flow ─────────────────────────────────────────


def test_crypto_roundtrip_in_registry_flow() -> None:
    """Encrypt tokens → store as string → decrypt → verify identical."""
    import importlib
    import os as _os
    from cryptography.fernet import Fernet

    # Ensure a fresh key is set before reload so _fernet() can initialise
    test_key = Fernet.generate_key().decode()
    _os.environ["TOKEN_ENCRYPTION_KEY"] = test_key

    import app.integrations.crypto as crypto_mod
    importlib.reload(crypto_mod)

    original = {
        "access_token": "ya29.real_access_token",
        "refresh_token": "1//real_refresh_token",
        "expires_at": 9999999999.0,
        "scope": "https://www.googleapis.com/auth/gmail.readonly",
    }

    ciphertext = crypto_mod.encrypt_tokens(original)
    # Simulate storing and retrieving from DB (string field)
    stored_string = ciphertext
    recovered = crypto_mod.decrypt_tokens(stored_string)

    assert recovered["access_token"] == original["access_token"]
    assert recovered["refresh_token"] == original["refresh_token"]
    assert recovered["expires_at"] == original["expires_at"]
    assert recovered["scope"] == original["scope"]
