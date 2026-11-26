"""CSRF Origin verification middleware.

Rejects state-mutating requests (POST, PUT, PATCH, DELETE) whose Origin
header does not match the server's own host.  Read-only methods (GET, HEAD,
OPTIONS) are always allowed.

Allowed origins are derived (in order) from:
  1. CSRF_TRUSTED_ORIGINS env var  — comma-separated list of full origins
     e.g. "https://app.example.com,https://www.example.com"
  2. CORS_ORIGINS env var          — reuses the existing CORS allowlist
  3. The request's own Host header — same-origin / same-site requests

Requests without an Origin header (direct curl, server-to-server) are
allowed by default because browsers always set Origin for cross-origin XHR.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _trusted_origins() -> set[str]:
    origins: set[str] = set()
    for env_var in ("CSRF_TRUSTED_ORIGINS", "CORS_ORIGINS"):
        raw = os.getenv(env_var, "")
        for o in raw.split(","):
            o = o.strip().rstrip("/")
            if o:
                origins.add(o)
    return origins


class CSRFOriginMiddleware(BaseHTTPMiddleware):
    """Reject cross-origin mutating requests whose Origin is not trusted."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._static_trusted = _trusted_origins()

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in _SAFE_METHODS:
            return await call_next(request)

        origin = request.headers.get("origin")
        if not origin:
            # No Origin header → not a browser cross-origin request → allow
            return await call_next(request)

        # Build dynamic trusted set: static list + Host-derived same-origin
        trusted = set(self._static_trusted)
        host = request.headers.get("host", "")
        if host:
            scheme = "https" if request.url.scheme == "https" else "http"
            trusted.add(f"{scheme}://{host}")

        # Normalise the incoming origin (strip trailing slash)
        parsed = urlparse(origin)
        normalised = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

        if normalised not in trusted:
            logger.warning(
                "CSRF: blocked %s %s from origin %s (trusted: %s)",
                request.method,
                request.url.path,
                origin,
                trusted,
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF check failed: origin not allowed."},
            )

        return await call_next(request)
