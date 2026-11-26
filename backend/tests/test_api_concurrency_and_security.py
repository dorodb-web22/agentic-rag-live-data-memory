import threading
import time
from typing import Any

from fastapi import status
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
import pytest

from app.agent import BasicAgent
from app.main import app, get_agent


class DelayGraph:
    """Stub graph that simulates variable execution latency."""

    def invoke(self, payload: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        tid = (config or {}).get("configurable", {}).get("thread_id")
        if tid == "slow":
            time.sleep(0.4)
        return {"answer": f"answer for {tid}", "evidence": None}


def test_concurrent_requests_isolate_thread_ids() -> None:
    """Verify Issue #19: Overlapping requests on shared BasicAgent must not swap thread_ids."""
    agent = BasicAgent(graph=DelayGraph(), checkpointer=InMemorySaver())
    app.dependency_overrides[get_agent] = lambda: agent
    client = TestClient(app)
    results: dict[str, dict[str, Any]] = {}

    def worker(tid: str) -> None:
        resp = client.post("/query", json={"query": "test query", "thread_id": tid})
        results[tid] = resp.json()

    t_slow = threading.Thread(target=worker, args=("slow",))
    t_fast = threading.Thread(target=worker, args=("fast",))

    t_slow.start()
    time.sleep(0.1)  # Ensure slow starts first
    t_fast.start()

    t_fast.join()
    t_slow.join()

    app.dependency_overrides.clear()

    assert results["slow"]["thread_id"] == "slow"
    assert results["fast"]["thread_id"] == "fast"
    assert results["slow"]["answer"] == "answer for slow"
    assert results["fast"]["answer"] == "answer for fast"


def test_thread_id_validation_rejects_path_traversal_and_invalid_chars() -> None:
    """Verify Issue #23: Malformed thread_id returns 422 Unprocessable Entity."""
    client = TestClient(app)

    # 1. /query with path traversal payload
    resp = client.post("/query", json={"query": "hello", "thread_id": "../../etc/passwd"})
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # 2. /query with excessive length (>64 chars)
    resp = client.post("/query", json={"query": "hello", "thread_id": "a" * 65})
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # 3. /threads/{id} with invalid characters
    resp = client.get("/threads/invalid..traversal/path")
    assert resp.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_ENTITY)

    resp2 = client.get("/threads/" + ("b" * 65))
    assert resp2.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_stream_error_sanitization() -> None:
    """Verify Issue #24: Stream execution errors do not leak raw exception text."""

    class ErrorGraph:
        def stream(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("SecretInternalDatabaseToken12345")

    agent = BasicAgent(graph=ErrorGraph(), checkpointer=InMemorySaver())
    app.dependency_overrides[get_agent] = lambda: agent
    client = TestClient(app)

    resp = client.post("/query/stream", json={"query": "fail me"})
    assert resp.status_code == 200
    text = resp.text

    # Must NOT contain the raw secret or raw exception detail
    assert "SecretInternalDatabaseToken12345" not in text
    assert "LLM request failed (RuntimeError)" in text
    assert "event: error" in text
    assert "event: done" in text

    app.dependency_overrides.clear()


def test_deep_health_check_returns_component_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Verify Issue #24: /health/deep reports database and provider readiness."""
    from app.db_setup import init_demo_database

    init_demo_database()
    client = TestClient(app)
    resp = client.get("/health/deep")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "ok" in data["components"]["database"]
    assert "llm_provider" in data["components"]
    assert "checkpointer" in data["components"]

    # When database is missing, health check must report 503 degraded
    fake_missing_db = tmp_path / "nonexistent.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(fake_missing_db))
    resp_down = client.get("/health/deep")
    assert resp_down.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert resp_down.json()["detail"]["status"] == "degraded"
