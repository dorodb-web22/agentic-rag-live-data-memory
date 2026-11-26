import os
os.environ["GOOGLE_CLIENT_ID"] = "test-client.apps.googleusercontent.com"
os.environ["SESSION_SECRET"] = "x" * 40
from fastapi import FastAPI
from fastapi.testclient import TestClient
import auth_google

app = FastAPI(); app.include_router(auth_google.router)
c = TestClient(app)
GOOD = {"sub": "1", "email": "a@b.com", "email_verified": True, "name": "Test User", "picture": "http://p"}

def test_bad_token_rejected(monkeypatch):
    def boom(*a, **k): raise ValueError("bad")
    monkeypatch.setattr(auth_google.id_token, "verify_oauth2_token", boom)
    assert c.post("/auth/google", json={"credential": "junk"}).status_code == 401

def test_unverified_email_rejected(monkeypatch):
    monkeypatch.setattr(auth_google.id_token, "verify_oauth2_token", lambda *a, **k: {**GOOD, "email_verified": False})
    assert c.post("/auth/google", json={"credential": "t"}).status_code == 401

def test_login_me_logout(monkeypatch):
    monkeypatch.setattr(auth_google.id_token, "verify_oauth2_token", lambda *a, **k: GOOD)
    assert c.get("/auth/me").status_code == 401
    r = c.post("/auth/google", json={"credential": "t"})
    assert r.status_code == 200 and r.json()["email"] == "a@b.com"
    assert "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/auth/me").json()["name"] == "Test User"
    c.post("/auth/logout")
    assert c.get("/auth/me").status_code == 401

def test_tampered_cookie_rejected():
    c.cookies.set("session", "not.a.jwt")
    assert c.get("/auth/me").status_code == 401
