"""SSE streaming helpers for /query/stream endpoint."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sse(event: str, data: Any) -> str:
    """Format one SSE frame."""
    return f"event: {event}\r\ndata: {json.dumps(data)}\r\n\r\n"


def sse_step(node: str, status: str) -> str:
    return _sse("step", {"node": node, "status": status, "timestamp": _now()})


def sse_trace(run_id: str | None) -> str | None:
    """Return a trace SSE frame if LangSmith is configured, else None."""
    if os.getenv("LANGCHAIN_TRACING_V2", "").lower() != "true":
        return None
    if not run_id:
        return None
    project = os.getenv("LANGCHAIN_PROJECT", "default")
    url = f"https://smith.langchain.com/public/{run_id}/r"
    return _sse("trace", {"url": url})


def sse_answer(answer: str, evidence: list[dict[str, Any]] | None, thread_id: str | None) -> str:
    return _sse("answer", {"answer": answer, "evidence": evidence, "thread_id": thread_id})


def sse_error(message: str) -> str:
    return _sse("error", {"message": message})


def sse_done() -> str:
    return _sse("done", {})
