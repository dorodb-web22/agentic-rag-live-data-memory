"""BaseConnector — the plugin contract every connector must implement.

Adding a new connector in the future requires only:
  1. Create backend/app/integrations/{provider}.py
  2. Subclass BaseConnector, fill in ClassVars, implement fetch()
  3. Decorate with @register  (auto-registers in REGISTRY)

No changes to auth, DB schema, routes, or Dorothy's frontend.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.db.models import UserIntegration


class BaseConnector(ABC):
    # ── ClassVars — set once per connector subclass ─────────────────────────
    provider: ClassVar[str]
    display_name: ClassVar[str]
    category: ClassVar[str]          # "code" | "communication" | "docs" | "database" | …
    description: ClassVar[str]
    auth_type: ClassVar[str]         # "oauth" | "upload"
    available: ClassVar[bool] = True
    suggested_prompts: ClassVar[list[str]] = []

    # ── Instance ─────────────────────────────────────────────────────────────
    def __init__(
        self,
        integration: UserIntegration | None = None,
        tokens: dict[str, Any] | None = None,
        db: Any | None = None,
    ) -> None:
        self.integration = integration
        self.tokens: dict[str, Any] = tokens or {}
        self.db = db

    # ── Abstract ─────────────────────────────────────────────────────────────
    @abstractmethod
    async def fetch(self, query: str) -> list[dict[str, Any]]:
        """Fetch records relevant to *query*.

        Returns a list of unified citation dicts:
          GitHub  → { source, citation_key, number, title, state, url, author, body_excerpt }
          Gmail   → { source, citation_key, message_id, thread_id, subject, sender, date, snippet, url }
          Notion  → { source, citation_key, page_id, title, last_edited, excerpt, url }
          SQLite  → { source, citation_key, table, row: {...} }
        """

    # ── Shared ───────────────────────────────────────────────────────────────
    def catalog_entry(self) -> dict[str, Any]:
        """Return one entry for GET /api/integrations response."""
        integ = self.integration
        return {
            "provider": self.provider,
            "display_name": self.display_name,
            "category": self.category,
            "description": self.description,
            "auth_type": self.auth_type,
            "available": self.available,
            "status": integ.status if integ else "disconnected",
            "scope_summary": integ.scope_summary if integ else None,
            "config": integ.config if integ else {},
            "suggested_prompts": self.suggested_prompts,
            "connected_at": (
                integ.connected_at.isoformat() if integ and integ.connected_at else None
            ),
        }

    @property
    def is_connected(self) -> bool:
        return self.integration is not None and self.integration.status == "connected"
