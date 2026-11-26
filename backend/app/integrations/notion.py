"""Notion connector — workspace pages & databases via Notion public OAuth.

OAuth: Notion's public integration OAuth v2.
  Authorization URL: https://api.notion.com/v1/oauth/authorize
  Token URL:         https://api.notion.com/v1/oauth/token

Required env vars:
  NOTION_OAUTH_CLIENT_ID     — Notion integration OAuth client ID
  NOTION_OAUTH_CLIENT_SECRET — Notion integration OAuth client secret
  APP_BASE_URL               — callback base

Citation key format: Notion-{short_page_id}
"""
from __future__ import annotations

import base64
import logging
import os
import urllib.parse
from typing import Any

import httpx

from app.integrations.base import BaseConnector
from app.integrations.registry import register

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_AUTH_URL = "https://api.notion.com/v1/oauth/authorize"
NOTION_TOKEN_URL = "https://api.notion.com/v1/oauth/token"
NOTION_VERSION = "2022-06-28"


def _app_base_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://localhost:8000").rstrip("/")


def build_notion_auth_url(state: str) -> str:
    client_id = os.environ["NOTION_OAUTH_CLIENT_ID"]
    redirect_uri = f"{_app_base_url()}/api/integrations/notion/callback"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "owner": "user",
        "state": state,
    }
    return NOTION_AUTH_URL + "?" + urllib.parse.urlencode(params)


async def exchange_notion_code(code: str) -> dict[str, Any]:
    client_id = os.environ["NOTION_OAUTH_CLIENT_ID"]
    client_secret = os.environ["NOTION_OAUTH_CLIENT_SECRET"]
    redirect_uri = f"{_app_base_url()}/api/integrations/notion/callback"

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            NOTION_TOKEN_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
            },
            json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        return resp.json()


def _short_id(page_id: str) -> str:
    """Return first 8 chars of page_id (without hyphens) as citation key fragment."""
    return page_id.replace("-", "")[:8]


def _extract_title(props: dict) -> str:
    """Extract the page title from Notion page properties."""
    for key in ("title", "Title", "Name", "name"):
        prop = props.get(key, {})
        title_parts = prop.get("title", [])
        if title_parts:
            return "".join(p.get("plain_text", "") for p in title_parts)
    return "(untitled)"


def _extract_rich_text(block: dict) -> str:
    """Extract plain text from a Notion block."""
    btype = block.get("type", "")
    content = block.get(btype, {})
    rich = content.get("rich_text", [])
    return "".join(p.get("plain_text", "") for p in rich)


@register
class NotionConnector(BaseConnector):
    provider = "notion"
    display_name = "Notion"
    category = "docs"
    description = "Workspace pages & databases"
    auth_type = "oauth"
    available = True
    suggested_prompts = [
        "Search my Notion docs for roadmap notes",
        "What action items are in my Notion workspace?",
        "Summarize the meeting notes from this week",
    ]

    async def fetch(self, query: str) -> list[dict[str, Any]]:
        if not self.is_connected:
            return []
        access_token = self.tokens.get("access_token")
        if not access_token:
            return []

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

        records: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Search pages matching query
            try:
                search_resp = await client.post(
                    f"{NOTION_API}/search",
                    headers=headers,
                    json={
                        "query": query,
                        "filter": {"value": "page", "property": "object"},
                        "page_size": 10,
                    },
                )
                if search_resp.status_code == 401:
                    logger.warning("Notion access token expired")
                    return []
                search_resp.raise_for_status()
                pages = search_resp.json().get("results", [])
            except httpx.HTTPError as exc:
                logger.warning("Notion search error: %s", exc)
                return []

            for page in pages[:10]:
                page_id = page.get("id", "")
                props = page.get("properties", {})
                title = _extract_title(props)
                last_edited = page.get("last_edited_time", "")
                url = page.get("url", "")

                # Fetch first few blocks for excerpt
                excerpt = ""
                try:
                    blocks_resp = await client.get(
                        f"{NOTION_API}/blocks/{page_id}/children",
                        headers=headers,
                        params={"page_size": 5},
                    )
                    if blocks_resp.status_code == 200:
                        blocks = blocks_resp.json().get("results", [])
                        excerpt = " ".join(
                            _extract_rich_text(b) for b in blocks
                        )[:400]
                except httpx.HTTPError:
                    pass

                records.append(
                    {
                        "source": "notion",
                        "citation_key": f"Notion-{_short_id(page_id)}",
                        "page_id": page_id,
                        "title": title,
                        "last_edited": last_edited,
                        "excerpt": excerpt,
                        "url": url,
                    }
                )

        # Sprint 3: Best-effort pgvector + FTS hybrid indexing & retrieval scoped to user_id
        user_id = getattr(self.integration, "user_id", None)
        if self.db is not None and isinstance(user_id, str) and user_id.strip():
            try:
                from app.rag.hybrid_search import hybrid_search_chunks, ingest_connector_records

                if records:
                    await ingest_connector_records(
                        self.db,
                        user_id=user_id,
                        provider="notion",
                        records=records,
                    )
                hybrid_hits = await hybrid_search_chunks(
                    self.db,
                    user_id=user_id,
                    query=query,
                    providers=["notion"],
                    top_k=10,
                )
                if hybrid_hits:
                    seen = {r["citation_key"] for r in hybrid_hits if r.get("citation_key")}
                    merged = list(hybrid_hits)
                    for rec in records:
                        if rec.get("citation_key") not in seen:
                            merged.append(rec)
                    return merged[:10]
            except Exception as exc:
                logger.debug("Notion hybrid search skipped (%s); returning live records", type(exc).__name__)

        return records
