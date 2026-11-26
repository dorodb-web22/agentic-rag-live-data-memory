"""Sprint 3 — Enable pgvector and create multi-tenant document_chunks table.

Supports semantic (pgvector HNSW cosine) + lexical (Postgres FTS/BM25 ts_rank_cd)
hybrid retrieval over Notion pages & Gmail threads, strictly scoped by user_id.

Revision: 002
Revises: 001
"""
from __future__ import annotations

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("citation_key", sa.String(128), nullable=False),
        sa.Column("title", sa.Text, nullable=False, server_default=""),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("chunk_text", sa.Text, nullable=False),
        sa.Column("metadata_json", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR,
            sa.Computed(
                "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(chunk_text, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "external_id",
            "chunk_index",
            name="uq_doc_chunks_user_provider_ext_idx",
        ),
    )

    op.create_index(
        "ix_doc_chunks_user_provider",
        "document_chunks",
        ["user_id", "provider"],
    )
    op.create_index(
        "ix_doc_chunks_tsv",
        "document_chunks",
        ["tsv"],
        postgresql_using="gin",
    )
    op.execute(
        "CREATE INDEX ix_doc_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_doc_chunks_embedding_hnsw")
    op.drop_index("ix_doc_chunks_tsv", table_name="document_chunks")
    op.drop_index("ix_doc_chunks_user_provider", table_name="document_chunks")
    op.drop_table("document_chunks")
