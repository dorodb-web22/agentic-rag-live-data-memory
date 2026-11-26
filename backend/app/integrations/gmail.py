"""Gmail connector — read-only email & thread search.

OAuth scope: https://www.googleapis.com/auth/gmail.readonly
Uses Incremental Google OAuth (see google_oauth.py).

Fetches message headers + snippets; never downloads full body for privacy.
Citation key format: Gmail-{short_message_id}
"""
from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.integrations.base import BaseConnector
from app.integrations.registry import register

logger = logging.getLogger(__name__)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


def _short_id(message_id: str) -> str:
    """Return a short, URL-safe citation key fragment from a Gmail message ID."""
    return message_id[:12] if message_id else "unknown"


@register
class GmailConnector(BaseConnector):
    provider = "gmail"
    display_name = "Gmail"
    category = "communication"
    description = "Read-only email & thread search"
    auth_type = "oauth"
    available = True
    suggested_prompts = [
        "Summarize important emails from this week",
        "Find emails about invoices or deadlines",
        "What did my team email me about yesterday?",
    ]

    async def fetch(self, query: str) -> list[dict[str, Any]]:
        if not self.is_connected:
            return []
        access_token = self.tokens.get("access_token")
        if not access_token:
            return []

        headers = {"Authorization": f"Bearer {access_token}"}

        records: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. Search for messages matching the query
            try:
                search_resp = await client.get(
                    f"{GMAIL_API}/messages",
                    headers=headers,
                    params={"q": query, "maxResults": 15},
                )
                if search_resp.status_code == 401:
                    logger.warning("Gmail access token expired")
                    return []
                search_resp.raise_for_status()
                messages = search_resp.json().get("messages", [])
            except httpx.HTTPError as exc:
                logger.warning("Gmail search error: %s", exc)
                return []

            # 2. Fetch metadata for each message (headers + snippet only)
            for msg in messages[:15]:
                msg_id = msg.get("id", "")
                try:
                    meta_resp = await client.get(
                        f"{GMAIL_API}/messages/{msg_id}",
                        headers=headers,
                        params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
                    )
                    meta_resp.raise_for_status()
                    data = meta_resp.json()
                    headers_list = data.get("payload", {}).get("headers", [])
                    hmap = {h["name"]: h["value"] for h in headers_list}
                    records.append(
                        {
                            "source": "gmail",
                            "citation_key": f"Gmail-{_short_id(msg_id)}",
                            "message_id": msg_id,
                            "thread_id": data.get("threadId", ""),
                            "subject": hmap.get("Subject", "(no subject)"),
                            "sender": hmap.get("From", ""),
                            "date": hmap.get("Date", ""),
                            "snippet": data.get("snippet", ""),
                            "url": f"https://mail.google.com/mail/u/0/#inbox/{msg_id}",
                        }
                    )
                except httpx.HTTPError as exc:
                    logger.warning("Gmail message fetch error (%s): %s", msg_id, exc)

        return records
