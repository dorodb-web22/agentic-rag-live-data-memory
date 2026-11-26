"""Conversation routes — /api/conversations/*

All endpoints require a valid session cookie and are strictly scoped to
the authenticated user. Non-existent or non-owned threads return 404
(never 403) to avoid leaking existence.

GET    /api/conversations                  — list all conversations
GET    /api/conversations/{thread_id}      — conversation detail + messages
DELETE /api/conversations/{thread_id}      — delete conversation + turns
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google import current_user
from app.db.conversations import delete_conversation, get_conversation, get_conversations
from app.db.session import get_db
from app.schemas import THREAD_ID_PATTERN

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    user: dict = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List the authenticated user's conversations, newest first."""
    convs = await get_conversations(db, user["user_id"])
    return {"conversations": convs}


@router.get("/{thread_id}")
async def get_conversation_detail(
    thread_id: str = Path(..., pattern=THREAD_ID_PATTERN),
    user: dict = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return a conversation and its full message history.

    Returns 404 if the thread does not exist or belongs to another user.
    """
    conv = await get_conversation(db, user["user_id"], thread_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    return conv


@router.delete("/{thread_id}")
async def delete_conversation_route(
    thread_id: str = Path(..., pattern=THREAD_ID_PATTERN),
    user: dict = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a conversation and all its turns.

    Returns 404 if the thread does not exist or belongs to another user.
    """
    deleted = await delete_conversation(db, user["user_id"], thread_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    return {"ok": True}
