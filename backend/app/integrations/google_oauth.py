"""Incremental Google OAuth 2.0 engine.

Design goals:
  1. Sign-in uses ONLY "openid email profile" (no data-access scopes).
  2. Each Google connector (Gmail, Sheets, Calendar) adds its OWN scopes via
     incremental auth (include_granted_scopes=true, prompt=consent).
  3. Adding Google Sheets or Calendar later = adding 1 entry to SCOPE_MAP.
     Zero changes here.

Required env vars:
  GOOGLE_CLIENT_ID      — Web OAuth client ID (same as sign-in)
  GOOGLE_CLIENT_SECRET  — Web OAuth client secret (keep private)
  APP_BASE_URL          — e.g. https://app.example.com  (no trailing slash)
"""
from __future__ import annotations

import logging
import os
import time
import urllib.parse
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Scope map — add new Google connectors here only ──────────────────────────
GOOGLE_SCOPE_MAP: dict[str, list[str]] = {
    "gmail": [
        "https://www.googleapis.com/auth/gmail.readonly",
    ],
    "google_sheets": [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
    ],
    "google_calendar": [
        "https://www.googleapis.com/auth/calendar.readonly",
    ],
}

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def _client_id() -> str:
    return os.environ["GOOGLE_CLIENT_ID"]


def _client_secret() -> str:
    sec = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not sec:
        raise EnvironmentError("GOOGLE_CLIENT_SECRET is not configured.")
    return sec


def _app_base_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://localhost:8000").rstrip("/")


def redirect_uri_for(provider: str) -> str:
    return f"{_app_base_url()}/api/integrations/{provider}/callback"


def build_google_auth_url(provider: str, state: str) -> str:
    """Build the Google OAuth authorization URL for *provider*.

    Uses include_granted_scopes=true so a user who already granted Gmail
    does not have to re-approve when adding Sheets later.
    """
    if provider not in GOOGLE_SCOPE_MAP:
        raise ValueError(f"Unknown Google provider: {provider!r}")
    scopes = GOOGLE_SCOPE_MAP[provider]
    params = {
        "client_id": _client_id(),
        "redirect_uri": redirect_uri_for(provider),
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


async def exchange_google_code(provider: str, code: str) -> dict[str, Any]:
    """Exchange an authorization code for access + refresh tokens."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "redirect_uri": redirect_uri_for(provider),
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    # Annotate expiry timestamp for auto-refresh
    if "expires_in" in data:
        data["expires_at"] = time.time() + data["expires_in"] - 60  # 60s buffer
    return data


async def refresh_google_token(refresh_token: str) -> dict[str, Any]:
    """Refresh a Google access token using the stored refresh token."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    if "expires_in" in data:
        data["expires_at"] = time.time() + data["expires_in"] - 60
    return data


async def revoke_google_token(token: str) -> None:
    """Revoke an access or refresh token (best-effort)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(GOOGLE_REVOKE_URL, params={"token": token})
    except Exception as exc:
        logger.warning("Google token revocation failed (non-fatal): %s", exc)
