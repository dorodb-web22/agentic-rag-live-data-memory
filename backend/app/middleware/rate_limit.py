"""Pure-ASGI Redis sliding-window rate limiter & daily token quota middleware.

Implemented as a native ASGI middleware (not BaseHTTPMiddleware) so SSE streaming
(`/api/query/stream`), client-disconnect detection, and multipart SQLite uploads
are never buffered or wrapped.

Guardrails enforced on expensive query/upload routes:
1. Sliding-window request limit (`RATE_LIMIT_REQUESTS_PER_MINUTE`, default 20 / 60s)
2. Per-user daily token budget (`DAILY_TOKEN_QUOTA`, default 100,000 tokens / UTC day)

Returns HTTP 429 Too Many Requests with `Retry-After`, `X-RateLimit-Limit`,
and `X-RateLimit-Remaining` headers when exceeded.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
import logging
import math
import os
import time
from typing import Any
import uuid

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.google import COOKIE_NAME, _decode_session_jwt

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_SECONDS = 60
DEFAULT_REQUESTS_PER_WINDOW = 20
DEFAULT_DAILY_TOKEN_QUOTA = 100_000
MAX_IN_MEMORY_KEYS = 4096

RATE_LIMITED_PATHS: frozenset[str] = frozenset(
    {
        "/api/query",
        "/api/query/stream",
        "/query",
        "/query/stream",
        "/api/integrations/sqlite/upload",
    }
)

_REDIS_CLIENT: Any = None
_REDIS_CLIENT_URL: str | None = None
_MEM_WINDOWS: dict[str, deque[float]] = {}
_MEM_DAILY_TOKENS: dict[str, int] = {}


def reset_in_memory_limits() -> None:
    """Clear in-memory rate-limit and token-quota state (used in tests)."""
    global _REDIS_CLIENT, _REDIS_CLIENT_URL
    _MEM_WINDOWS.clear()
    _MEM_DAILY_TOKENS.clear()
    _REDIS_CLIENT = None
    _REDIS_CLIENT_URL = None


def _is_rate_limit_enabled() -> bool:
    explicit = os.getenv("RATE_LIMIT_ENABLED")
    if explicit is not None and explicit.strip() != "":
        return explicit.strip().lower() in {"1", "true", "yes", "on"}
    return bool(os.getenv("REDIS_URL", "").strip())


def _get_window_config() -> tuple[int, int, int]:
    try:
        max_reqs = max(
            1, int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", str(DEFAULT_REQUESTS_PER_WINDOW)))
        )
    except ValueError:
        max_reqs = DEFAULT_REQUESTS_PER_WINDOW
    try:
        window_sec = max(
            1, int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", str(DEFAULT_WINDOW_SECONDS)))
        )
    except ValueError:
        window_sec = DEFAULT_WINDOW_SECONDS
    try:
        daily_quota = max(
            0, int(os.getenv("DAILY_TOKEN_QUOTA", str(DEFAULT_DAILY_TOKEN_QUOTA)))
        )
    except ValueError:
        daily_quota = DEFAULT_DAILY_TOKEN_QUOTA
    return max_reqs, window_sec, daily_quota


def _seconds_until_utc_midnight(now_dt: datetime | None = None) -> int:
    current = now_dt or datetime.now(timezone.utc)
    tomorrow = (current + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int(math.ceil((tomorrow - current).total_seconds())))


def _resolve_subject_key(request: Request) -> str:
    """Prefer authenticated `user_id` from verified session JWT; fall back to client IP."""
    token = request.cookies.get(COOKIE_NAME)
    if token:
        try:
            payload = _decode_session_jwt(token)
            if payload and payload.get("user_id"):
                return f"user:{payload['user_id']}"
        except HTTPException:
            pass

    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        first_ip = forwarded.split(",")[0].strip()
        if first_ip:
            return f"ip:{first_ip}"

    client_host = request.client.host if request.client else "unknown"
    return f"ip:{client_host}"


def _estimate_request_tokens_from_headers(request: Request) -> int:
    """Estimate prompt tokens from Content-Length without consuming ASGI receive stream."""
    content_type = request.headers.get("content-type", "").lower()
    if "multipart/form-data" in content_type:
        return 0
    try:
        content_length = int(request.headers.get("content-length", "0"))
    except ValueError:
        content_length = 0
    if content_length <= 0:
        return 1
    return max(1, min(32_000, content_length // 4))


async def _get_redis_client() -> Any | None:
    global _REDIS_CLIENT, _REDIS_CLIENT_URL
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return None
    if _REDIS_CLIENT is not None and _REDIS_CLIENT_URL == redis_url:
        return _REDIS_CLIENT

    try:
        import redis.asyncio as aioredis

        _REDIS_CLIENT = aioredis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        _REDIS_CLIENT_URL = redis_url
        return _REDIS_CLIENT
    except Exception as exc:
        logger.warning(
            "Failed to initialize Redis client (%s); using in-memory fallback",
            type(exc).__name__,
        )
        return None


async def _check_sliding_window_redis(
    redis_client: Any,
    subject: str,
    max_requests: int,
    window_seconds: int,
    now: float,
) -> tuple[bool, int, int]:
    key = f"rl:sw:{subject}"
    window_start = now - window_seconds
    member = f"{now:.6f}:{uuid.uuid4().hex[:8]}"

    pipe = redis_client.pipeline(transaction=True)
    pipe.zremrangebyscore(key, "-inf", window_start)
    pipe.zcard(key)
    pipe.zrange(key, 0, 0, withscores=True)
    _, current_count, oldest_entries = await pipe.execute()

    count = int(current_count or 0)
    if count >= max_requests:
        oldest_ts = float(oldest_entries[0][1]) if oldest_entries else now
        retry_after = max(1, int(math.ceil((oldest_ts + window_seconds) - now)))
        return False, 0, retry_after

    write_pipe = redis_client.pipeline(transaction=True)
    write_pipe.zadd(key, {member: now})
    write_pipe.expire(key, window_seconds + 5)
    await write_pipe.execute()

    remaining = max(0, max_requests - (count + 1))
    return True, remaining, 0


def _check_sliding_window_memory(
    subject: str,
    max_requests: int,
    window_seconds: int,
    now: float,
) -> tuple[bool, int, int]:
    if len(_MEM_WINDOWS) >= MAX_IN_MEMORY_KEYS and subject not in _MEM_WINDOWS:
        _MEM_WINDOWS.pop(next(iter(_MEM_WINDOWS)), None)

    bucket = _MEM_WINDOWS.setdefault(subject, deque())
    cutoff = now - window_seconds
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()

    if len(bucket) >= max_requests:
        retry_after = max(1, int(math.ceil((bucket[0] + window_seconds) - now)))
        return False, 0, retry_after

    bucket.append(now)
    remaining = max(0, max_requests - len(bucket))
    return True, remaining, 0


async def _check_and_reserve_daily_tokens(
    redis_client: Any | None,
    subject: str,
    estimated_tokens: int,
    daily_quota: int,
) -> tuple[bool, int, int]:
    if daily_quota <= 0 or estimated_tokens <= 0:
        return True, max(0, daily_quota), 0

    now_dt = datetime.now(timezone.utc)
    day_str = now_dt.strftime("%Y-%m-%d")
    ttl = _seconds_until_utc_midnight(now_dt)
    quota_key = f"rl:tokens:{subject}:{day_str}"

    if redis_client is not None:
        try:
            current_raw = await redis_client.get(quota_key)
            current_used = int(current_raw) if current_raw is not None else 0
            if current_used + estimated_tokens > daily_quota:
                return False, max(0, daily_quota - current_used), ttl
            pipe = redis_client.pipeline(transaction=True)
            pipe.incrby(quota_key, estimated_tokens)
            pipe.expire(quota_key, ttl + 60)
            res = await pipe.execute()
            new_used = int(res[0])
            return True, max(0, daily_quota - new_used), 0
        except Exception as exc:
            logger.warning(
                "Redis token quota check failed (%s); falling back to memory",
                type(exc).__name__,
            )

    if len(_MEM_DAILY_TOKENS) >= MAX_IN_MEMORY_KEYS and quota_key not in _MEM_DAILY_TOKENS:
        _MEM_DAILY_TOKENS.pop(next(iter(_MEM_DAILY_TOKENS)), None)

    used = _MEM_DAILY_TOKENS.get(quota_key, 0)
    if used + estimated_tokens > daily_quota:
        return False, max(0, daily_quota - used), ttl
    _MEM_DAILY_TOKENS[quota_key] = used + estimated_tokens
    return True, max(0, daily_quota - _MEM_DAILY_TOKENS[quota_key]), 0


async def record_token_usage(user_id: str, tokens: int) -> None:
    """Record additional post-completion LLM token usage for *user_id*."""
    if not user_id or tokens <= 0 or not _is_rate_limit_enabled():
        return
    subject = f"user:{user_id}"
    now_dt = datetime.now(timezone.utc)
    day_str = now_dt.strftime("%Y-%m-%d")
    ttl = _seconds_until_utc_midnight(now_dt)
    quota_key = f"rl:tokens:{subject}:{day_str}"

    redis_client = await _get_redis_client()
    if redis_client is not None:
        try:
            pipe = redis_client.pipeline(transaction=True)
            pipe.incrby(quota_key, int(tokens))
            pipe.expire(quota_key, ttl + 60)
            await pipe.execute()
            return
        except Exception as exc:
            logger.warning(
                "Redis record_token_usage failed (%s); updating memory counter",
                type(exc).__name__,
            )

    _MEM_DAILY_TOKENS[quota_key] = _MEM_DAILY_TOKENS.get(quota_key, 0) + int(tokens)


class RateLimitMiddleware:
    """Pure-ASGI per-user sliding-window rate limiter + daily token quota."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        if method == "OPTIONS" or path not in RATE_LIMITED_PATHS or not _is_rate_limit_enabled():
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        max_requests, window_seconds, daily_quota = _get_window_config()
        subject = _resolve_subject_key(request)
        now = time.time()

        redis_client = await _get_redis_client()
        if redis_client is not None:
            try:
                allowed, remaining, retry_after = await _check_sliding_window_redis(
                    redis_client,
                    subject=subject,
                    max_requests=max_requests,
                    window_seconds=window_seconds,
                    now=now,
                )
            except Exception as exc:
                logger.warning(
                    "Redis sliding-window check failed (%s); falling back to memory",
                    type(exc).__name__,
                )
                allowed, remaining, retry_after = _check_sliding_window_memory(
                    subject=subject,
                    max_requests=max_requests,
                    window_seconds=window_seconds,
                    now=now,
                )
        else:
            allowed, remaining, retry_after = _check_sliding_window_memory(
                subject=subject,
                max_requests=max_requests,
                window_seconds=window_seconds,
                now=now,
            )

        if not allowed:
            resp = JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Rate limit exceeded ({max_requests} requests per {window_seconds}s). "
                        f"Please retry in {retry_after}s."
                    ),
                    "retry_after": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": "0",
                },
            )
            await resp(scope, receive, send)
            return

        estimated_tokens = _estimate_request_tokens_from_headers(request)
        quota_ok, tokens_remaining, quota_retry = await _check_and_reserve_daily_tokens(
            redis_client,
            subject=subject,
            estimated_tokens=estimated_tokens,
            daily_quota=daily_quota,
        )
        if not quota_ok:
            resp = JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Daily token quota ({daily_quota} tokens/day) exceeded. "
                        "Quota resets at 00:00 UTC."
                    ),
                    "retry_after": quota_retry,
                },
                headers={
                    "Retry-After": str(quota_retry),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": str(remaining),
                    "X-Daily-Token-Remaining": str(tokens_remaining),
                },
            )
            await resp(scope, receive, send)
            return

        extra_headers: list[tuple[bytes, bytes]] = [
            (b"x-ratelimit-limit", str(max_requests).encode("latin-1")),
            (b"x-ratelimit-remaining", str(remaining).encode("latin-1")),
        ]
        if daily_quota > 0:
            extra_headers.append(
                (b"x-daily-token-remaining", str(tokens_remaining).encode("latin-1"))
            )

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(extra_headers)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
