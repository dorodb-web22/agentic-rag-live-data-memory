"""Multi-tenant conversation persistence.

Exported for Dorothy's agent endpoint:
    from app.db.conversations import record_conversation_turn

Every query is strictly scoped to WHERE user_id = :user_id.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, ConversationTurn, _uuid


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _truncate(text: str, max_len: int = 120) -> str:
    return text[:max_len].strip() if text else "New conversation"


# ---------------------------------------------------------------------------
# Public read helpers
# ---------------------------------------------------------------------------


async def get_conversations(db: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    """List conversations for a user, most-recently-updated first."""
    result = await db.execute(
        select(
            Conversation.id,
            Conversation.thread_id,
            Conversation.title,
            Conversation.updated_at,
        )
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
    )
    return [
        {
            "id": row.id,
            "thread_id": row.thread_id,
            "title": row.title,
            "updated_at": row.updated_at.isoformat(),
        }
        for row in result.all()
    ]


async def get_conversation(
    db: AsyncSession, user_id: str, thread_id: str
) -> dict[str, Any] | None:
    """Return full conversation with turns, or None if not found / not owned."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.thread_id == thread_id)
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        return None

    turns_result = await db.execute(
        select(ConversationTurn)
        .where(ConversationTurn.conversation_id == conv.id)
        .order_by(ConversationTurn.created_at)
    )
    turns = turns_result.scalars().all()

    return {
        "thread_id": conv.thread_id,
        "title": conv.title,
        "messages": [
            {
                "id": t.id,
                "role": t.role,
                "content": t.content,
                "evidence": t.evidence,
                "trace_url": t.trace_url,
                "created_at": t.created_at.isoformat(),
            }
            for t in turns
        ],
    }


async def delete_conversation(
    db: AsyncSession, user_id: str, thread_id: str
) -> bool:
    """Delete a conversation and all its turns. Returns False if not found/owned."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.user_id == user_id, Conversation.thread_id == thread_id
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        return False
    await db.execute(
        delete(ConversationTurn).where(ConversationTurn.conversation_id == conv.id)
    )
    await db.delete(conv)
    return True


# ---------------------------------------------------------------------------
# Write helper (exported for Dorothy's agent endpoint)
# ---------------------------------------------------------------------------


async def record_conversation_turn(
    db: AsyncSession,
    *,
    user_id: str,
    thread_id: str,
    user_msg: str,
    assistant_msg: str,
    evidence: list[dict[str, Any]] | None = None,
    trace_url: str | None = None,
) -> None:
    """Upsert the conversation and append one user + one assistant turn.

    Designed to be called from Dorothy's /api/query endpoint after the agent
    returns its answer:

        from app.db.conversations import record_conversation_turn
        await record_conversation_turn(
            db,
            user_id=user["user_id"],
            thread_id=thread_id,
            user_msg=request.query,
            assistant_msg=answer,
            evidence=evidence,
            trace_url=trace_url,
        )
    """
    # Find or create conversation
    result = await db.execute(
        select(Conversation).where(
            Conversation.user_id == user_id, Conversation.thread_id == thread_id
        )
    )
    conv = result.scalar_one_or_none()

    if conv is None:
        conv = Conversation(
            id=_uuid(),
            user_id=user_id,
            thread_id=thread_id,
            title=_truncate(user_msg),
        )
        db.add(conv)
        await db.flush()  # populate conv.id before FK inserts below

    # Update title from first user message if still default
    if conv.title == "New conversation" and user_msg:
        conv.title = _truncate(user_msg)

    conv.updated_at = _now()

    now = _now()
    db.add(
        ConversationTurn(
            id=_uuid(),
            conversation_id=conv.id,
            role="user",
            content=user_msg,
            created_at=now,
        )
    )
    db.add(
        ConversationTurn(
            id=_uuid(),
            conversation_id=conv.id,
            role="assistant",
            content=assistant_msg,
            evidence=evidence,
            trace_url=trace_url,
            created_at=_now(),
        )
    )
