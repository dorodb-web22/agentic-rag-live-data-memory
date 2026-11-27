"""Google Calendar connector — read-only events, schedules & availability.

OAuth scope: https://www.googleapis.com/auth/calendar.readonly
Uses Incremental Google OAuth (see google_oauth.py).

Citation key format: GCal-{short_event_id}
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Any

import httpx

from app.integrations.base import BaseConnector
from app.integrations.registry import register

logger = logging.getLogger(__name__)

GCAL_API = "https://www.googleapis.com/calendar/v3"

_PAST_KEYWORDS = {"past", "last", "yesterday", "previous", "earlier"}
_BROAD_SCHEDULE_WORDS = {
    "calendar",
    "schedule",
    "events",
    "event",
    "meetings",
    "meeting",
    "today",
    "tomorrow",
    "week",
    "upcoming",
    "free",
    "busy",
    "availability",
    "available",
    "agenda",
    "summarize",
    "summary",
    "show",
    "list",
    "what",
    "when",
}


def _short_id(event_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", event_id or "")
    return cleaned[:10] if cleaned else "unknown"


def _has_word(text: str, words: set[str]) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


@register
class GoogleCalendarConnector(BaseConnector):
    provider = "google_calendar"
    display_name = "Google Calendar"
    category = "calendar"
    description = "Events, schedules & availability (Read-only)"
    auth_type = "oauth"
    available = True
    suggested_prompts = [
        "What events do I have on my calendar this week?",
        "Am I free tomorrow afternoon?",
        "Summarize my upcoming meetings",
    ]

    async def fetch(self, query: str) -> list[dict[str, Any]]:
        if not self.is_connected:
            return []
        access_token = self.tokens.get("access_token")
        if not access_token:
            return []

        now = datetime.now(timezone.utc)
        q_lower = (query or "").lower()
        include_past = _has_word(q_lower, _PAST_KEYWORDS)
        start_dt = (
            now - timedelta(days=14)
            if include_past
            else now.replace(hour=0, minute=0, second=0, microsecond=0)
        )
        end_dt = now + timedelta(days=30)

        params: dict[str, Any] = {
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 25,
            "timeMin": start_dt.isoformat(),
            "timeMax": end_dt.isoformat(),
        }

        # Only pass Google's text filter `q` for targeted searches (e.g. "dentist" or "Priya"),
        # never for broad schedule questions like "what meetings do I have this week?"
        tokens = re.findall(r"[a-zA-Z0-9]+", q_lower)
        specific_terms = [t for t in tokens if len(t) >= 3 and t not in _BROAD_SCHEDULE_WORDS]
        if len(specific_terms) == 1:
            params["q"] = specific_terms[0]

        headers = {"Authorization": f"Bearer {access_token}"}
        records: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    f"{GCAL_API}/calendars/primary/events",
                    headers=headers,
                    params=params,
                )
                if resp.status_code == 401:
                    logger.warning("Google Calendar access token expired")
                    return []
                resp.raise_for_status()
                items = resp.json().get("items", [])

                # If a targeted `q` search returned nothing, fall back to the full window
                if not items and "q" in params:
                    params.pop("q", None)
                    resp2 = await client.get(
                        f"{GCAL_API}/calendars/primary/events",
                        headers=headers,
                        params=params,
                    )
                    if resp2.status_code == 200:
                        items = resp2.json().get("items", [])
            except httpx.HTTPError as exc:
                logger.warning("Google Calendar fetch error: %s", exc)
                return []

        for item in items[:25]:
            ev_id = str(item.get("id") or "")
            start_obj = item.get("start") or {}
            end_obj = item.get("end") or {}
            start_val = start_obj.get("dateTime") or start_obj.get("date") or ""
            end_val = end_obj.get("dateTime") or end_obj.get("date") or ""
            attendees = [
                a.get("email", "")
                for a in (item.get("attendees") or [])
                if isinstance(a, dict) and a.get("email")
            ][:10]
            records.append(
                {
                    "source": "google_calendar",
                    "citation_key": f"GCal-{_short_id(ev_id)}",
                    "event_id": ev_id,
                    "summary": item.get("summary") or "(no title)",
                    "start": start_val,
                    "end": end_val,
                    "location": item.get("location") or "",
                    "organizer": (item.get("organizer") or {}).get("email", ""),
                    "attendees": attendees,
                    "status": item.get("status") or "",
                    "description": (item.get("description") or "")[:300],
                    "url": item.get("htmlLink") or "",
                }
            )

        return records
