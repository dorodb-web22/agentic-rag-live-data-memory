import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.agent import (
    BasicAgent,
    build_sql_query,
    create_agent_graph,
    get_agent,
    is_database_query,
)
from app.db_setup import init_demo_database
from app.main import app
from app.mcp_client import McpClientError, SqliteMcpClient


class RecordingFakeLLM:
    def __init__(self, answer: str = "A mock LLM answer.") -> None:
        self.inputs: list[object] = []
        self.answer = answer

    def invoke(self, input: object) -> AIMessage:
        self.inputs.append(input)
        return AIMessage(content=self.answer)


@pytest.fixture(scope="module")
def initialized_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    temp_dir = tmp_path_factory.mktemp("test_mcp_db")
    db_file = temp_dir / "test_products.db"
    init_demo_database(db_file)
    return db_file


@pytest.fixture
def mcp_client(initialized_db: Path) -> SqliteMcpClient:
    return SqliteMcpClient(db_path=initialized_db)


def test_demo_database_initialization(initialized_db: Path) -> None:
    assert initialized_db.exists()
    assert initialized_db.stat().st_size > 0


def test_is_database_query_detection() -> None:
    assert is_database_query("What is the price of the Enterprise package?") is True
    assert is_database_query("Show me the products catalog") is True
    assert is_database_query("How much does the Starter subscription cost?") is True
    assert is_database_query("What is retrieval augmented generation?") is False
    assert is_database_query("Hello, who are you?") is False


def test_build_sql_query_generation() -> None:
    sql1, term1 = build_sql_query("What is the price of the Enterprise package?")
    assert "WHERE LOWER(name) LIKE '%enterprise%'" in sql1
    assert term1 == "enterprise"

    sql2, term2 = build_sql_query("What is the price of the Quantum package?")
    assert "WHERE LOWER(name) LIKE '%quantum%'" in sql2
    assert term2 == "quantum"

    sql3, term3 = build_sql_query("Show all available products")
    assert sql3 == "SELECT id, name, description, price, category FROM products"
    assert term3 is None


def test_mcp_client_lists_tables(mcp_client: SqliteMcpClient) -> None:
    tables = mcp_client.get_tables_sync()
    assert "products" in tables


def test_mcp_client_describes_table(mcp_client: SqliteMcpClient) -> None:
    schema = mcp_client.describe_table_sync("products")
    column_names = [col["name"] for col in schema]
    assert "id" in column_names
    assert "name" in column_names
    assert "price" in column_names
    assert "category" in column_names


def test_mcp_client_real_query_retrieval(mcp_client: SqliteMcpClient) -> None:
    records = mcp_client.execute_query_sync(
        "SELECT id, name, price, category FROM products WHERE LOWER(name) LIKE '%enterprise%'"
    )
    assert len(records) == 1
    record = records[0]
    assert record["name"] == "Enterprise package"
    assert record["price"] == 5000.0
    assert record["category"] == "Subscriptions"


def test_mcp_client_empty_results(mcp_client: SqliteMcpClient) -> None:
    records = mcp_client.execute_query_sync(
        "SELECT id, name, price FROM products WHERE LOWER(name) LIKE '%nonexistent_package%'"
    )
    assert records == []


def test_mcp_client_security_rejects_non_select(mcp_client: SqliteMcpClient) -> None:
    with pytest.raises(McpClientError, match="Only SELECT queries are permitted"):
        mcp_client.execute_query_sync("DROP TABLE products")

    with pytest.raises(McpClientError, match="Only SELECT queries are permitted"):
        mcp_client.execute_query_sync("INSERT INTO products VALUES (99, 'bad', 0, 'bad')")

    with pytest.raises(McpClientError, match="Only SELECT queries are permitted"):
        mcp_client.execute_query_sync("UPDATE products SET price = 0")


