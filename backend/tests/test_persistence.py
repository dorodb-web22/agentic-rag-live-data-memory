"""Week 5 tests for PostgreSQL checkpointer persistence and thread-scoped conversational memory."""

import os
from typing import Any
from unittest.mock import MagicMock, patch
import uuid

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from psycopg.rows import dict_row
import pytest

from app.agent import (
    AgentError,
    BasicAgent,
    create_agent_graph,
    get_agent,
)
from app.main import app
from app.persistence import (
    PersistenceError,
    PersistenceNotConfiguredError,
    PostgresPersistenceManager,
    create_connection_pool,
    create_postgres_checkpointer,
    init_optional_checkpointer_from_env,
    resolve_database_url,
)


class SequencedFakeLLM:
    """Fake LLM that records incoming message lists and returns sequenced answers."""

    def __init__(self, answers: list[str] | None = None) -> None:
        self.inputs: list[Any] = []
        self._answers = list(answers or ["Default fake answer."])
        self._index = 0

    def invoke(self, input_messages: Any) -> AIMessage:
        self.inputs.append(input_messages)
        answer = self._answers[min(self._index, len(self._answers) - 1)]
        self._index += 1
        return AIMessage(content=answer)


def test_resolve_database_url_rejects_missing_or_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(PersistenceNotConfiguredError, match="DATABASE_URL is not configured"):
        resolve_database_url()

    with pytest.raises(PersistenceNotConfiguredError, match="DATABASE_URL is not configured"):
        resolve_database_url("   ")


def test_resolve_database_url_rejects_non_postgres_scheme() -> None:
    with pytest.raises(PersistenceNotConfiguredError, match=r"must start with 'postgresql://' or 'postgres://'"):
        resolve_database_url("sqlite:///tmp/demo.db")


def test_create_connection_pool_rejects_min_size_zero() -> None:
    with pytest.raises(PersistenceError, match="min_size must be >= 1"):
        create_connection_pool(
            database_url="postgresql://postgres:postgres@localhost:5432/agentic_rag",
            min_size=0,
            max_size=5,
            open_pool=False,
        )


def test_create_connection_pool_configures_autocommit_and_dict_row() -> None:
    with patch("app.persistence.ConnectionPool") as mock_pool_cls:
        mock_pool_instance = MagicMock()
        mock_pool_cls.return_value = mock_pool_instance

        pool = create_connection_pool(
            database_url="postgresql://postgres:postgres@localhost:5432/agentic_rag",
            min_size=2,
            max_size=8,
            open_pool=True,
            connect_timeout=4,
        )

        assert pool is mock_pool_instance
        mock_pool_cls.assert_called_once()
        _, kwargs = mock_pool_cls.call_args
        assert kwargs["conninfo"] == "postgresql://postgres:postgres@localhost:5432/agentic_rag"
        assert kwargs["min_size"] == 2
        assert kwargs["max_size"] == 8
        assert kwargs["open"] is False
        assert kwargs["kwargs"]["autocommit"] is True
        assert kwargs["kwargs"]["row_factory"] is dict_row
        assert kwargs["kwargs"]["connect_timeout"] == 4
        mock_pool_instance.open.assert_called_once_with(wait=True, timeout=6.0)


def test_create_connection_pool_validates_pool_sizes() -> None:
    with pytest.raises(PersistenceError, match="max_size"):
        create_connection_pool(
            database_url="postgresql://postgres:postgres@localhost:5432/agentic_rag",
            min_size=5,
            max_size=2,
        )


def test_create_postgres_checkpointer_calls_setup() -> None:
    mock_pool = MagicMock()
    with patch("app.persistence.PostgresSaver") as mock_saver_cls:
        mock_saver = MagicMock()
        mock_saver_cls.return_value = mock_saver

        checkpointer = create_postgres_checkpointer(mock_pool, setup_schema=True)

        assert checkpointer is mock_saver
        mock_saver_cls.assert_called_once_with(mock_pool)
        mock_saver.setup.assert_called_once()


def test_postgres_persistence_manager_closes_pool_if_setup_fails() -> None:
    with (
        patch("app.persistence.create_connection_pool") as mock_create_pool,
        patch("app.persistence.create_postgres_checkpointer") as mock_create_cp,
    ):
        mock_pool = MagicMock()
        mock_create_pool.return_value = mock_pool
        mock_create_cp.side_effect = PersistenceError("DDL failed")

        manager = PostgresPersistenceManager(
            database_url="postgresql://postgres:postgres@localhost:5432/agentic_rag"
        )
        with pytest.raises(PersistenceError, match="DDL failed"):
            manager.start()

        mock_pool.close.assert_called_once()
        assert manager.pool is None
        assert manager.checkpointer is None


def test_init_optional_checkpointer_returns_none_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    manager, checkpointer = init_optional_checkpointer_from_env()
    assert manager is None
    assert checkpointer is None


