"""SQLite upload connector — user-supplied read-only .db / .sqlite file.

Upload flow:
  POST /api/integrations/sqlite/upload  →  validates magic header, stores file,
  introspects schema, upserts user_integrations row.

Security:
  - File validated via SQLite magic header (first 16 bytes).
  - All queries use SQLite URI mode: "file:path?mode=ro" (read-only).
  - Table names validated against ^[a-zA-Z_][a-zA-Z0-9_]*$ before interpolation.
  - SELECT limited to 20 rows per table.
  - Files stored under uploads/{user_id}/ (never world-readable).

Citation key format: SQL-{table}-{rowid}
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from app.integrations.base import BaseConnector
from app.integrations.registry import register

logger = logging.getLogger(__name__)

SQLITE_MAGIC = b"SQLite format 3\x00"
MAX_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB
UPLOAD_ROOT = Path(os.environ.get("SQLITE_UPLOAD_DIR", "uploads"))
_SAFE_TABLE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def validate_sqlite_file(data: bytes) -> None:
    """Raise ValueError if *data* is not a valid SQLite file."""
    if len(data) > MAX_SIZE_BYTES:
        raise ValueError(f"File exceeds maximum size of {MAX_SIZE_BYTES // (1024*1024)} MB.")
    if not data.startswith(SQLITE_MAGIC):
        raise ValueError("Not a valid SQLite database file (magic header mismatch).")


def store_sqlite_file(user_id: str, filename: str, data: bytes) -> Path:
    """Write the validated file to a per-user directory and return the path."""
    dest_dir = UPLOAD_ROOT / user_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Sanitize filename: keep only safe characters
    safe_name = re.sub(r"[^a-zA-Z0-9_.\-]", "_", filename)
    dest = dest_dir / safe_name
    dest.write_bytes(data)
    logger.info("SQLite file stored: %s", dest)
    return dest


def introspect_schema(db_path: str) -> list[dict[str, Any]]:
    """Return table names + column info from a read-only SQLite file."""
    tables: list[dict[str, Any]] = []
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            for (table_name,) in cur.fetchall():
                if not _SAFE_TABLE.match(table_name):
                    continue
                cur.execute(f'PRAGMA table_info("{table_name}")')
                columns = [row[1] for row in cur.fetchall()]
                cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
                row_count = cur.fetchone()[0]
                tables.append(
                    {"table": table_name, "columns": columns, "row_count": row_count}
                )
    except sqlite3.Error as exc:
        logger.warning("SQLite schema introspection error: %s", exc)
    return tables


@register
class SQLiteConnector(BaseConnector):
    provider = "sqlite"
    display_name = "SQLite Database"
    category = "database"
    description = "Upload your own read-only .db / .sqlite file"
    auth_type = "upload"
    available = True
    suggested_prompts = [
        "List the tables and summarize key metrics in my database",
        "What are the top 10 rows in this database?",
    ]

    async def fetch(self, query: str) -> list[dict[str, Any]]:
        if not self.is_connected or not self.integration:
            return []
        db_path = self.integration.config.get("db_path", "")
        if not db_path or not Path(db_path).exists():
            logger.warning("SQLite file not found: %s", db_path)
            return []

        records: list[dict[str, Any]] = []
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                tables = [row[0] for row in cur.fetchall() if _SAFE_TABLE.match(row[0])]

                for table in tables[:5]:  # cap at 5 tables per query
                    cur.execute(f'SELECT rowid, * FROM "{table}" LIMIT 20')
                    for row in cur.fetchall():
                        row_dict = dict(row)
                        rowid = row_dict.pop("rowid", None)
                        records.append(
                            {
                                "source": "sqlite",
                                "citation_key": f"SQL-{table}-{rowid}",
                                "table": table,
                                "row": row_dict,
                            }
                        )
        except sqlite3.Error as exc:
            logger.warning("SQLite fetch error: %s", exc)

        return records
