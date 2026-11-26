"""Sprint 1 — Create multi-tenant core tables.

Tables: users, conversations, conversation_turns, user_integrations

Revision: 001
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("google_sub", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("picture", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)
    op.create_index("ix_users_email", "users", ["email"])

    # ------------------------------------------------------------------
    # conversations
    # ------------------------------------------------------------------
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column(
            "title", sa.String(500), nullable=False, server_default="New conversation"
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
        sa.UniqueConstraint("user_id", "thread_id", name="uq_conversations_user_thread"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index(
        "ix_conversations_updated_at", "conversations", ["updated_at"]
    )
    op.create_index("ix_conversations_thread_id", "conversations", ["thread_id"])

    # ------------------------------------------------------------------
    # conversation_turns
    # ------------------------------------------------------------------
    op.create_table(
        "conversation_turns",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("evidence", postgresql.JSONB, nullable=True),
        sa.Column("trace_url", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_turns_conversation_id", "conversation_turns", ["conversation_id"]
    )
    op.create_index("ix_turns_created_at", "conversation_turns", ["created_at"])

    # ------------------------------------------------------------------
    # user_integrations  (ready for Sprint 2 OAuth connectors)
    # ------------------------------------------------------------------
    op.create_table(
        "user_integrations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        # AES-256-GCM / Fernet encrypted token blob — written by Sprint 2 crypto.py
        sa.Column("encrypted_tokens", sa.Text, nullable=True),
        sa.Column("config", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="disconnected",
        ),
        sa.Column("scope_summary", sa.Text, nullable=True),
        # expires_at enables automatic token refresh in Sprint 2
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "user_id", "provider", name="uq_integrations_user_provider"
        ),
    )
    op.create_index("ix_integrations_user_id", "user_integrations", ["user_id"])
    op.create_index("ix_integrations_provider", "user_integrations", ["provider"])


def downgrade() -> None:
    op.drop_table("user_integrations")
    op.drop_table("conversation_turns")
    op.drop_table("conversations")
    op.drop_table("users")
