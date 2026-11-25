"""Tests for GET /threads/{thread_id} history hydration endpoint."""
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent import BasicAgent, create_agent_graph
from app.main import app, get_agent


class _FakeLLM:
    def invoke(self, _input: object) -> AIMessage:
        return AIMessage(content="Enterprise costs $5,000 [Product-3].")


def test_get_thread_history_returns_saved_messages_and_evidence() -> None:
    saver = InMemorySaver()
    mcp = MagicMock()
    mcp.execute_query_sync.return_value = [
        {"id": 3, "name": "Enterprise", "price": 5000.0, "category": "Subscriptions"}
    ]
    graph = create_agent_graph(llm=_FakeLLM(), mcp_client=mcp, checkpointer=saver)
    agent = BasicAgent(graph=graph, mcp_client=mcp, checkpointer=saver)

    app.dependency_overrides[get_agent] = lambda: agent
    try:
        client = TestClient(app)
        res = client.post(
            "/query",
            json={"query": "How much is Enterprise?", "thread_id": "thread-42"},
        )
        assert res.status_code == 200

        # Fresh BasicAgent without compiled graph still reads directly from saver
        fresh_agent = BasicAgent(checkpointer=saver)
        app.dependency_overrides[get_agent] = lambda: fresh_agent

        hist = client.get("/threads/thread-42")
        assert hist.status_code == 200
        body = hist.json()
        assert body["thread_id"] == "thread-42"
        assert body["messages"] == [
            {"role": "user", "content": "How much is Enterprise?"},
            {"role": "assistant", "content": "Enterprise costs $5,000 [Product-3]."},
        ]
        assert body["evidence"][0]["name"] == "Enterprise"
    finally:
        app.dependency_overrides.clear()


def test_get_thread_history_404_when_unknown() -> None:
    saver = InMemorySaver()
    app.dependency_overrides[get_agent] = lambda: BasicAgent(checkpointer=saver)
    try:
        res = TestClient(app).get("/threads/does-not-exist")
        assert res.status_code == 404
    finally:
        app.dependency_overrides.clear()
