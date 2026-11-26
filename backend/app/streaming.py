"""SSE streaming helpers for /query/stream endpoint."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sse(event: str, data: Any) -> str:
    """Format one SSE frame."""
    return f"event: {event}\r\ndata: {json.dumps(data)}\r\n\r\n"


def sse_step(node: str, status: str) -> str:
    return _sse("step", {"node": node, "status": status, "timestamp": _now()})


def sse_trace(run_id: str | None) -> str | None:
    """Return a trace SSE frame if LangSmith is configured and run exists, else None."""
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
        return _sse("trace", {"url": str(url)})
    except Exception:
        return None


def sse_answer(answer: str, evidence: list[dict[str, Any]] | None, thread_id: str | None) -> str:
    return _sse("answer", {"answer": answer or "", "evidence": evidence, "thread_id": thread_id})


def sse_error(message: str) -> str:
    return _sse("error", {"message": message})


def sse_done() -> str:
    return _sse("done", {})
