"""Sprint 2 async multi-tool LangGraph agent & streaming tests."""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import jwt
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
import pytest

os.environ.setdefault("SESSION_SECRET", "s" * 32)
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client.apps.googleusercontent.com")

from app.agent import (  # noqa: E402
    AgentRecursionLimitError,
    BasicAgent,
    _build_citation_index,
    _validate_citations,
    create_dynamic_tool_agent_graph,
    get_agent,
)
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
import app.streaming as streaming_mod  # noqa: E402


def _make_cookie(user_id: str, email: str = "dorothy@example.com") -> str:
    payload = {
        "user_id": user_id,
        "sub": f"sub-{user_id}",
        "email": email,
        "name": "Dorothy",
        "picture": "",
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, os.environ["SESSION_SECRET"], algorithm="HS256")


class ScriptedToolCallingLLM:
    """Deterministic fake LLM supporting bind_tools() and ainvoke()."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self._idx = 0
        self.bound_tool_names: list[str] = []
        self.invocations: list[list[Any]] = []

    def bind_tools(self, tools: list[Any]) -> "ScriptedToolCallingLLM":
        self.bound_tool_names = [t.name for t in tools]
        return self

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        self.invocations.append(list(messages))
        msg = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return msg


# ---------------------------------------------------------------------------
# 1. Generalized Unified Citation Indexing & Validation
# ---------------------------------------------------------------------------


def test_unified_citations_across_github_gmail_notion_and_sqlite() -> None:
    records = [
        {
            "source": "github",
            "number": 42,
            "title": "Fix OAuth callback",
            "state": "open",
            "url": "https://github.com/org/repo/issues/42",
        },
        {
            "source": "gmail",
            "message_id": "18f3a9b2",
            "subject": "Launch checklist",
            "sender": "pm@example.com",
        },
        {
            "source": "notion",
            "page_id": "9b2c1d4e",
            "title": "Q4 Launch Plan",
        },
        {
            "source": "sqlite",
            "table": "orders",
            "row": {"rowid": 7, "customer": "Acme", "total": 12000},
        },
    ]

    idx = _build_citation_index(records)
    assert set(idx.keys()) == {
        "GitHub-42",
        "Gmail-18f3a9b2",
        "Notion-9b2c1d4e",
        "SQL-orders-7",
    }

    raw_answer = (
        "Launch blocker tracked in [GitHub-42] and [Gmail-18f3a9b2], "
        "documented in [Notion-9b2c1d4e] with revenue [SQL-orders-7]. "
        "Fabricated refs [GitHub-999] [Gmail-fake] [Notion-fake] [SQL-orders-999] must vanish."
    )
    cleaned = _validate_citations(raw_answer, records)

    assert "[GitHub-42]" in cleaned
    assert "[Gmail-18f3a9b2]" in cleaned
    assert "[Notion-9b2c1d4e]" in cleaned
    assert "[SQL-orders-7]" in cleaned
    assert "[GitHub-999]" not in cleaned
    assert "[Gmail-fake]" not in cleaned
    assert "[Notion-fake]" not in cleaned
    assert "[SQL-orders-999]" not in cleaned


# ---------------------------------------------------------------------------
# 2. Parallel Multi-Tool Fan-Out via asyncio.gather + Per-User Tool Binding
# ---------------------------------------------------------------------------


def test_parallel_multitool_fanout_executes_concurrently_and_merges_evidence() -> None:
    async def _run() -> None:
        async def search_gmail(query: str) -> list[dict[str, Any]]:
            await asyncio.sleep(0.08)
            return [
                {
                    "source": "gmail",
                    "citation_key": "Gmail-msg01",
                    "message_id": "msg01",
                    "subject": "Launch blocker: SSO redirect",
                    "sender": "lead@example.com",
                    "snippet": "SSO callback needs prod URL",
                    "url": "https://mail.google.com/mail/u/0/#inbox/msg01",
                }
            ]

        async def search_notion(query: str) -> list[dict[str, Any]]:
            await asyncio.sleep(0.08)
            return [
                {
                    "source": "notion",
                    "citation_key": "Notion-pg99",
                    "page_id": "pg99",
                    "title": "Launch Readiness Doc",
                    "excerpt": "SSO is P0 before GA",
                    "url": "https://notion.so/pg99",
                }
            ]

        async def search_github(query: str) -> list[dict[str, Any]]:
            await asyncio.sleep(0.08)
            return [
                {
                    "source": "github",
                    "citation_key": "GitHub-108",
                    "number": 108,
                    "title": "Update production OAuth callback URL",
                    "state": "open",
                    "url": "https://github.com/org/repo/issues/108",
                }
            ]

        user_tools = [
            StructuredTool.from_function(coroutine=search_gmail, name="search_gmail", description="Search Gmail"),
            StructuredTool.from_function(coroutine=search_notion, name="search_notion", description="Search Notion"),
            StructuredTool.from_function(coroutine=search_github, name="search_github", description="Search GitHub"),
        ]

        llm = ScriptedToolCallingLLM(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "tc-1", "name": "search_gmail", "args": {"query": "launch blocker"}},
                        {"id": "tc-2", "name": "search_notion", "args": {"query": "launch blocker"}},
                        {"id": "tc-3", "name": "search_github", "args": {"query": "SSO callback"}},
                    ],
                ),
                AIMessage(
                    content=(
                        "SSO callback is flagged in Gmail [Gmail-msg01], Notion [Notion-pg99], "
                        "and tracked in [GitHub-108] (not [GitHub-999])."
                    )
                ),
            ]
        )

        user_id = str(uuid.uuid4())
        saver = InMemorySaver()
        agent = BasicAgent(llm=llm, async_checkpointer=saver)

        with patch("app.agent.get_user_connectors", new_callable=AsyncMock, return_value=user_tools) as mock_conn:
            t0 = time.perf_counter()
            answer, evidence = await agent.aquery_with_evidence(
                "Check my Gmail and Notion for launch blockers and cross-check open GitHub issues",
                thread_id="thread-fanout-1",
                user_id=user_id,
            )
            elapsed = time.perf_counter() - t0

        mock_conn.assert_awaited_once_with(user_id, db=None)
        assert llm.bound_tool_names == ["search_gmail", "search_notion", "search_github"]
        assert elapsed < 0.21, f"Expected parallel fan-out, took {elapsed:.3f}s"

        assert "[Gmail-msg01]" in answer
        assert "[Notion-pg99]" in answer
        assert "[GitHub-108]" in answer
        assert "[GitHub-999]" not in answer
        assert evidence is not None and len(evidence) == 3

    asyncio.run(_run())


def test_dynamic_agent_enforces_recursion_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_RECURSION_LIMIT", "4")

    async def _run() -> None:
        async def noop_tool(query: str) -> list[dict[str, Any]]:
            return []

        tool = StructuredTool.from_function(coroutine=noop_tool, name="search_github", description="Search")
        looping_msg = AIMessage(
            content="",
            tool_calls=[{"id": "loop-1", "name": "search_github", "args": {"query": "forever"}}],
        )
        llm = ScriptedToolCallingLLM([looping_msg] * 10)
        graph = create_dynamic_tool_agent_graph(llm=llm, tools=[tool])
        agent = BasicAgent(llm=llm)

        with patch("app.agent.get_user_connectors", new_callable=AsyncMock, return_value=[tool]):
            with pytest.raises(AgentRecursionLimitError):
                await agent.aquery_with_evidence("Loop test", user_id="u-loop")
        assert graph is not None

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 3. /api/query/stream SSE Events, Turn Persistence, Keepalive & Disconnect
# ---------------------------------------------------------------------------


def test_api_query_stream_requires_auth() -> None:
    with TestClient(app) as client:
        resp = client.post("/api/query/stream", json={"query": "hello"})
        assert resp.status_code == 401


def test_api_query_stream_astream_events_and_records_turn() -> None:
    user_id = str(uuid.uuid4())
    cookie = _make_cookie(user_id)

    async def search_sqlite(query: str) -> list[dict[str, Any]]:
        return [{"source": "sqlite", "table": "metrics", "row": {"id": 5, "arr": 95000}}]

    tool = StructuredTool.from_function(coroutine=search_sqlite, name="query_sqlite", description="Query DB")
    llm = ScriptedToolCallingLLM(
        [
            AIMessage(
                content="",
                tool_calls=[{"id": "tc-db", "name": "query_sqlite", "args": {"query": "arr"}}],
            ),
            AIMessage(content="Current ARR is $95,000 [SQL-metrics-5]."),
        ]
    )
    test_agent = BasicAgent(llm=llm, async_checkpointer=InMemorySaver())

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    async def fake_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[get_agent] = lambda: test_agent

    try:
        with (
            patch("app.agent.get_user_connectors", new_callable=AsyncMock, return_value=[tool]),
            patch("app.main.record_conversation_turn", new_callable=AsyncMock) as mock_record,
            TestClient(app) as client,
        ):
            client.cookies.set("session", cookie)
            resp = client.post(
                "/api/query/stream",
                json={"query": "What is our ARR?", "thread_id": "thread-arr-1"},
            )

        assert resp.status_code == 200
        assert "event: step" in resp.text
        assert '"node": "tools"' in resp.text
        assert "event: answer" in resp.text
        assert "[SQL-metrics-5]" in resp.text
        assert "event: done" in resp.text

        mock_record.assert_awaited_once()
        kwargs = mock_record.call_args.kwargs
        assert kwargs["user_id"] == user_id
        assert kwargs["thread_id"] == "thread-arr-1"
        assert "[SQL-metrics-5]" in kwargs["assistant_msg"]
        assert kwargs["evidence"][0]["citation_key"] == "SQL-metrics-5"
    finally:
        app.dependency_overrides.clear()


def test_api_query_stream_emits_keepalive_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(streaming_mod, "KEEPALIVE_INTERVAL_SECONDS", 0.04)
    user_id = str(uuid.uuid4())
    cookie = _make_cookie(user_id)

    class SlowAsyncAgent:
        last_run_id = None

        async def astream_with_evidence(self, query: str, thread_id: str | None = None, **kwargs: Any):
            yield {"event": "step", "data": {"node": "planner", "status": "start"}}
            await asyncio.sleep(0.12)
            yield {"event": "step", "data": {"node": "planner", "status": "end"}}
            yield {
                "event": "answer",
                "data": {"answer": "Completed after keepalive.", "evidence": None, "thread_id": thread_id},
            }
            yield {"event": "done", "data": {}}

    async def fake_get_db():
        s = AsyncMock()
        s.commit = AsyncMock()
        yield s

    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[get_agent] = lambda: SlowAsyncAgent()

    try:
        with (
            patch("app.main.record_conversation_turn", new_callable=AsyncMock),
            TestClient(app) as client,
        ):
            client.cookies.set("session", cookie)
            resp = client.post("/api/query/stream", json={"query": "slow query"})

        assert resp.status_code == 200
        assert ": keepalive\n\n" in resp.text
        assert "Completed after keepalive." in resp.text
    finally:
        app.dependency_overrides.clear()


def test_api_query_stream_cancels_inflight_task_on_disconnect() -> None:
    from app.main import api_stream_agent
    from app.schemas import QueryRequest

    async def _run() -> None:
        cancelled_flag = asyncio.Event()

        class CancellableAgent:
            last_run_id = None

            async def astream_with_evidence(self, query: str, thread_id: str | None = None, **kwargs: Any):
                try:
                    yield {"event": "step", "data": {"node": "planner", "status": "start"}}
                    await asyncio.sleep(10.0)
                except asyncio.CancelledError:
                    cancelled_flag.set()
                    raise

        fake_request = MagicMock()
        disconnect_state = {"disconnected": False}

        async def is_disconnected() -> bool:
            return disconnect_state["disconnected"]

        fake_request.is_disconnected = is_disconnected
        mock_db = AsyncMock()

        response = await api_stream_agent(
            payload=QueryRequest(query="cancel me", thread_id="tid-cancel"),
            raw_request=fake_request,
            user={"user_id": str(uuid.uuid4())},
            db=mock_db,
            agent=CancellableAgent(),  # type: ignore[arg-type]
        )

        body_iter = response.body_iterator
        first_chunk = await anext(body_iter)
        assert "planner" in str(first_chunk)

        disconnect_state["disconnected"] = True
        remaining = [chunk async for chunk in body_iter]
        assert remaining == []
        assert cancelled_flag.is_set()

    asyncio.run(_run())