def test_mcp_client_security_rejects_semicolons_and_comments(mcp_client: SqliteMcpClient) -> None:
    with pytest.raises(McpClientError, match="Multiple statements or semicolons"):
        mcp_client.execute_query_sync("SELECT * FROM products; DROP TABLE products")

    with pytest.raises(McpClientError, match="SQL comments are not permitted"):
        mcp_client.execute_query_sync("SELECT * FROM products -- malicious comment")


def test_mcp_client_missing_database_raises_error(tmp_path: Path) -> None:
    missing_client = SqliteMcpClient(db_path=tmp_path / "nonexistent.db")
    with pytest.raises(McpClientError, match="database file not found"):
        missing_client.execute_query_sync("SELECT * FROM products")


def test_agent_database_query_integration_with_fake_llm(mcp_client: SqliteMcpClient) -> None:
    fake_llm = RecordingFakeLLM(
        answer="The Enterprise package costs $5,000.\n\n### Supporting Evidence\n- Record ID: 3\n- Price: $5000"
    )
    agent = BasicAgent(
        graph=create_agent_graph(llm=fake_llm, mcp_client=mcp_client),
        mcp_client=mcp_client,
    )

    answer, evidence = agent.query_with_evidence(
        "What is the price of the Enterprise package, and what database information supports your answer?"
    )

    assert "The Enterprise package costs $5,000" in answer
    assert evidence is not None
    assert len(evidence) == 1
    assert evidence[0]["name"] == "Enterprise package"
    assert evidence[0]["price"] == 5000.0

    # Verify that the LLM received the database evidence in its prompt
    assert len(fake_llm.inputs) == 1
    prompt_sent = str(fake_llm.inputs[0])
    assert "Enterprise package" in prompt_sent
    assert "5000" in prompt_sent


def test_agent_unknown_product_retrieval_with_fake_llm(mcp_client: SqliteMcpClient) -> None:
    fake_llm = RecordingFakeLLM(
        answer="I could not find a Quantum package in the database.\n\n### Supporting Evidence\n0 records returned."
    )
    agent = BasicAgent(
        graph=create_agent_graph(llm=fake_llm, mcp_client=mcp_client),
        mcp_client=mcp_client,
    )

    answer, evidence = agent.query_with_evidence("What is the price of the Quantum package?")
    assert "could not find" in answer
    assert evidence == []

    # Verify that the LLM was explicitly instructed not to fabricate facts
    prompt_sent = str(fake_llm.inputs[0])
    assert "No matching records found" in prompt_sent
    assert "Do NOT invent" in prompt_sent


def test_agent_general_query_bypasses_mcp_retrieval(mcp_client: SqliteMcpClient) -> None:
    fake_llm = RecordingFakeLLM(answer="RAG combines retrieval with generation.")
    agent = BasicAgent(
        graph=create_agent_graph(llm=fake_llm, mcp_client=mcp_client),
        mcp_client=mcp_client,
    )

    answer, evidence = agent.query_with_evidence("What is retrieval augmented generation?")
    assert answer == "RAG combines retrieval with generation."
    assert evidence is None

    prompt_sent = str(fake_llm.inputs[0])
    assert "Database Source: SQLite" not in prompt_sent


def test_api_query_returns_evidence_for_database_query(mcp_client: SqliteMcpClient) -> None:
    fake_llm = RecordingFakeLLM(
        answer="The Starter package costs $100.\n\n### Supporting Evidence\n| Record ID: 1 | Price: $100 |"
    )
    test_agent = BasicAgent(
        graph=create_agent_graph(llm=fake_llm, mcp_client=mcp_client),
        mcp_client=mcp_client,
    )

    app.dependency_overrides[get_agent] = lambda: test_agent
    client = TestClient(app)

    try:
        response = client.post(
            "/query",
            json={"query": "What is the price of the Starter package?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "Starter package costs $100" in data["answer"]
        assert data["evidence"] is not None
        assert len(data["evidence"]) == 1
        assert data["evidence"][0]["name"] == "Starter package"
        assert data["evidence"][0]["price"] == 100.0
    finally:
        app.dependency_overrides.clear()
