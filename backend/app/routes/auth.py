"""Auth routes — /api/auth/*

POST /api/auth/google   — verify Google ID token, upsert user, set session cookie
GET  /api/auth/me       — return current user profile
POST /api/auth/logout   — clear session cookie
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google import current_user, google_sign_in
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class GoogleTokenBody(BaseModel):
    credential: str


@router.post("/google")
async def post_google_auth(
    body: GoogleTokenBody,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify Google ID token → upsert user → set httpOnly session cookie."""
    return await google_sign_in(body.credential, response, db)


@router.get("/me")
async def get_me(user: dict = Depends(current_user)) -> dict:
    """Return the signed-in user's profile from the session JWT."""
    return {
        "id": user["user_id"],
        "name": user["name"],
        "email": user["email"],
        "picture": user["picture"],
    }


@router.post("/logout")
async def post_logout(response: Response) -> dict:
    """Clear the session cookie."""
    response.delete_cookie("session", path="/")
    return {"ok": True}
