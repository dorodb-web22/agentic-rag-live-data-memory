"""Integration routes — /api/integrations/*

GET    /api/integrations                        — full connector catalog (registry-driven)
GET    /api/integrations/{provider}/connect     — CSRF-signed state → redirect to OAuth
GET    /api/integrations/{provider}/callback    — exchange code, store encrypted tokens
PATCH  /api/integrations/{provider}/config      — update user scope config
POST   /api/integrations/sqlite/upload          — validate + store SQLite file
DELETE /api/integrations/{provider}             — revoke + delete credentials
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import jwt
from fastapi import APIRouter, Depends, File, HTTPException, Path, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google import current_user
from app.db.models import UserIntegration
from app.db.session import get_db
from app.integrations.crypto import decrypt_tokens, encrypt_tokens
from app.integrations.registry import REGISTRY, get_catalog_for_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])

_GOOGLE_PROVIDERS = {"gmail", "google_sheets", "google_calendar"}
_GITHUB_PROVIDER = "github"
_NOTION_PROVIDER = "notion"
_SQLITE_PROVIDER = "sqlite"


# ── State helpers (CSRF) ──────────────────────────────────────────────────────


def _session_secret() -> str:
    sec = os.environ.get("SESSION_SECRET", "").strip()
    if len(sec) < 32:
        raise HTTPException(500, "SESSION_SECRET is not configured.")
    return sec


def _make_oauth_state(user_id: str, provider: str) -> str:
    """Short-lived signed JWT as CSRF state parameter (10 min TTL)."""
    payload = {
        "user_id": user_id,
        "provider": provider,
        "exp": int(time.time()) + 600,
    }
    return jwt.encode(payload, _session_secret(), algorithm="HS256")


def _decode_oauth_state(state: str) -> dict:
    try:
        return jwt.decode(state, _session_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OAuth state expired — please try connecting again.")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid OAuth state.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── DB upsert helper ──────────────────────────────────────────────────────────


async def _upsert_integration(
    db: AsyncSession,
    user_id: str,
    provider: str,
    encrypted_tokens: str | None,
    config: dict,
    status_val: str,
    scope_summary: str | None,
    expires_at: datetime | None = None,
) -> None:
    stmt = (
        pg_insert(UserIntegration)
        .values(
            user_id=user_id,
            provider=provider,
            encrypted_tokens=encrypted_tokens,
            config=config,
            status=status_val,
            scope_summary=scope_summary,
            expires_at=expires_at,
            connected_at=_now(),
        )
        .on_conflict_do_update(
            constraint="uq_integrations_user_provider",
            set_={
                "encrypted_tokens": encrypted_tokens,
                "config": config,
                "status": status_val,
                "scope_summary": scope_summary,
                "expires_at": expires_at,
                "connected_at": _now(),
            },
        )
    )
    await db.execute(stmt)


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("")
async def list_integrations(
    user: dict = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the full connector catalog with per-user connection status."""
    catalog = await get_catalog_for_user(user["user_id"], db)
    return {"integrations": catalog}


