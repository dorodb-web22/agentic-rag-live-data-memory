"""Sprint 3 — Offline tests for Redis & fallback sliding-window rate limiter + daily token quota."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import time
from fastapi import FastAPI
from fastapi.testclient import TestClient
import jwt
import pytest

os.environ.setdefault("SESSION_SECRET", "x" * 32)
os.environ.setdefault("GOOGLE_CLIENT_ID", "test.apps.googleusercontent.com")

from app.auth.google import COOKIE_NAME  # noqa: E402
from app.middleware.rate_limit import (  # noqa: E402
    RateLimitMiddleware,
    record_token_usage,
    reset_in_memory_limits,
)


def _make_jwt(user_id: str, email: str) -> str:
    secret = os.environ["SESSION_SECRET"]
    return jwt.encode(
        {
            "user_id": user_id,
            "sub": f"sub-{user_id}",
            "email": email,
            "name": user_id,
            "picture": "",
            "exp": int(time.time()) + 3600,
        },
        secret,
        algorithm="HS256",
    )


def _build_mini_app() -> FastAPI:
    mini = FastAPI()
    mini.add_middleware(RateLimitMiddleware)

    @mini.post("/api/query")
    async def api_query(payload: dict) -> dict:
        return {"answer": f"echo:{payload.get('query', '')}"}

    @mini.get("/api/health")
    async def api_health() -> dict:
        return {"status": "ok"}

    return mini


def test_sliding_window_blocks_excess_requests_and_sets_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_in_memory_limits()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "3")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("DAILY_TOKEN_QUOTA", "100000")

    token_a = _make_jwt("user-alpha", "alpha@example.com")
    token_b = _make_jwt("user-beta", "beta@example.com")

    app = _build_mini_app()
    with TestClient(app) as client:
        for i in range(3):
            r = client.post(
                "/api/query",
                json={"query": f"hi {i}"},
                cookies={COOKIE_NAME: token_a},
            )
            assert r.status_code == 200
            assert r.headers["X-RateLimit-Limit"] == "3"

        # 4th request for user-alpha -> 429 with Retry-After
        blocked = client.post(
            "/api/query",
            json={"query": "overflow"},
            cookies={COOKIE_NAME: token_a},
        )
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 1
        assert blocked.headers["X-RateLimit-Remaining"] == "0"

        # Tenant isolation: user-beta has an independent bucket -> still 200 OK
        other_user = client.post(
            "/api/query",
            json={"query": "hello from beta"},
            cookies={COOKIE_NAME: token_b},
        )
        assert other_user.status_code == 200

        # Non-rate-limited health check remains unrestricted even for user-alpha
        health = client.get("/api/health", cookies={COOKIE_NAME: token_a})
        assert health.status_code == 200

    reset_in_memory_limits()


@pytest.mark.asyncio
async def test_daily_token_quota_enforced_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_in_memory_limits()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "50")
    monkeypatch.setenv("DAILY_TOKEN_QUOTA", "100")

    token = _make_jwt("quota-user", "quota@example.com")

    await record_token_usage("quota-user", 98)

    app = _build_mini_app()
    with TestClient(app) as client:
        # Payload > 8 bytes -> estimated >= 3 tokens -> exceeds 100 daily budget
        resp = client.post(
            "/api/query",
            json={"query": "Please summarize all my Notion documents from this quarter"},
            cookies={COOKIE_NAME: token},
        )
        assert resp.status_code == 429
        assert "Daily token quota" in resp.json()["detail"]
        assert int(resp.headers["Retry-After"]) >= 1

    reset_in_memory_limits()


def test_redis_pipeline_path_and_graceful_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_in_memory_limits()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "2")
    monkeypatch.setenv("DAILY_TOKEN_QUOTA", "50000")

    # Mock async Redis pipeline reporting count == 2 (already at limit)
    read_pipe = MagicMock()
    read_pipe.zremrangebyscore = MagicMock(return_value=read_pipe)
    read_pipe.zcard = MagicMock(return_value=read_pipe)
    read_pipe.zrange = MagicMock(return_value=read_pipe)
    import time as _time

    read_pipe.execute = AsyncMock(return_value=[0, 2, [("m1", _time.time() - 10)]])

    fake_redis = MagicMock()
    fake_redis.pipeline = MagicMock(return_value=read_pipe)
    fake_redis.get = AsyncMock(return_value="0")

    app = _build_mini_app()
    with patch("app.middleware.rate_limit._get_redis_client", AsyncMock(return_value=fake_redis)):
        with TestClient(app) as client:
            resp = client.post("/api/query", json={"query": "test redis"})
            assert resp.status_code == 429
            assert int(resp.headers["Retry-After"]) >= 1

    # Now simulate Redis outage -> middleware must degrade to memory, never 500
    broken_redis = MagicMock()
    broken_pipe = MagicMock()
    broken_pipe.execute = AsyncMock(side_effect=ConnectionError("redis down"))
    broken_redis.pipeline = MagicMock(return_value=broken_pipe)
    broken_redis.get = AsyncMock(side_effect=ConnectionError("redis down"))

    with patch("app.middleware.rate_limit._get_redis_client", AsyncMock(return_value=broken_redis)):
        with TestClient(app) as client:
            ok_resp = client.post("/api/query", json={"query": "survives outage"})
            assert ok_resp.status_code == 200

    reset_in_memory_limits()
