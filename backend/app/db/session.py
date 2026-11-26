"""Async SQLAlchemy engine + session factory.

Connection string is derived from DATABASE_URL.  Supports both
  postgresql://user:pass@host/db          (psycopg3 sync, used by alembic)
  postgresql+psycopg://user:pass@host/db  (psycopg3 async, used by FastAPI)

Tests override DATABASE_URL before importing this module to point at
a test-scoped database or use app.dependency_overrides[get_db].
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_raw_url = os.getenv("DATABASE_URL", "")


def _async_url(url: str) -> str:
    """Translate a standard postgres URL to the psycopg3 async dialect."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg" + url[len(prefix) - 3:]
    return url  # already correct or empty


ASYNC_DATABASE_URL = _async_url(_raw_url)

# NullPool keeps every request's connection lifecycle explicit (good for async).
# Switch to AsyncAdaptedQueuePool + pool_size for high-throughput production.
_engine = create_async_engine(
    ASYNC_DATABASE_URL or "postgresql+psycopg://localhost/agentic_rag",
    echo=os.getenv("SQLALCHEMY_ECHO", "").lower() in ("1", "true"),
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields one AsyncSession per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