@router.get("/{provider}/connect")
async def connect_provider(
    provider: str = Path(..., pattern=r"^[a-z_]+$"),
    user: dict = Depends(current_user),
) -> RedirectResponse:
    """Generate a CSRF-signed state and redirect to the provider's OAuth screen."""
    state = _make_oauth_state(user["user_id"], provider)

    if provider in _GOOGLE_PROVIDERS:
        from app.integrations.google_oauth import build_google_auth_url
        url = build_google_auth_url(provider, state)

    elif provider == _GITHUB_PROVIDER:
        from app.integrations.github import build_github_auth_url
        url = build_github_auth_url(state)

    elif provider == _NOTION_PROVIDER:
        from app.integrations.notion import build_notion_auth_url
        url = build_notion_auth_url(state)

    else:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown provider: {provider!r}")

    return RedirectResponse(url, status_code=302)


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str = Path(..., pattern=r"^[a-z_]+$"),
    code: str = "",
    state: str = "",
    error: str = "",
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Exchange OAuth code for tokens, encrypt + store, redirect to /app."""
    if error:
        logger.warning("OAuth error for %s: %s", provider, error)
        return RedirectResponse(f"/app?error={error}&provider={provider}")

    state_data = _decode_oauth_state(state)
    if state_data.get("provider") != provider:
        raise HTTPException(400, "OAuth state/provider mismatch.")
    user_id: str = state_data["user_id"]

    app_base = os.environ.get("APP_BASE_URL", "http://localhost:8000").rstrip("/")
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173")
    redirect_success = f"{frontend_url}/app?connected={provider}"

    try:
        if provider in _GOOGLE_PROVIDERS:
            from app.integrations.google_oauth import exchange_google_code
            tokens = await exchange_google_code(provider, code)
            scope_summary = provider.replace("_", " ").title() + " (Read-only)"
            expires_at = None
            if "expires_at" in tokens:
                expires_at = datetime.fromtimestamp(tokens["expires_at"], tz=timezone.utc)

        elif provider == _GITHUB_PROVIDER:
            from app.integrations.github import exchange_github_code
            tokens = await exchange_github_code(code)
            scope_summary = "GitHub (Read-only)"
            expires_at = None

        elif provider == _NOTION_PROVIDER:
            from app.integrations.notion import exchange_notion_code
            tokens = await exchange_notion_code(code)
            workspace = tokens.get("workspace_name", "")
            scope_summary = f"Notion: {workspace}" if workspace else "Notion workspace"
            expires_at = None

        else:
            raise HTTPException(404, f"Unknown provider: {provider!r}")

        encrypted = encrypt_tokens(tokens)
        await _upsert_integration(
            db, user_id, provider,
            encrypted_tokens=encrypted,
            config={},
            status_val="connected",
            scope_summary=scope_summary,
            expires_at=expires_at,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("OAuth callback error for %s: %s", provider, exc)
        return RedirectResponse(f"{frontend_url}/app?error=callback_failed&provider={provider}")

    return RedirectResponse(redirect_success, status_code=302)


class ConfigBody(BaseModel):
    config: dict[str, Any]


@router.patch("/{provider}/config")
async def update_config(
    body: ConfigBody,
    provider: str = Path(..., pattern=r"^[a-z_]+$"),
    user: dict = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update per-user connector config (repos list, Notion root pages, etc.)."""
    result = await db.execute(
        select(UserIntegration).where(
            UserIntegration.user_id == user["user_id"],
            UserIntegration.provider == provider,
        )
    )
    integ = result.scalar_one_or_none()
    if integ is None:
        raise HTTPException(404, f"No connected integration for {provider!r}.")
    integ.config = {**(integ.config or {}), **body.config}
    return {"ok": True, "config": integ.config}


@router.post("/sqlite/upload")
async def upload_sqlite(
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Validate + store a user-uploaded SQLite database file."""
    from app.integrations.sqlite_upload import (
        validate_sqlite_file,
        store_sqlite_file,
        introspect_schema,
        MAX_SIZE_BYTES,
    )

    data = await file.read()
    try:
        validate_sqlite_file(data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    db_path = store_sqlite_file(user["user_id"], file.filename or "upload.db", data)
    tables = introspect_schema(str(db_path))
    table_names = [t["table"] for t in tables]

    await _upsert_integration(
        db,
        user["user_id"],
        "sqlite",
        encrypted_tokens=None,
        config={"db_path": str(db_path), "filename": file.filename, "tables": table_names},
        status_val="connected",
        scope_summary=f"{file.filename} ({len(tables)} table{'s' if len(tables) != 1 else ''})",
        expires_at=None,
    )

    return {
        "ok": True,
        "filename": file.filename,
        "tables": tables,
    }


@router.delete("/{provider}")
async def delete_integration(
    provider: str = Path(..., pattern=r"^[a-z_]+$"),
    user: dict = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revoke provider tokens, delete stored credentials and indexed chunks."""
    result = await db.execute(
        select(UserIntegration).where(
            UserIntegration.user_id == user["user_id"],
            UserIntegration.provider == provider,
        )
    )
    integ = result.scalar_one_or_none()
    if integ is None:
        raise HTTPException(404, f"No integration found for {provider!r}.")

    # Best-effort token revocation
    try:
        tokens = decrypt_tokens(integ.encrypted_tokens) if integ.encrypted_tokens else {}
        if provider in _GOOGLE_PROVIDERS and tokens.get("access_token"):
            from app.integrations.google_oauth import revoke_google_token
            await revoke_google_token(tokens.get("refresh_token") or tokens["access_token"])
        elif provider == _GITHUB_PROVIDER and tokens.get("access_token"):
            from app.integrations.github import revoke_github_token
            await revoke_github_token(tokens["access_token"])
    except Exception as exc:
        logger.warning("Token revocation failed (non-fatal): %s", exc)

    # Delete SQLite file if applicable
    if provider == "sqlite":
        db_path = (integ.config or {}).get("db_path", "")
        if db_path:
            try:
                import os as _os
                _os.remove(db_path)
            except OSError:
                pass

    await db.delete(integ)
    return {"ok": True}
