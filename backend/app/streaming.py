"""SSE streaming helpers for /query/stream and /api/query/stream endpoints."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from typing import Any

KEEPALIVE_INTERVAL_SECONDS = 15.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sse(event: str, data: Any) -> str:
    """Format one SSE frame."""
    return f"event: {event}\r\ndata: {json.dumps(data)}\r\n\r\n"


def sse_keepalive() -> str:
    """Return an SSE comment heartbeat frame (': keepalive\\n\\n')."""
    return ": keepalive\n\n"


def sse_step(node: str, status: str) -> str:
    return _sse("step", {"node": node, "status": status, "timestamp": _now()})


def resolve_trace_url(run_id: str | None) -> str | None:
    """Return the LangSmith run URL if LangSmith tracing is configured and run exists."""
    if os.getenv("LANGCHAIN_TRACING_V2", "").lower() != "true":
        return None
    api_key = os.getenv("LANGCHAIN_API_KEY", "").strip()
    if not api_key:
        return None
    if not run_id or not run_id.strip():
        return None

    try:
        import langsmith

        timeout_ms = int(os.getenv("LANGSMITH_TIMEOUT_MS", "3000"))
        client = langsmith.Client(api_key=api_key, timeout_ms=timeout_ms)
        run = client.read_run(run_id.strip())
        url = getattr(run, "url", None)
        if not url:
            return None
        return str(url)
    except Exception:
        return None


async def aresolve_trace_url(run_id: str | None) -> str | None:
    """Non-blocking async wrapper around resolve_trace_url."""
    if os.getenv("LANGCHAIN_TRACING_V2", "").lower() != "true":
        return None
    if not os.getenv("LANGCHAIN_API_KEY", "").strip():
        return None
    if not run_id or not run_id.strip():
        return None
    return await asyncio.to_thread(resolve_trace_url, run_id)


def sse_trace(run_id: str | None) -> str | None:
    """Return a trace SSE frame if LangSmith is configured and run exists, else None."""
    url = resolve_trace_url(run_id)
    if not url:
        return None
    return _sse("trace", {"url": url})


def sse_trace_from_url(trace_url: str | None) -> str | None:
    """Format an already-resolved LangSmith trace URL as an SSE trace frame."""
    if not trace_url:
        return None
    return _sse("trace", {"url": trace_url})


def sse_answer(answer: str, evidence: list[dict[str, Any]] | None, thread_id: str | None) -> str:
    return _sse("answer", {"answer": answer or "", "evidence": evidence, "thread_id": thread_id})


def sse_error(message: str) -> str:
    return _sse("error", {"message": message})


def sse_done() -> str:
    return _sse("done", {})
