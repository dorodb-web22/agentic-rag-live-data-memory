from langchain_core.messages import AIMessage

from app.agent import BasicAgent, create_agent_graph


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
