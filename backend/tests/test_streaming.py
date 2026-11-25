from __future__ import annotations

from collections.abc import Iterator
import json
from typing import Any
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
import pytest

from app.agent import BasicAgent, create_agent_graph, get_agent
from app.main import app
from app.streaming import (
    _now,
    sse_answer,
    sse_done,
    sse_error,
    sse_step,
    sse_trace,
)

client = TestClient(app)


def _parse_sse_events(raw_text: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse raw SSE stream text into a list of (event_type, parsed_json_dict) pairs."""
    events: list[tuple[str, dict[str, Any]]] = []
    # Normalize CRLF and split on double newlines separating SSE frames
    blocks = [b.strip() for b in raw_text.replace("\r\n", "\n").split("\n\n") if b.strip()]
    for block in blocks:
        lines = block.split("\n")
        event_name: str | None = None
        data_dict: dict[str, Any] = {}
        for line in lines:
            if line.startswith("event: "):
                event_name = line[len("event: ") :].strip()
            elif line.startswith("data: "):
                raw_data = line[len("data: ") :].strip()
                data_dict = json.loads(raw_data) if raw_data else {}
        if event_name is not None:
            events.append((event_name, data_dict))
    return events


# ---------------------------------------------------------------------------
# Unit tests for streaming helpers
# ---------------------------------------------------------------------------

def test_sse_step_format() -> None:
    frame = sse_step("planner", "start")
    assert frame.startswith("event: step\r\n")
    assert "\r\ndata: " in frame
    assert frame.endswith("\r\n\r\n")

    events = _parse_sse_events(frame)
    assert len(events) == 1
    event_type, data = events[0]
    assert event_type == "step"
    assert data["node"] == "planner"
    assert data["status"] == "start"
    assert "timestamp" in data


def test_sse_answer_format() -> None:
    frame = sse_answer("Enterprise is $5000.", [{"id": 3, "name": "Enterprise"}], "thread-123")
    assert frame.startswith("event: answer\r\n")
    events = _parse_sse_events(frame)
    assert len(events) == 1
    event_type, data = events[0]
    assert event_type == "answer"
    assert data["answer"] == "Enterprise is $5000."
    assert data["evidence"] == [{"id": 3, "name": "Enterprise"}]
    assert data["thread_id"] == "thread-123"


def test_sse_error_format() -> None:
    frame = sse_error("Database connection lost.")
    assert frame.startswith("event: error\r\n")
    events = _parse_sse_events(frame)
    assert len(events) == 1
    event_type, data = events[0]
    assert event_type == "error"
    assert data["message"] == "Database connection lost."


def test_sse_done_format() -> None:
    frame = sse_done()
    assert frame.startswith("event: done\r\n")
    events = _parse_sse_events(frame)
    assert len(events) == 1
    event_type, data = events[0]
    assert event_type == "done"
    assert data == {}


def test_sse_trace_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    assert sse_trace("some-run-id") is None

    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    assert sse_trace("some-run-id") is None


def test_sse_trace_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_PROJECT", "agentic-rag-test")

    assert sse_trace(None) is None

    frame = sse_trace("test-run-uuid-123")
    assert frame is not None
    assert frame.startswith("event: trace\r\n")
    events = _parse_sse_events(frame)
    assert len(events) == 1
    event_type, data = events[0]
    assert event_type == "trace"
    assert data["url"] == "https://smith.langchain.com/public/test-run-uuid-123/r"


# ---------------------------------------------------------------------------
# Endpoint tests for POST /query/stream
# ---------------------------------------------------------------------------

class StubStreamingAgent:
    """Stub agent for controlling stream_with_evidence yield behavior."""

    def __init__(self, should_raise: bool = False, run_id: str | None = None) -> None:
        self.should_raise = should_raise
        self.last_run_id = run_id
        self.checkpointer = None

    def stream_with_evidence(
        self,
        query: str,
        thread_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        if self.should_raise:
            raise RuntimeError("Simulation failure in agent stream")

        yield {"event": "step", "data": {"node": "planner", "status": "end"}}
        yield {"event": "step", "data": {"node": "worker", "status": "end"}}
        yield {
            "event": "answer",
            "data": {
                "answer": f"Mock answer for: {query}",
                "evidence": [{"id": 1, "name": "Starter"}],
                "thread_id": thread_id,
            },
        }
        yield {"event": "done", "data": {}}


def test_stream_endpoint_returns_event_stream_content_type() -> None:
    stub = StubStreamingAgent()
    app.dependency_overrides[get_agent] = lambda: stub
    try:
        response = client.post("/query/stream", json={"query": "What is Starter?"})
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
    finally:
        app.dependency_overrides.clear()


def test_stream_endpoint_emits_step_and_answer_events() -> None:
    stub = StubStreamingAgent()
    app.dependency_overrides[get_agent] = lambda: stub
    try:
        response = client.post("/query/stream", json={"query": "What is Starter?", "thread_id": "tid-42"})
        assert response.status_code == 200
        events = _parse_sse_events(response.text)

        event_names = [e[0] for e in events]
        # Should follow planner start -> planner end -> worker start -> worker end -> answer -> done
        assert event_names == ["step", "step", "step", "step", "answer", "done"]

        # Planner start
        assert events[0][1]["node"] == "planner"
        assert events[0][1]["status"] == "start"

        # Planner end
        assert events[1][1]["node"] == "planner"
        assert events[1][1]["status"] == "end"

        # Worker start
        assert events[2][1]["node"] == "worker"
        assert events[2][1]["status"] == "start"

        # Worker end
        assert events[3][1]["node"] == "worker"
        assert events[3][1]["status"] == "end"

        # Answer
        assert events[4][1]["answer"] == "Mock answer for: What is Starter?"
        assert events[4][1]["evidence"] == [{"id": 1, "name": "Starter"}]
        assert events[4][1]["thread_id"] == "tid-42"

        # Done is always last
        assert events[5][0] == "done"
    finally:
        app.dependency_overrides.clear()


def test_sse_done_is_always_last_on_exception() -> None:
    stub = StubStreamingAgent(should_raise=True)
    app.dependency_overrides[get_agent] = lambda: stub
    try:
        response = client.post("/query/stream", json={"query": "Trigger error"})
        assert response.status_code == 200
        events = _parse_sse_events(response.text)

        assert len(events) >= 2
        last_event_type, last_data = events[-1]
        assert last_event_type == "done"
        assert last_data == {}

        # The event right before done should be error
        error_event_type, error_data = events[-2]
        assert error_event_type == "error"
        assert "Simulation failure" in error_data["message"]
    finally:
        app.dependency_overrides.clear()


def test_stream_endpoint_without_langsmith_emits_no_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    stub = StubStreamingAgent(run_id="run-1234")
    app.dependency_overrides[get_agent] = lambda: stub
    try:
        response = client.post("/query/stream", json={"query": "Hello without trace"})
        events = _parse_sse_events(response.text)
        event_names = [e[0] for e in events]
        assert "trace" not in event_names
    finally:
        app.dependency_overrides.clear()


def test_stream_endpoint_with_langsmith_emits_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_PROJECT", "agentic-rag-test")

    stub = StubStreamingAgent(run_id="run-5678")
    app.dependency_overrides[get_agent] = lambda: stub
    try:
        response = client.post("/query/stream", json={"query": "Hello with trace"})
        events = _parse_sse_events(response.text)
        event_names = [e[0] for e in events]
        assert "trace" in event_names
        trace_event = next(e for e in events if e[0] == "trace")
        assert "smith.langchain.com/public/run-5678/r" in trace_event[1]["url"]
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Integration test for stream_with_evidence on real BasicAgent
# ---------------------------------------------------------------------------

class FakeLLMForStream:
    def invoke(self, input: object) -> AIMessage:
        return AIMessage(content="General answer from fake LLM.")


def test_basic_agent_stream_with_evidence_stateless() -> None:
    fake_llm = FakeLLMForStream()
    mock_mcp = MagicMock()
    graph = create_agent_graph(llm=fake_llm, mcp_client=mock_mcp)
    agent = BasicAgent(graph=graph, mcp_client=mock_mcp)

    events = list(agent.stream_with_evidence("What is the meaning of life?"))
    event_types = [e["event"] for e in events]

    assert "step" in event_types
    assert "answer" in event_types
    assert "done" in event_types

    answer_ev = next(e for e in events if e["event"] == "answer")
    assert "General answer from fake LLM." in answer_ev["data"]["answer"]
    assert events[-1]["event"] == "done"
