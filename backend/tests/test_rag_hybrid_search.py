"""Sprint 3 — Offline unit & tenant-isolation tests for pgvector + BM25 hybrid RAG."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.chunker import chunk_text
from app.rag.embeddings import EMBEDDING_DIM, embed_texts
from app.rag.hybrid_search import (
    delete_user_provider_chunks,
    hybrid_search_chunks,
    ingest_connector_records,
    reciprocal_rank_fusion,
)


def test_chunk_text_splits_long_text_with_overlap() -> None:
    sentence = "Enterprise tier includes dedicated SSO and audit logging. "
    long_doc = sentence * 40
    chunks = chunk_text(long_doc, max_chars=300, overlap=60)
    assert len(chunks) >= 6
    assert all(0 < len(c) <= 300 for c in chunks)
    assert chunks[0].startswith("Enterprise tier")


def test_chunk_text_handles_empty_and_short_inputs() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\t  ") == []
    assert chunk_text("Short note", max_chars=500) == ["Short note"]


@pytest.mark.asyncio
async def test_embed_texts_returns_none_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    res = await embed_texts(["hello world", "roadmap q4"])
    assert res == [None, None]


@pytest.mark.asyncio
async def test_embed_texts_parses_vectors_and_degrades_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    fake_vec = [0.01] * EMBEDDING_DIM

    ok_resp = MagicMock()
    ok_resp.raise_for_status = MagicMock()
    ok_resp.json.return_value = {
        "data": [{"index": 0, "embedding": fake_vec}],
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=ok_resp)

    vectors = await embed_texts(["quarter four roadmap"], client=mock_client)
    assert len(vectors) == 1
    assert vectors[0] is not None
    assert len(vectors[0]) == EMBEDDING_DIM

    # Simulate upstream error -> graceful fallback to [None]
    mock_client.post = AsyncMock(side_effect=RuntimeError("upstream timeout"))
    fallback = await embed_texts(["quarter four roadmap"], client=mock_client)
    assert fallback == [None]


def test_reciprocal_rank_fusion_boosts_consensus_hits() -> None:
    sem = [
        {"citation_key": "Notion-aaa11111", "provider": "notion", "title": "Q4 Roadmap", "chunk_text": "Launch v2"},
        {"citation_key": "Notion-bbb22222", "provider": "notion", "title": "Hiring Plan", "chunk_text": "Backend roles"},
    ]
    lex = [
        {"citation_key": "Notion-bbb22222", "provider": "notion", "title": "Hiring Plan", "chunk_text": "Backend roles"},
        {"citation_key": "Gmail-msg999", "provider": "gmail", "title": "Invoice", "chunk_text": "Due Friday"},
    ]
    fused = reciprocal_rank_fusion(sem, lex, rrf_k=60, top_k=3)
    assert len(fused) == 3
    # Notion-bbb22222 appears in BOTH semantic and lexical results -> highest RRF score
    assert fused[0]["citation_key"] == "Notion-bbb22222"
    assert fused[0]["rrf_score"] > fused[1]["rrf_score"]


@pytest.mark.asyncio
async def test_hybrid_search_enforces_user_id_isolation() -> None:
    """Verify SQL statements strictly bind user_id and reject empty user_id."""
    db = AsyncMock()

    with pytest.raises(ValueError, match="user_id"):
        await hybrid_search_chunks(db, user_id="   ", query="roadmap")

    captured_calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_execute(stmt: Any, params: dict[str, Any] | None = None) -> Any:
        sql_str = str(stmt)
        captured_calls.append((sql_str, dict(params or {})))
        mappings_mock = MagicMock()
        if "semantic_score" in sql_str:
            mappings_mock.all.return_value = [
                {
                    "id": "chunk-1",
                    "provider": "notion",
                    "external_id": "page-12345678",
                    "citation_key": "Notion-page1234",
                    "title": "Architecture Spec",
                    "url": "https://notion.so/page-12345678",
                    "chunk_text": "Multi-tenant pgvector isolation design",
                    "metadata_json": {"page_id": "page-12345678", "last_edited": "2026-11-26"},
                }
            ]
        else:
            mappings_mock.all.return_value = [
                {
                    "id": "chunk-2",
                    "provider": "gmail",
                    "external_id": "msg_abc123",
                    "citation_key": "Gmail-msg_abc123",
                    "title": "Deadline Reminder",
                    "url": "https://mail.google.com/mail/u/0/#inbox/msg_abc123",
                    "chunk_text": "From: lead@acme.io\nSprint 3 deploy is Friday",
                    "metadata_json": {
                        "message_id": "msg_abc123",
                        "thread_id": "th_1",
                        "sender": "lead@acme.io",
                        "date": "Thu, 26 Nov 2026",
                    },
                }
            ]
        res = MagicMock()
        res.mappings.return_value = mappings_mock
        return res

    db.execute = AsyncMock(side_effect=fake_execute)

    async def fake_embed(texts: Any) -> list[list[float] | None]:
        return [[0.02] * EMBEDDING_DIM for _ in texts]

    results = await hybrid_search_chunks(
        db,
        user_id="tenant-user-alpha",
        query="pgvector deploy",
        providers=["notion", "gmail"],
        top_k=5,
        embed_fn=fake_embed,
    )

    assert len(captured_calls) == 2
    for sql_text, bound_params in captured_calls:
        assert "WHERE user_id = :user_id" in sql_text
        assert bound_params["user_id"] == "tenant-user-alpha"
        assert bound_params["providers"] == ["notion", "gmail"]

    keys = {r["citation_key"] for r in results}
    assert keys == {"Notion-page1234", "Gmail-msg_abc123"}


@pytest.mark.asyncio
async def test_ingest_and_delete_chunks_scoped_by_user_id() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=2))

    async def fake_embed(texts: Any) -> list[list[float] | None]:
        return [[0.05] * EMBEDDING_DIM for _ in texts]

    count = await ingest_connector_records(
        db,
        user_id="user-111",
        provider="notion",
        records=[
            {
                "source": "notion",
                "citation_key": "Notion-deadbeef",
                "page_id": "deadbeef-1234",
                "title": "Security Checklist",
                "last_edited": "2026-11-26",
                "excerpt": "All queries must filter by user_id.",
                "url": "https://notion.so/deadbeef",
            }
        ],
        embed_fn=fake_embed,
    )
    assert count == 1
    assert db.execute.await_count == 1

    deleted = await delete_user_provider_chunks(
        db,
        user_id="user-111",
        provider="notion",
    )
    assert deleted == 2

    with pytest.raises(ValueError, match="user_id"):
        await delete_user_provider_chunks(db, user_id="", provider="notion")