def test_graph_compiles_with_checkpointer_and_saves_state_at_every_step() -> None:
    checkpointer = InMemorySaver()
    mock_mcp = MagicMock()
    mock_mcp.execute_query_sync.return_value = [
        {"id": 3, "name": "Enterprise package", "price": 5000.0, "category": "Subscriptions"}
    ]
    fake_llm = SequencedFakeLLM(answers=["The Enterprise package costs $5,000 [Product-3]."])

    graph = create_agent_graph(llm=fake_llm, mcp_client=mock_mcp, checkpointer=checkpointer)
    assert graph.checkpointer is checkpointer

    thread_id = "thread-step-verify"
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke({"query": "What is the price of the Enterprise package?"}, config)

    assert result["answer"] == "The Enterprise package costs $5,000 [Product-3]."

    snapshot = graph.get_state(config)
    assert snapshot.values["query"] == "What is the price of the Enterprise package?"
    assert snapshot.values["plan"] == "db"
    assert "enterprise" in snapshot.values["sql"].lower()
    assert snapshot.values["evidence"] == [
        {"id": 3, "name": "Enterprise package", "price": 5000.0, "category": "Subscriptions"}
    ]
    assert len(snapshot.values["messages"]) == 2
    assert isinstance(snapshot.values["messages"][0], HumanMessage)
    assert isinstance(snapshot.values["messages"][1], AIMessage)

    history = list(graph.get_state_history(config))
    assert len(history) >= 3


def test_resuming_conversation_with_same_thread_id_passes_history_to_llm() -> None:
    checkpointer = InMemorySaver()
    mock_mcp = MagicMock()
    mock_mcp.execute_query_sync.return_value = [
        {"id": 3, "name": "Enterprise package", "price": 5000.0, "category": "Subscriptions"}
    ]
    fake_llm = SequencedFakeLLM(
        answers=[
            "The Enterprise package costs $5,000 [Product-3].",
            "As mentioned earlier, the Enterprise package includes a dedicated account manager.",
        ]
    )

    agent_1 = BasicAgent(
        graph=create_agent_graph(llm=fake_llm, mcp_client=mock_mcp, checkpointer=checkpointer),
        mcp_client=mock_mcp,
        checkpointer=checkpointer,
    )
    answer_1, evidence_1 = agent_1.query_with_evidence(
        "What is the price of the Enterprise package?",
        thread_id="shared-thread-1",
    )
    assert "[Product-3]" in answer_1
    assert evidence_1 is not None

    agent_2 = BasicAgent(
        graph=create_agent_graph(llm=fake_llm, mcp_client=mock_mcp, checkpointer=checkpointer),
        mcp_client=mock_mcp,
        checkpointer=checkpointer,
    )
    answer_2, _ = agent_2.query_with_evidence(
        "Summarize what you just told me.",
        thread_id="shared-thread-1",
    )
    assert "dedicated account manager" in answer_2

    turn_2_messages = fake_llm.inputs[1]
    serialized_turn_2 = "\n".join(str(getattr(m, "content", m)) for m in turn_2_messages)
    assert "What is the price of the Enterprise package?" in serialized_turn_2
    assert "The Enterprise package costs $5,000 [Product-3]." in serialized_turn_2

    state = agent_2.get_thread_state("shared-thread-1")
    assert state is not None
    assert len(state["messages"]) == 4


def test_two_different_thread_ids_are_strictly_isolated() -> None:
    checkpointer = InMemorySaver()
    mock_mcp = MagicMock()
    mock_mcp.execute_query_sync.return_value = [
        {"id": 1, "name": "Starter package", "price": 100.0, "category": "Subscriptions"}
    ]
    fake_llm = SequencedFakeLLM(
        answers=[
            "Starter costs $100 [Product-1].",
            "Hello Bob, RAG combines retrieval with generation.",
            "Alice, your Starter tier is $100.",
        ]
    )
    agent = BasicAgent(
        graph=create_agent_graph(llm=fake_llm, mcp_client=mock_mcp, checkpointer=checkpointer),
        mcp_client=mock_mcp,
        checkpointer=checkpointer,
    )

    agent.query_with_evidence("How much is the Starter package?", thread_id="thread-alice")
    agent.query_with_evidence("Hi, I am Bob. What is RAG?", thread_id="thread-bob")
    agent.query_with_evidence("Can you repeat that for me?", thread_id="thread-alice")

    alice_turn_2_input = "\n".join(str(getattr(m, "content", m)) for m in fake_llm.inputs[2])
    assert "Starter costs $100 [Product-1]." in alice_turn_2_input
    assert "Bob" not in alice_turn_2_input

    alice_state = agent.get_thread_state("thread-alice")
    bob_state = agent.get_thread_state("thread-bob")
    assert alice_state is not None and len(alice_state["messages"]) == 4
    assert bob_state is not None and len(bob_state["messages"]) == 2
    assert all("Bob" not in str(m.content) for m in alice_state["messages"])


