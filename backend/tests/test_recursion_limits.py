"""Strict recursion-limit guards: a looping graph must be stopped, never run forever."""
from typing import Any, TypedDict

import pytest
from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph

from app.agent import (
    DEFAULT_RECURSION_LIMIT,
    MAX_RECURSION_LIMIT,
    MIN_RECURSION_LIMIT,
    AgentRecursionLimitError,
    BasicAgent,
    get_recursion_limit,
)
from app.main import app, get_agent
from app.schemas import MAX_QUERY_LENGTH


class _LoopState(TypedDict, total=False):
    query: str
    answer: str
    hops: int


def _looping_graph() -> Any:
    """A deliberately broken graph that never reaches END."""

    def spin(state: _LoopState) -> dict[str, Any]:
        return {"hops": state.get("hops", 0) + 1}

    g = StateGraph(_LoopState)
    g.add_node("spin", spin)
    g.add_edge(START, "spin")
    g.add_conditional_edges("spin", lambda _s: "spin", {"spin": "spin", END: END})
    return g.compile()


def test_default_limit_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_RECURSION_LIMIT", raising=False)
    assert get_recursion_limit() == DEFAULT_RECURSION_LIMIT


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("7", 7),
        ("1", MIN_RECURSION_LIMIT),
        ("0", MIN_RECURSION_LIMIT),
        ("-5", MIN_RECURSION_LIMIT),
        ("100000", MAX_RECURSION_LIMIT),
        ("abc", DEFAULT_RECURSION_LIMIT),
        ("  ", DEFAULT_RECURSION_LIMIT),
    ],
)
def test_limit_is_always_clamped(monkeypatch: pytest.MonkeyPatch, raw: str, expected: int) -> None:
    monkeypatch.setenv("AGENT_RECURSION_LIMIT", raw)
    assert get_recursion_limit() == expected


def test_looping_graph_raises_recursion_limit_error() -> None:
    agent = BasicAgent(graph=_looping_graph())
    with pytest.raises(AgentRecursionLimitError, match="step limit"):
        agent.query_with_evidence("loop forever")


def test_looping_graph_with_thread_id_also_stopped() -> None:
    from langgraph.checkpoint.memory import InMemorySaver

    g = StateGraph(_LoopState)
    g.add_node("spin", lambda s: {"hops": s.get("hops", 0) + 1})
    g.add_edge(START, "spin")
    g.add_conditional_edges("spin", lambda _s: "spin", {"spin": "spin", END: END})
    saver = InMemorySaver()
    agent = BasicAgent(graph=g.compile(checkpointer=saver), checkpointer=saver)
    with pytest.raises(AgentRecursionLimitError):
        agent.query_with_evidence("loop", thread_id="t-1")


def test_looping_graph_stream_emits_error_then_done() -> None:
    agent = BasicAgent(graph=_looping_graph())
    events = list(agent.stream_with_evidence("loop forever"))
    names = [e["event"] for e in events]
    assert "error" in names
    assert names[-1] == "done"
    assert "step limit" in next(e for e in events if e["event"] == "error")["data"]["message"]
    assert "answer" not in names


def test_loop_is_bounded_by_configured_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_RECURSION_LIMIT", "5")
    seen: list[int] = []

    def spin(state: _LoopState) -> dict[str, Any]:
        seen.append(1)
        return {"hops": state.get("hops", 0) + 1}

    g = StateGraph(_LoopState)
    g.add_node("spin", spin)
    g.add_edge(START, "spin")
    g.add_conditional_edges("spin", lambda _s: "spin", {"spin": "spin", END: END})
    with pytest.raises(AgentRecursionLimitError):
        BasicAgent(graph=g.compile()).query_with_evidence("x")
    assert 0 < len(seen) <= 5


def test_http_endpoint_maps_recursion_error_to_422() -> None:
    app.dependency_overrides[get_agent] = lambda: BasicAgent(graph=_looping_graph())
    try:
        response = TestClient(app).post("/query", json={"query": "loop"})
        assert response.status_code == 422
        assert "step limit" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_stream_endpoint_reports_recursion_error_and_ends_with_done() -> None:
    app.dependency_overrides[get_agent] = lambda: BasicAgent(graph=_looping_graph())
    try:
        response = TestClient(app).post("/query/stream", json={"query": "loop"})
        assert response.status_code == 200
        assert "event: error" in response.text
        assert response.text.rstrip().endswith("event: done\r\ndata: {}")
    finally:
        app.dependency_overrides.clear()


def test_normal_graph_runs_well_within_default_limit() -> None:
    """The real planner->worker graph must never be tripped by the default limit."""
    from unittest.mock import MagicMock

    from langchain_core.messages import AIMessage

    from app.agent import create_agent_graph

    class Fake:
        def invoke(self, _input: object) -> AIMessage:
            return AIMessage(content="ok")

    agent = BasicAgent(graph=create_agent_graph(llm=Fake(), mcp_client=MagicMock()))
    answer, _ = agent.query_with_evidence("hello there")
    assert answer == "ok"


def test_query_longer_than_cap_is_rejected() -> None:
    client = TestClient(app)
    response = client.post("/query", json={"query": "a" * (MAX_QUERY_LENGTH + 1)})
    assert response.status_code == 422
    response = client.post("/query/stream", json={"query": "a" * (MAX_QUERY_LENGTH + 1)})
    assert response.status_code == 422
