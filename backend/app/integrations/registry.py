"""Plugin connector registry.

Connectors self-register via @register decorator.
Import order: registry must be imported BEFORE connector modules
so the decorator is available. The bottom of this file imports all
connectors to trigger registration.

Export for Dorothy's agent endpoint:
    from app.integrations.registry import get_user_connectors
"""
from __future__ import annotations

import logging
import time
from typing import Any, TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.integrations.base import BaseConnector

logger = logging.getLogger(__name__)

# Maps provider string → connector class
REGISTRY: dict[str, type["BaseConnector"]] = {}


def register(cls: type["BaseConnector"]) -> type["BaseConnector"]:
    """Class decorator — registers a connector in REGISTRY."""
    REGISTRY[cls.provider] = cls
    return cls


# ── Coming-soon stubs (not in REGISTRY — no fetch(), no OAuth) ───────────────

COMING_SOON_STUBS: list[dict[str, Any]] = [
    {
        "provider": "google_sheets",
        "display_name": "Google Sheets",
        "category": "spreadsheets",
        "description": "Live spreadsheets & tabs (Incremental Google OAuth)",
        "auth_type": "oauth",
        "available": False,
        "status": "coming_soon",
        "scope_summary": None,
        "config": {},
        "suggested_prompts": [],
        "connected_at": None,
    },
    {
        "provider": "google_calendar",
        "display_name": "Google Calendar",
        "category": "calendar",
        "description": "Events, schedules & availability (Incremental Google OAuth)",
        "auth_type": "oauth",
        "available": False,
        "status": "coming_soon",
        "scope_summary": None,
        "config": {},
        "suggested_prompts": [],
        "connected_at": None,
    },
]

# Canonical display order for GET /api/integrations
_PROVIDER_ORDER = ["github", "gmail", "notion", "sqlite", "google_sheets", "google_calendar"]


# ── Auto-refresh helpers ──────────────────────────────────────────────────────

_GOOGLE_PROVIDERS = {"gmail", "google_sheets", "google_calendar"}


async def _maybe_refresh_google(
    tokens: dict, integration: Any, db: AsyncSession
) -> dict:
    """Refresh Google access token if it expires within 60 seconds."""
    expires_at = tokens.get("expires_at", 0)
    if time.time() < expires_at - 60:
        return tokens  # still valid

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        logger.warning("No refresh_token for %s — marking needs_reauth", integration.provider)
        integration.status = "needs_reauth"
        return tokens

    try:
        from app.integrations.google_oauth import refresh_google_token
        from app.integrations.crypto import encrypt_tokens

        new_data = await refresh_google_token(refresh_token)
        tokens = {**tokens, **new_data}
        integration.encrypted_tokens = encrypt_tokens(tokens)
        if "expires_in" in new_data:
            tokens["expires_at"] = time.time() + new_data["expires_in"] - 60
        logger.info("Google token refreshed for provider=%s", integration.provider)
    except Exception as exc:
        logger.warning("Google token refresh failed: %s — marking needs_reauth", exc)
        integration.status = "needs_reauth"

    return tokens


# ── Public API ────────────────────────────────────────────────────────────────


async def get_user_connectors(
    user_id: str, db: AsyncSession
) -> list["BaseConnector"]:
    """Return instantiated, token-fresh connectors for all connected integrations.

    Called by Dorothy's agent endpoint to build the tool list per request.
    Uses a single DB query + per-connector token refresh if needed.
    NO per-request subprocess spawning.
    """
    from app.db.models import UserIntegration
    from app.integrations.crypto import decrypt_tokens

    result = await db.execute(
        select(UserIntegration).where(
            UserIntegration.user_id == user_id,
            UserIntegration.status.in_(["connected"]),
        )
    )
    integrations = result.scalars().all()

    connectors: list["BaseConnector"] = []
    for integ in integrations:
        cls = REGISTRY.get(integ.provider)
        if cls is None:
            continue
        try:
            tokens = decrypt_tokens(integ.encrypted_tokens) if integ.encrypted_tokens else {}
            # Auto-refresh Google tokens before instantiating
            if integ.provider in _GOOGLE_PROVIDERS:
                tokens = await _maybe_refresh_google(tokens, integ, db)
            connectors.append(cls(integration=integ, tokens=tokens))
        except Exception as exc:
            logger.warning("Failed to build connector for %s: %s", integ.provider, exc)

    return connectors


async def get_catalog_for_user(
    user_id: str, db: AsyncSession
) -> list[dict[str, Any]]:
    """Return the full connector catalog with per-user status merged in.

    Adding a new connector auto-appears here — zero frontend rewrites.
    """
    from app.db.models import UserIntegration
    from app.integrations.crypto import decrypt_tokens

    result = await db.execute(
        select(UserIntegration).where(UserIntegration.user_id == user_id)
    )
    user_integs: dict[str, Any] = {i.provider: i for i in result.scalars().all()}

    catalog: list[dict[str, Any]] = []
    for provider in _PROVIDER_ORDER:
        if provider in REGISTRY:
            cls = REGISTRY[provider]
            integ = user_integs.get(provider)
            connector = cls(integration=integ, tokens={})
            catalog.append(connector.catalog_entry())
        else:
            # Coming-soon stub
            stub = next((s for s in COMING_SOON_STUBS if s["provider"] == provider), None)
            if stub:
                catalog.append(stub)

    return catalog


# ── Trigger connector registration by importing all connector modules ─────────
# (keep at bottom to avoid circular imports)
import app.integrations.github  # noqa: E402, F401
import app.integrations.gmail  # noqa: E402, F401
import app.integrations.notion  # noqa: E402, F401
import app.integrations.sqlite_upload  # noqa: E402, F401
