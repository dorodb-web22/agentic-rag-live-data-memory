"""Google Sheets connector — read-only spreadsheets & tabs.

OAuth scopes:
  - https://www.googleapis.com/auth/spreadsheets.readonly
  - https://www.googleapis.com/auth/drive.metadata.readonly (zero-config sheet listing)

Uses Incremental Google OAuth (see google_oauth.py).
Citation key format: GSheet-{short_id}-{tab}
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any

import httpx

from app.integrations.base import BaseConnector
from app.integrations.registry import register

logger = logging.getLogger(__name__)

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE_API = "https://www.googleapis.com/drive/v3/files"

_SHEETS_URL_RE = re.compile(
    r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]{10,128})",
    re.IGNORECASE,
)
_SAFE_SHEET_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{10,128}$")


def _is_safe_spreadsheet_id(sheet_id: str) -> bool:
    return bool(_SAFE_SHEET_ID_RE.match(sheet_id or ""))


def _extract_spreadsheet_ids_from_query(query: str) -> list[str]:
    found: list[str] = []
    for match in _SHEETS_URL_RE.finditer(query or ""):
        sid = match.group(1)
        if _is_safe_spreadsheet_id(sid) and sid not in found:
            found.append(sid)
    return found


def _short_id(spreadsheet_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", spreadsheet_id or "")
    return cleaned[:8] if cleaned else "unknown"


def _safe_tab_key(tab_name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", (tab_name or "").replace(" ", "_"))
    return cleaned[:16] or "Sheet1"


async def _discover_recent_spreadsheets(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    limit: int = 3,
) -> list[dict[str, str]]:
    """Auto-discover the user's most recently modified Google Sheets via Drive metadata."""
    try:
        resp = await client.get(
            DRIVE_API,
            headers=headers,
            params={
                "q": "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
                "orderBy": "modifiedTime desc",
                "pageSize": max(limit, 5),
                "fields": "files(id,name,webViewLink,modifiedTime)",
            },
        )
        if resp.status_code == 401:
            logger.warning("Google Sheets/Drive access token expired")
            return []
        resp.raise_for_status()
        files = resp.json().get("files", [])
        out: list[dict[str, str]] = []
        for f in files:
            sid = str(f.get("id") or "")
            if _is_safe_spreadsheet_id(sid):
                out.append(
                    {
                        "id": sid,
                        "name": str(f.get("name") or ""),
                        "url": str(f.get("webViewLink") or f"https://docs.google.com/spreadsheets/d/{sid}"),
                    }
                )
                if len(out) >= limit:
                    break
        return out
    except httpx.HTTPError as exc:
        logger.warning("Google Drive spreadsheet discovery error: %s", exc)
        return []


@register
class GoogleSheetsConnector(BaseConnector):
    provider = "google_sheets"
    display_name = "Google Sheets"
    category = "spreadsheets"
    description = "Live spreadsheets & tabs (Read-only)"
    auth_type = "oauth"
    available = True
    suggested_prompts = [
        "List my recent Google Sheets and summarize their tabs",
        "Summarize the key numbers in my latest spreadsheet",
    ]

    async def fetch(self, query: str) -> list[dict[str, Any]]:
        if not self.is_connected:
            return []
        access_token = self.tokens.get("access_token")
        if not access_token:
            return []

        headers = {"Authorization": f"Bearer {access_token}"}

        # Priority: explicit Sheets URL in query -> user-configured IDs -> Drive auto-discovery
        url_ids = _extract_spreadsheet_ids_from_query(query)
        cfg_ids = [
            s.strip()
            for s in (self.integration.config.get("spreadsheet_ids", []) if self.integration else [])
            if isinstance(s, str) and _is_safe_spreadsheet_id(s.strip())
        ]

        records: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            sheet_ids: list[str] = []
            for sid in url_ids + cfg_ids:
                if sid not in sheet_ids:
                    sheet_ids.append(sid)

            if not sheet_ids:
                discovered = await _discover_recent_spreadsheets(client, headers, limit=3)
                sheet_ids = [d["id"] for d in discovered]

            if not sheet_ids:
                return []

            for sid in sheet_ids[:3]:
                try:
                    meta_resp = await client.get(
                        f"{SHEETS_API}/{sid}",
                        headers=headers,
                        params={"fields": "properties.title,spreadsheetUrl,sheets.properties.title"},
                    )
                    if meta_resp.status_code == 401:
                        logger.warning("Google Sheets token expired for %s", sid)
                        return records
                    meta_resp.raise_for_status()
                    meta = meta_resp.json()
                    title = (meta.get("properties") or {}).get("title") or sid
                    url = meta.get("spreadsheetUrl") or f"https://docs.google.com/spreadsheets/d/{sid}"
                    tabs = [
                        (s.get("properties") or {}).get("title", "")
                        for s in (meta.get("sheets") or [])
                        if isinstance(s, dict)
                    ]
                    tabs = [t for t in tabs if t] or ["Sheet1"]

                    # Read top 25 rows of the first 2 tabs
                    for tab_name in tabs[:2]:
                        quoted_tab = tab_name.replace("'", "''")
                        range_expr = urllib.parse.quote(f"'{quoted_tab}'!A1:Z25", safe="")
                        val_resp = await client.get(
                            f"{SHEETS_API}/{sid}/values/{range_expr}",
                            headers=headers,
                        )
                        if val_resp.status_code != 200:
                            continue
                        values = val_resp.json().get("values") or []
                        headers_row = [str(c) for c in values[0]] if values else []
                        data_rows: list[dict[str, str]] = []
                        for raw_row in values[1:21]:
                            row_obj = {
                                (headers_row[i] if i < len(headers_row) and headers_row[i] else f"col_{i+1}"): str(cell)
                                for i, cell in enumerate(raw_row)
                            }
                            data_rows.append(row_obj)

                        records.append(
                            {
                                "source": "google_sheets",
                                "citation_key": f"GSheet-{_short_id(sid)}-{_safe_tab_key(tab_name)}",
                                "spreadsheet_id": sid,
                                "spreadsheet_title": title,
                                "sheet_name": tab_name,
                                "headers": headers_row,
                                "rows": data_rows,
                                "row_count": len(data_rows),
                                "url": url,
                            }
                        )
                except httpx.HTTPError as exc:
                    logger.warning("Google Sheets fetch error (%s): %s", sid, exc)

        return records
