from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from app.agent import (
    AgentError,
    create_agent_graph,
    planner_node,
    worker_node,
)
from app.mcp_client import McpClientError


class FakeLLM:
    def __init__(self, answer: str = "A mock LLM answer.") -> None:
        self.inputs: list[object] = []
        self.answer = answer

    def invoke(self, input: object) -> AIMessage:
        self.inputs.append(input)
        return AIMessage(content=self.answer)


def test_planner_sets_plan_db_for_db_query() -> None:
    state = {"query": "What is the price of the Enterprise package?"}
    result = planner_node(state)

    assert result["plan"] == "db"
    assert result["sql"] is not None
    assert "enterprise" in result["sql"].lower()


def test_planner_sets_plan_general_for_general_query() -> None:
    state = {"query": "What is retrieval augmented generation?"}
    result = planner_node(state)

    assert result["plan"] == "general"
    assert result["sql"] is None


def test_worker_calls_mcp_when_plan_is_db() -> None:
    mock_mcp = MagicMock()
    mock_mcp.execute_query_sync.return_value = [
        {"id": 1, "name": "Enterprise package", "price": 5000.0, "category": "Subscriptions"}
    ]
    fake_llm = FakeLLM(answer="The Enterprise package costs $5,000.")

    state = {
        "query": "What is the price of the Enterprise package?",
        "plan": "db",
        "sql": "SELECT id, name, price, category FROM products WHERE LOWER(name) LIKE '%enterprise%'",
    }
    result = worker_node(state, fake_llm, mock_mcp)

    assert result["answer"] == "The Enterprise package costs $5,000."
    assert result["evidence"] == [
        {"id": 1, "name": "Enterprise package", "price": 5000.0, "category": "Subscriptions"}
    ]
    mock_mcp.execute_query_sync.assert_called_once_with(state["sql"])
    assert len(fake_llm.inputs) == 1
    assert "Enterprise package" in str(fake_llm.inputs[0])


def test_worker_skips_mcp_when_plan_is_general() -> None:
    mock_mcp = MagicMock()
    fake_llm = FakeLLM(answer="RAG stands for Retrieval-Augmented Generation.")

    state = {
        "query": "What is RAG?",
        "plan": "general",
        "sql": None,
    }
    result = worker_node(state, fake_llm, mock_mcp)

    assert result["answer"] == "RAG stands for Retrieval-Augmented Generation."
    assert result["evidence"] is None
    mock_mcp.execute_query_sync.assert_not_called()
    assert len(fake_llm.inputs) == 1


def test_worker_raises_agent_error_on_mcp_failure() -> None:
    mock_mcp = MagicMock()
    mock_mcp.execute_query_sync.side_effect = McpClientError("Connection refused")
    fake_llm = FakeLLM()

    state = {
        "query": "Show all products",
        "plan": "db",
        "sql": "SELECT id, name, price, category FROM products",
    }

    with pytest.raises(AgentError, match="MCP retrieval failed"):
        worker_node(state, fake_llm, mock_mcp)


def test_full_graph_db_query_end_to_end() -> None:
    mock_mcp = MagicMock()
    mock_mcp.execute_query_sync.return_value = [
        {"id": 2, "name": "Starter package", "price": 100.0, "category": "Subscriptions"}
    ]
    fake_llm = FakeLLM(answer="The Starter package costs $100.")

    graph = create_agent_graph(llm=fake_llm, mcp_client=mock_mcp)
    result = graph.invoke({"query": "How much does the Starter package cost?"})

    assert result["query"] == "How much does the Starter package cost?"
    assert result["plan"] == "db"
    assert result["sql"] is not None
    assert "starter" in result["sql"].lower()
    assert result["answer"] == "The Starter package costs $100."
    assert result["evidence"] == [
        {"id": 2, "name": "Starter package", "price": 100.0, "category": "Subscriptions"}
    ]


def test_full_graph_general_query_end_to_end() -> None:
    mock_mcp = MagicMock()
    fake_llm = FakeLLM(answer="Hello! How can I help you today?")

    graph = create_agent_graph(llm=fake_llm, mcp_client=mock_mcp)
    result = graph.invoke({"query": "Hello there"})

    assert result["query"] == "Hello there"
    assert result["plan"] == "general"
    assert result["sql"] is None
    assert result["answer"] == "Hello! How can I help you today?"
    assert result["evidence"] is None
    mock_mcp.execute_query_sync.assert_not_called()
