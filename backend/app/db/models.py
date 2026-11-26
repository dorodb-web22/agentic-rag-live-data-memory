"""SQLAlchemy ORM models for multi-tenant Agentic RAG SaaS.

Tables owned by Alok; never modified by Dorothy's agent/streaming code.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    picture: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    last_login_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    integrations: Mapped[list[UserIntegration]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_users_google_sub", "google_sub"),
        Index("ix_users_email", "email"),
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # thread_id is Dorothy's LangGraph thread key — unique per user
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="New conversation")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    user: Mapped[User] = relationship(back_populates="conversations")
    turns: Mapped[list[ConversationTurn]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationTurn.created_at",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "thread_id", name="uq_conversations_user_thread"),
        Index("ix_conversations_user_id", "user_id"),
        Index("ix_conversations_updated_at", "updated_at"),
        Index("ix_conversations_thread_id", "thread_id"),
    )


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    conversation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # evidence is Dorothy's list[dict] from the agent — stored as JSONB
    evidence: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    trace_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    conversation: Mapped[Conversation] = relationship(back_populates="turns")

    __table_args__ = (
        Index("ix_turns_conversation_id", "conversation_id"),
        Index("ix_turns_created_at", "created_at"),
    )


class UserIntegration(Base):
    """Per-user connector credentials. Sprint 2 populates encrypted_tokens."""

    __tablename__ = "user_integrations"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # provider: "github" | "gmail" | "notion" | "sqlite" | "google_sheets" | …
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    # AES-256-GCM / Fernet encrypted JSON blob — Sprint 2 crypto.py writes this
    encrypted_tokens: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provider-specific config (repos list, Notion root pages, SQLite filename, …)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # "connected" | "disconnected" | "needs_reauth" | "coming_soon"
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="disconnected")
    # Human-readable scope summary e.g. "dorodb-web22/repo (Read-only)"
    scope_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Token expiry for automatic refresh (Sprint 2)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="integrations")

    __table_args__ = (
        # Prevents duplicate providers per user; Sprint 2 upserts use ON CONFLICT
        UniqueConstraint("user_id", "provider", name="uq_integrations_user_provider"),
        Index("ix_integrations_user_id", "user_id"),
        Index("ix_integrations_provider", "provider"),
    )