def test_fastapi_query_endpoint_generates_and_reuses_thread_id() -> None:
    checkpointer = InMemorySaver()
    mock_mcp = MagicMock()
    mock_mcp.execute_query_sync.return_value = [
        {"id": 3, "name": "Enterprise package", "price": 5000.0, "category": "Subscriptions"}
    ]
    fake_llm = SequencedFakeLLM(
        answers=[
            "The Enterprise package costs $5,000 [Product-3].",
            "Yes, Enterprise at $5,000 includes SLA support.",
        ]
    )
    test_agent = BasicAgent(
        graph=create_agent_graph(llm=fake_llm, mcp_client=mock_mcp, checkpointer=checkpointer),
        mcp_client=mock_mcp,
        checkpointer=checkpointer,
    )

    app.dependency_overrides[get_agent] = lambda: test_agent
    client = TestClient(app)
    try:
        res1 = client.post("/query", json={"query": "What is the Enterprise package price?"})
        assert res1.status_code == 200
        body1 = res1.json()
        assert "[Product-3]" in body1["answer"]
        assert isinstance(body1.get("thread_id"), str) and len(body1["thread_id"]) > 0
        generated_thread_id = body1["thread_id"]

        res2 = client.post(
            "/query",
            json={
                "query": "Does that include SLA?",
                "thread_id": generated_thread_id,
            },
        )
        assert res2.status_code == 200
        body2 = res2.json()
        assert body2["thread_id"] == generated_thread_id
        assert "SLA support" in body2["answer"]

        persisted = test_agent.get_thread_state(generated_thread_id)
        assert persisted is not None
        assert len(persisted["messages"]) == 4
    finally:
        app.dependency_overrides.clear()


def test_unreachable_postgres_connection_raises_sanitized_persistence_error() -> None:
    secret_url = "postgresql://admin_user:super_secret_pw_123@127.0.0.1:59999/nonexistent_db"
    manager = PostgresPersistenceManager(database_url=secret_url, connect_timeout=1)

    with pytest.raises(PersistenceError) as exc_info:
        manager.start()

    assert "PostgreSQL connection initialization failed" in str(exc_info.value)
    assert "super_secret_pw_123" not in str(exc_info.value)


def test_checkpointer_failure_during_invoke_maps_to_agent_error() -> None:
    class FailingGraph:
        checkpointer = object()

        def invoke(self, input_data: object, config: object = None) -> object:
            raise PersistenceError("PostgreSQL connection lost mid-checkpoint")

    agent = BasicAgent(graph=FailingGraph())
    with pytest.raises(AgentError, match="PostgreSQL connection lost"):
        agent.query_with_evidence("Hello", thread_id="thread-fail")


def _live_postgres_url() -> str | None:
    url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url or not url.strip():
        return None
    try:
        with PostgresPersistenceManager(database_url=url.strip(), connect_timeout=2) as _:
            return url.strip()
    except Exception:
        return None


def test_live_postgres_saver_end_to_end_persistence_and_isolation() -> None:
    db_url = _live_postgres_url()
    if not db_url:
        pytest.skip("No reachable PostgreSQL instance configured via TEST_DATABASE_URL or DATABASE_URL.")

    mock_mcp = MagicMock()
    mock_mcp.execute_query_sync.return_value = [
        {"id": 3, "name": "Enterprise package", "price": 5000.0, "category": "Subscriptions"}
    ]
    thread_a = f"pg-live-a-{uuid.uuid4()}"
    thread_b = f"pg-live-b-{uuid.uuid4()}"

    with PostgresPersistenceManager(database_url=db_url) as checkpointer_1:
        llm_1 = SequencedFakeLLM(
            answers=[
                "The Enterprise package costs $5,000 [Product-3].",
                "Thread B independent response.",
            ]
        )
        agent_1 = BasicAgent(
            graph=create_agent_graph(llm=llm_1, mcp_client=mock_mcp, checkpointer=checkpointer_1),
            mcp_client=mock_mcp,
            checkpointer=checkpointer_1,
        )
        ans_a1, _ = agent_1.query_with_evidence(
            "What is the price of the Enterprise package?",
            thread_id=thread_a,
        )
        assert "[Product-3]" in ans_a1
        agent_1.query_with_evidence("Hello from Thread B", thread_id=thread_b)

    with PostgresPersistenceManager(database_url=db_url) as checkpointer_2:
        llm_2 = SequencedFakeLLM(answers=["Continuing Thread A from PostgreSQL checkpoint."])
        agent_2 = BasicAgent(
            graph=create_agent_graph(llm=llm_2, mcp_client=mock_mcp, checkpointer=checkpointer_2),
            mcp_client=mock_mcp,
            checkpointer=checkpointer_2,
        )
        ans_a2, _ = agent_2.query_with_evidence(
            "What did I just ask you in Turn 1?",
            thread_id=thread_a,
        )
        assert ans_a2 == "Continuing Thread A from PostgreSQL checkpoint."

        resumed_prompt_messages = "\n".join(str(getattr(m, "content", m)) for m in llm_2.inputs[0])
        assert "What is the price of the Enterprise package?" in resumed_prompt_messages
        assert "The Enterprise package costs $5,000 [Product-3]." in resumed_prompt_messages
        assert "Thread B" not in resumed_prompt_messages

        state_a = agent_2.get_thread_state(thread_a)
        state_b = agent_2.get_thread_state(thread_b)
        assert state_a is not None and len(state_a["messages"]) == 4
        assert state_b is not None and len(state_b["messages"]) == 2
