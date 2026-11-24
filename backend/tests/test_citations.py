from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from app.agent import (
    BasicAgent,
    _build_citation_index,
    _validate_citations,
    create_agent_graph,
    worker_node,
)


class FakeLLM:
    def __init__(self, answer: str = "A mock LLM answer.") -> None:
        self.inputs: list[object] = []
        self.answer = answer

    def invoke(self, input: object) -> AIMessage:
        self.inputs.append(input)
        return AIMessage(content=self.answer)


def test_build_citation_index_uses_id_field() -> None:
    records = [{"id": 3, "name": "Enterprise", "price": 5000.0, "category": "Subscriptions"}]
    index = _build_citation_index(records)
    assert index == {"Product-3": "3"}


def test_build_citation_index_fallback_for_missing_id() -> None:
    records = [
        {"name": "Custom Tier", "price": 100.0},
        {"id": 7, "name": "Support Tier", "price": 200.0},
    ]
    index = _build_citation_index(records)
    assert index == {"Product-row0": "row0", "Product-7": "7"}


def test_validate_citations_keeps_valid_marker() -> None:
    records = [{"id": 3, "name": "Enterprise"}]
    answer = "The Enterprise tier costs $5000 [Product-3]."
    validated = _validate_citations(answer, records)
    assert validated == "The Enterprise tier costs $5000 [Product-3]."


def test_validate_citations_strips_fabricated_marker() -> None:
    records = [{"id": 3, "name": "Enterprise"}]
    answer = "The Enterprise tier costs $5000 [Product-99]."
    validated = _validate_citations(answer, records)
    assert "[Product-99]" not in validated
    assert "costs $5000." in validated


def test_validate_citations_strips_all_on_empty_records() -> None:
    records: list[dict[str, Any]] = []
    answer = "No products found [Product-1] or [Product-2]."
    validated = _validate_citations(answer, records)
    assert "[Product-1]" not in validated
    assert "[Product-2]" not in validated


def test_validate_citations_multiple_markers_mixed() -> None:
    records = [{"id": 1, "name": "Starter"}, {"id": 2, "name": "Pro"}]
    answer = "Starter is $29 [Product-1], Pro is $99 [Product-2], Ultra is $999 [Product-999]."
    validated = _validate_citations(answer, records)
    assert "[Product-1]" in validated
    assert "[Product-2]" in validated
    assert "[Product-999]" not in validated


def test_worker_node_prompt_contains_valid_citation_keys() -> None:
    mock_mcp = MagicMock()
    mock_mcp.execute_query_sync.return_value = [
        {"id": 3, "name": "Enterprise", "price": 5000.0, "category": "Subscriptions"}
    ]
    fake_llm = FakeLLM(answer="Enterprise costs $5000 [Product-3].")
    state = {
        "query": "Enterprise price",
        "plan": "db",
        "sql": "SELECT id, name, description, price, category FROM products WHERE name LIKE '%enterprise%'",
    }
    result = worker_node(state, fake_llm, mock_mcp)

    prompt_text = str(fake_llm.inputs[0])
    assert "Product-3" in prompt_text
    assert result["answer"] == "Enterprise costs $5000 [Product-3]."


def test_worker_node_strips_fabricated_citation_in_answer() -> None:
    mock_mcp = MagicMock()
    mock_mcp.execute_query_sync.return_value = [
        {"id": 3, "name": "Enterprise", "price": 5000.0, "category": "Subscriptions"}
    ]
    fake_llm = FakeLLM(answer="Enterprise costs $5000 [Product-99].")
    state = {
        "query": "Enterprise price",
        "plan": "db",
        "sql": "SELECT id, name, description, price, category FROM products WHERE name LIKE '%enterprise%'",
    }
    result = worker_node(state, fake_llm, mock_mcp)

    assert "[Product-99]" not in result["answer"]
    assert "costs $5000." in result["answer"]
