from fastapi.testclient import TestClient

from app.agent import AgentNotConfiguredError, get_agent
from app.main import app

client = TestClient(app)


def test_health_check_returns_success() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


class StubAgent:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def answer(self, query: str) -> str:
        self.queries.append(query)
        return "Retrieval augmented generation combines retrieval with generation."


def test_query_returns_agent_answer() -> None:
    agent = StubAgent()
    app.dependency_overrides[get_agent] = lambda: agent

    response = client.post(
        "/query",
        json={"query": "What is retrieval augmented generation?"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {
        "answer": "Retrieval augmented generation combines retrieval with generation."
    }
    assert agent.queries == ["What is retrieval augmented generation?"]


def test_query_rejects_missing_query() -> None:
    response = client.post("/query", json={})

    assert response.status_code == 422


def test_query_rejects_blank_query() -> None:
    response = client.post("/query", json={"query": "   "})

    assert response.status_code == 422


def test_query_returns_service_unavailable_when_llm_is_not_configured() -> None:
    class UnconfiguredAgent:
        def answer(self, query: str) -> str:
            raise AgentNotConfiguredError("OPENAI_API_KEY is required to call the LLM.")

    app.dependency_overrides[get_agent] = lambda: UnconfiguredAgent()

    response = client.post("/query", json={"query": "Hello"})

    app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json() == {"detail": "OPENAI_API_KEY is required to call the LLM."}
