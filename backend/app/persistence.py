"""PostgreSQL checkpoint persistence for LangGraph thread-scoped conversational memory.

Implements Week 5 Backend Infrastructure requirements using ``langgraph-checkpoint-postgres``
and ``psycopg_pool.ConnectionPool``.
"""

import logging
import os
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

DEFAULT_POOL_MIN_SIZE = 1
DEFAULT_POOL_MAX_SIZE = 10


class PersistenceError(RuntimeError):
    """Raised when the PostgreSQL persistence layer fails to initialize or operate."""


class PersistenceNotConfiguredError(PersistenceError):
    """Raised when DATABASE_URL is missing or invalid when PostgreSQL persistence is requested."""


def _parse_pool_int(env_var: str, default: int) -> int:
    raw = os.getenv(env_var)
    if not raw or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning(
            "%s='%s' is not a valid integer; falling back to default %d.",
            env_var,
            raw,
            default,
        )
        return default
    if value < 1:
        raise PersistenceError(f"{env_var} must be >= 1, got {value}.")
    return value


def resolve_database_url(database_url: str | None = None) -> str:
    """Resolve and validate the PostgreSQL connection string from argument or environment."""
    raw = database_url if database_url is not None else os.getenv("DATABASE_URL", "")
    cleaned = raw.strip()
    if not cleaned:
        raise PersistenceNotConfiguredError(
            "DATABASE_URL is not configured. Set DATABASE_URL to enable PostgreSQL checkpoint persistence."
        )
    if not (
        cleaned.startswith("postgresql://")
        or cleaned.startswith("postgres://")
    ):
        raise PersistenceNotConfiguredError(
            "DATABASE_URL must start with 'postgresql://' or 'postgres://'."
        )
    return cleaned


def create_connection_pool(
    database_url: str | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
    open_pool: bool = True,
    connect_timeout: int = 5,
) -> ConnectionPool:
    """Create a Psycopg 3 ConnectionPool configured for LangGraph's PostgresSaver.

    LangGraph's ``PostgresSaver`` requires ``autocommit=True`` (so ``.setup()`` DDL
    and checkpoint writes commit immediately) and ``row_factory=dict_row`` (so
    checkpoint rows support dict-style column access).
    """
    conninfo = resolve_database_url(database_url)
    resolved_min = min_size if min_size is not None else _parse_pool_int("POSTGRES_POOL_MIN_SIZE", DEFAULT_POOL_MIN_SIZE)
    resolved_max = max_size if max_size is not None else _parse_pool_int("POSTGRES_POOL_MAX_SIZE", DEFAULT_POOL_MAX_SIZE)

    if resolved_min < 1:
        raise PersistenceError(f"min_size must be >= 1, got {resolved_min}.")
    if resolved_max < 1 or resolved_max < resolved_min:
        raise PersistenceError(
            f"max_size ({resolved_max}) must be >= 1 and >= min_size ({resolved_min})."
        )

    try:
        pool = ConnectionPool(
            conninfo=conninfo,
            min_size=resolved_min,
            max_size=resolved_max,
            open=False,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
                "connect_timeout": connect_timeout,
            },
        )
        if open_pool:
            pool.open(wait=True, timeout=float(connect_timeout + 2))
        return pool
    except PersistenceError:
        raise
    except Exception as exc:
        logger.exception("Failed to initialize PostgreSQL connection pool")
        raise PersistenceError(
            f"PostgreSQL connection initialization failed ({type(exc).__name__})."
        ) from exc


def create_postgres_checkpointer(
    pool: ConnectionPool,
    setup_schema: bool = True,
) -> PostgresSaver:
    """Instantiate a LangGraph PostgresSaver from an active ConnectionPool and run migrations."""
    try:
        checkpointer = PostgresSaver(pool)
        if setup_schema:
            checkpointer.setup()
        return checkpointer
    except Exception as exc:
        logger.exception("Failed to initialize or setup PostgresSaver schema")
        raise PersistenceError(
            f"PostgreSQL checkpointer setup failed ({type(exc).__name__})."
        ) from exc


class PostgresPersistenceManager:
    """Manages the lifecycle of the PostgreSQL connection pool and LangGraph PostgresSaver."""

    def __init__(
        self,
        database_url: str | None = None,
        min_size: int | None = None,
        max_size: int | None = None,
        connect_timeout: int = 5,
    ) -> None:
        self._database_url = database_url
        self._min_size = min_size
        self._max_size = max_size
        self._connect_timeout = connect_timeout
        self._pool: ConnectionPool | None = None
        self._checkpointer: PostgresSaver | None = None

    @property
    def pool(self) -> ConnectionPool | None:
        return self._pool

    @property
    def checkpointer(self) -> PostgresSaver | None:
        return self._checkpointer

    def start(self, setup_schema: bool = True) -> PostgresSaver:
        """Open the connection pool, initialize PostgresSaver, and ensure checkpoint tables exist."""
        if self._checkpointer is not None and self._pool is not None:
            return self._checkpointer

        pool = create_connection_pool(
            database_url=self._database_url,
            min_size=self._min_size,
            max_size=self._max_size,
            open_pool=True,
            connect_timeout=self._connect_timeout,
        )
        try:
            checkpointer = create_postgres_checkpointer(pool, setup_schema=setup_schema)
        except Exception:
            pool.close()
            raise

        self._pool = pool
        self._checkpointer = checkpointer
        return checkpointer

    def close(self) -> None:
        """Close the PostgreSQL connection pool cleanly on application shutdown."""
        if self._pool is not None:
            try:
                self._pool.close()
            except Exception:
                logger.exception("Error while closing PostgreSQL connection pool")
            finally:
                self._pool = None
                self._checkpointer = None

    def __enter__(self) -> PostgresSaver:
        return self.start()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


def init_optional_checkpointer_from_env() -> tuple[PostgresPersistenceManager | None, BaseCheckpointSaver | None]:
    """Initialize a PostgreSQL checkpointer if DATABASE_URL is set in the environment.

    If DATABASE_URL is unset or blank, returns ``(None, None)`` so unit tests and
    local stateless development work out-of-the-box without requiring a running
    PostgreSQL server unless DATABASE_URL is provided.
    """
    raw_url = os.getenv("DATABASE_URL", "").strip()
    if not raw_url:
        return None, None

    manager = PostgresPersistenceManager(database_url=raw_url)
    checkpointer = manager.start(setup_schema=True)
    return manager, checkpointer
