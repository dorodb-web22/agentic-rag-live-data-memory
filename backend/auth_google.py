"""Google sign-in for the landing page.

Flow: the browser gets a Google ID token -> POSTs it to /auth/google -> we VERIFY it
with Google's public keys -> we set our own signed session cookie. The browser's
localStorage copy of the profile is only for showing the avatar; the cookie is the
real proof of login.

Env vars: GOOGLE_CLIENT_ID, SESSION_SECRET (long random string), COOKIE_SECURE=1 in production (HTTPS).
In backend/main.py:
    from auth_google import router as auth_router
    app.include_router(auth_router)
and CORS must allow the landing origin with credentials, e.g.
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5500"],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
Protect any route with:  user: dict = Depends(current_user)
"""
import os
import time

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE = "session"
MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def _client_id() -> str:
    cid = os.environ.get("GOOGLE_CLIENT_ID")
    if not cid:
        raise HTTPException(500, "GOOGLE_CLIENT_ID is not set")
    return cid


def _secret() -> str:
    sec = os.environ.get("SESSION_SECRET")
    if not sec or len(sec) < 32:
        raise HTTPException(500, "SESSION_SECRET must be set (32+ characters)")
    return sec


class GoogleToken(BaseModel):
    credential: str


@router.post("/google")
def google_login(body: GoogleToken, response: Response):
    try:
        # checks signature, expiry, issuer and that the token was issued for OUR client id
        info = id_token.verify_oauth2_token(body.credential, g_requests.Request(), _client_id())
    except ValueError:
        raise HTTPException(401, "Invalid Google token")
    if not info.get("email_verified"):
        raise HTTPException(401, "Google email is not verified")
    profile = {"sub": info["sub"], "email": info["email"],
               "name": info.get("name", ""), "picture": info.get("picture", "")}
    session = jwt.encode({**profile, "exp": int(time.time()) + MAX_AGE}, _secret(), algorithm="HS256")
    response.set_cookie(COOKIE, session, max_age=MAX_AGE, httponly=True, samesite="lax",
                        secure=os.environ.get("COOKIE_SECURE") == "1")
    return {k: profile[k] for k in ("name", "email", "picture")}


def current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Not signed in")
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired")


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return {k: user[k] for k in ("name", "email", "picture")}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}
