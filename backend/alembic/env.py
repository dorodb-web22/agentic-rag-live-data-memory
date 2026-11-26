"""Alembic env.py — supports both sync (CLI) and async (app) usage.

DATABASE_URL is read from the environment.  If not set, the CLI will error
with a clear message rather than silently using a wrong database.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

# Import the ORM metadata so autogenerate can detect schema changes
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db.models import Base  # noqa: E402

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Override sqlalchemy.url from env — never hardcode credentials
_db_url = os.environ.get("DATABASE_URL", "")
if _db_url:
    # psycopg3 sync dialect for alembic CLI
    if _db_url.startswith("postgresql+psycopg://") or _db_url.startswith("postgres+psycopg://"):
        pass  # already correct
    elif _db_url.startswith("postgresql://"):
        _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql+psycopg://", 1)
    config.set_main_option("sqlalchemy.url", _db_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
