import pytest
from langchain_core.messages import AIMessage

from app.agent import (
    AgentError,
    AgentNotConfiguredError,
    BasicAgent,
    create_agent_graph,
    create_llm,
)


class FakeLLM:
    def __init__(self) -> None:
        self.inputs: list[object] = []

    def invoke(self, input: object) -> AIMessage:
        self.inputs.append(input)
        return AIMessage(content="A deterministic agent answer.")


def test_agent_graph_invokes_llm_and_returns_answer() -> None:
    llm = FakeLLM()
    graph = create_agent_graph(llm)

    result = graph.invoke({"query": "What is RAG?"})

    assert result == {
        "query": "What is RAG?",
        "answer": "A deterministic agent answer.",
    }
    assert len(llm.inputs) == 1


def test_basic_agent_returns_graph_answer() -> None:
    graph = create_agent_graph(FakeLLM())
    agent = BasicAgent(graph)

    assert agent.answer("What is RAG?") == "A deterministic agent answer."


def test_create_llm_groq_requires_key(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(AgentNotConfiguredError, match="GROQ_API_KEY"):
        create_llm()


def test_create_llm_groq_uses_groq_base_url_and_model(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)

    llm = create_llm()

    assert llm.model_name == "openai/gpt-oss-20b"
    assert "api.groq.com" in str(llm.openai_api_base)


def test_create_llm_rejects_unknown_provider(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "nope")

    with pytest.raises(AgentNotConfiguredError, match="Unsupported LLM_PROVIDER"):
        create_llm()


def test_create_llm_openai_default_still_requires_openai_key(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(AgentNotConfiguredError, match="OPENAI_API_KEY"):
        create_llm()


def test_provider_failure_becomes_agent_error() -> None:
    class BoomGraph:
        def invoke(self, input: object) -> object:
            raise RuntimeError("secret provider detail")

    with pytest.raises(AgentError) as info:
        BasicAgent(BoomGraph()).answer("hi")

    assert "RuntimeError" in str(info.value)
    assert "secret provider detail" not in str(info.value)
