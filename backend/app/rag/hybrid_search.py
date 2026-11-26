"""Multi-tenant pgvector + PostgreSQL FTS/BM25 hybrid search & ingestion.

Security invariant:
  Every single database read, write, and delete MUST validate a non-empty
  `user_id` and bind `WHERE user_id = :user_id` via parameterized SQL/ORM.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
import json
import logging
from typing import Any
import uuid

from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentChunk
from app.rag.chunker import chunk_text
from app.rag.embeddings import EMBEDDING_DIM, embed_texts

logger = logging.getLogger(__name__)

EmbedFn = Callable[[Sequence[str]], Awaitable[list[list[float] | None]]]


def _require_user_id(user_id: str) -> str:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("Multi-tenant RAG queries require a non-empty user_id.")
    return user_id.strip()


def _format_pgvector_literal(vec: Sequence[float]) -> str:
    if len(vec) != EMBEDDING_DIM:
        raise ValueError(f"Expected {EMBEDDING_DIM}-dim vector, got {len(vec)}")
    return "[" + ",".join(f"{float(v):.8f}" for v in vec) + "]"


def _normalize_record_for_chunking(provider: str, record: dict[str, Any]) -> dict[str, Any] | None:
    """Extract canonical external_id, citation_key, title, url, body, and metadata."""
    prov = provider.strip().lower()
    if prov == "notion":
        ext_id = str(record.get("page_id") or record.get("external_id") or "").strip()
        title = str(record.get("title") or "(untitled)").strip()
        body = str(record.get("excerpt") or record.get("content") or "").strip()
        citation_key = str(record.get("citation_key") or f"Notion-{ext_id.replace('-', '')[:8]}")
        url = record.get("url")
        metadata = {
            "page_id": ext_id,
            "last_edited": record.get("last_edited", ""),
        }
    elif prov == "gmail":
        ext_id = str(record.get("message_id") or record.get("external_id") or "").strip()
        title = str(record.get("subject") or record.get("title") or "(no subject)").strip()
        sender = str(record.get("sender") or "").strip()
        snippet = str(record.get("snippet") or record.get("content") or "").strip()
        body = f"From: {sender}\n{snippet}".strip() if sender else snippet
        citation_key = str(record.get("citation_key") or f"Gmail-{ext_id[:12]}")
        url = record.get("url")
        metadata = {
            "message_id": ext_id,
            "thread_id": record.get("thread_id", ""),
            "sender": sender,
            "date": record.get("date", ""),
        }
    else:
        ext_id = str(
            record.get("external_id")
            or record.get("id")
            or record.get("number")
            or ""
        ).strip()
        title = str(record.get("title") or record.get("subject") or "").strip()
        body = str(
            record.get("body_excerpt")
            or record.get("excerpt")
            or record.get("snippet")
            or record.get("content")
            or ""
        ).strip()
        citation_key = str(record.get("citation_key") or f"{prov.capitalize()}-{ext_id[:12]}")
        url = record.get("url")
        metadata = {
            k: v
            for k, v in record.items()
            if k not in {"chunk_text", "content", "embedding"}
        }

    combined = f"{title}\n{body}".strip()
    if not ext_id or not combined:
        return None

    return {
        "external_id": ext_id,
        "citation_key": citation_key,
        "title": title,
        "url": str(url) if url else None,
        "text": body or title,
        "metadata_json": metadata,
    }


async def ingest_connector_records(
    db: AsyncSession,
    *,
    user_id: str,
    provider: str,
    records: Sequence[dict[str, Any]],
    embed_fn: EmbedFn = embed_texts,
) -> int:
    """Chunk, embed, and upsert Notion/Gmail records into `document_chunks` for *user_id*."""
    scoped_uid = _require_user_id(user_id)
    prov = provider.strip().lower()
    if not records:
        return 0

    staged_rows: list[dict[str, Any]] = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        norm = _normalize_record_for_chunking(prov, raw)
        if norm is None:
            continue
        pieces = chunk_text(norm["text"])
        if not pieces:
            pieces = [norm["title"]]
        for idx, piece in enumerate(pieces):
            staged_rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "user_id": scoped_uid,
                    "provider": prov,
                    "external_id": norm["external_id"],
                    "chunk_index": idx,
                    "citation_key": norm["citation_key"],
                    "title": norm["title"],
                    "url": norm["url"],
                    "chunk_text": piece,
                    "metadata_json": norm["metadata_json"],
                }
            )

    if not staged_rows:
        return 0

    embed_inputs = [f"{r['title']}\n{r['chunk_text']}".strip() for r in staged_rows]
    vectors = await embed_fn(embed_inputs)
    now = datetime.now(timezone.utc)

    for idx, row in enumerate(staged_rows):
        vec = vectors[idx] if idx < len(vectors) else None
        row["embedding"] = vec
        row["updated_at"] = now

    stmt = pg_insert(DocumentChunk).values(staged_rows)
    upsert_stmt = stmt.on_conflict_do_update(
        constraint="uq_doc_chunks_user_provider_ext_idx",
        set_={
            "citation_key": stmt.excluded.citation_key,
            "title": stmt.excluded.title,
            "url": stmt.excluded.url,
            "chunk_text": stmt.excluded.chunk_text,
            "metadata_json": stmt.excluded.metadata_json,
            "embedding": stmt.excluded.embedding,
            "updated_at": now,
        },
    )
    await db.execute(upsert_stmt)
    return len(staged_rows)


async def delete_user_provider_chunks(
    db: AsyncSession,
    *,
    user_id: str,
    provider: str,
) -> int:
    """Delete all indexed `document_chunks` belonging strictly to *(user_id, provider)*."""
    scoped_uid = _require_user_id(user_id)
    prov = provider.strip().lower()
    stmt = delete(DocumentChunk).where(
        DocumentChunk.user_id == scoped_uid,
        DocumentChunk.provider == prov,
    )
    res = await db.execute(stmt)
    rowcount = getattr(res, "rowcount", 0)
    return int(rowcount) if isinstance(rowcount, int) and rowcount >= 0 else 0


def reciprocal_rank_fusion(
    semantic_rows: Sequence[dict[str, Any]],
    lexical_rows: Sequence[dict[str, Any]],
    *,
    rrf_k: int = 60,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    """Combine semantic (`pgvector`) and lexical (`ts_rank_cd`) ranked lists via RRF."""
    scores: dict[str, float] = {}
    merged_by_key: dict[str, dict[str, Any]] = {}

    for rank, row in enumerate(semantic_rows, start=1):
        key = str(row.get("citation_key") or row.get("id"))
        scores[key] = scores.get(key, 0.0) + (1.0 / (rrf_k + rank))
        merged_by_key.setdefault(key, dict(row))

    for rank, row in enumerate(lexical_rows, start=1):
        key = str(row.get("citation_key") or row.get("id"))
        scores[key] = scores.get(key, 0.0) + (1.0 / (rrf_k + rank))
        if key not in merged_by_key:
            merged_by_key[key] = dict(row)

    ranked_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)[:top_k]
    fused: list[dict[str, Any]] = []
    for key in ranked_keys:
        item = dict(merged_by_key[key])
        item["rrf_score"] = round(scores[key], 6)
        fused.append(item)
    return fused


def _chunk_row_to_evidence(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a `document_chunks` SQL row into Dorothy's unified citation record."""
    provider = str(row.get("provider") or "")
    raw_meta = row.get("metadata_json") or {}
    if isinstance(raw_meta, str):
        try:
            meta = json.loads(raw_meta)
        except json.JSONDecodeError:
            meta = {}
    elif isinstance(raw_meta, dict):
        meta = raw_meta
    else:
        meta = {}

    chunk_txt = str(row.get("chunk_text") or "")
    title = str(row.get("title") or "")
    citation_key = str(row.get("citation_key") or "")
    url = row.get("url")

    if provider == "gmail":
        return {
            "source": "gmail",
            "citation_key": citation_key,
            "message_id": meta.get("message_id") or row.get("external_id", ""),
            "thread_id": meta.get("thread_id", ""),
            "subject": title,
            "sender": meta.get("sender", ""),
            "date": meta.get("date", ""),
            "snippet": chunk_txt,
            "url": url or "",
        }
    if provider == "notion":
        return {
            "source": "notion",
            "citation_key": citation_key,
            "page_id": meta.get("page_id") or row.get("external_id", ""),
            "title": title,
            "last_edited": meta.get("last_edited", ""),
            "excerpt": chunk_txt,
            "url": url or "",
        }
    return {
        "source": provider,
        "citation_key": citation_key,
        "external_id": row.get("external_id", ""),
        "title": title,
        "excerpt": chunk_txt,
        "url": url or "",
    }


async def hybrid_search_chunks(
    db: AsyncSession,
    *,
    user_id: str,
    query: str,
    providers: Sequence[str] | None = None,
    top_k: int = 8,
    rrf_k: int = 60,
    embed_fn: EmbedFn = embed_texts,
) -> list[dict[str, Any]]:
    """Execute multi-tenant semantic (`pgvector`) + BM25/FTS (`tsvector`) hybrid search.

    Always enforces `WHERE user_id = :user_id` on both retrieval legs.
    """
    scoped_uid = _require_user_id(user_id)
    cleaned_query = (query or "").strip()
    if not cleaned_query or top_k <= 0:
        return []

    provider_list = [p.strip().lower() for p in providers if p and p.strip()] if providers else []
    provider_clause = "AND provider = ANY(:providers)" if provider_list else ""
    candidate_limit = max(top_k * 3, 20)

    base_params: dict[str, Any] = {
        "user_id": scoped_uid,
        "limit": candidate_limit,
    }
    if provider_list:
        base_params["providers"] = provider_list

    # 1. Semantic pgvector leg (skipped gracefully if embeddings unavailable)
    semantic_rows: list[dict[str, Any]] = []
    vectors = await embed_fn([cleaned_query])
    query_vec = vectors[0] if vectors else None
    if query_vec is not None:
        sem_sql = text(
            f"""
            SELECT id, provider, external_id, citation_key, title, url, chunk_text, metadata_json,
                   1 - (embedding <=> CAST(:query_vec AS vector)) AS semantic_score
            FROM document_chunks
            WHERE user_id = :user_id
              AND embedding IS NOT NULL
              {provider_clause}
            ORDER BY embedding <=> CAST(:query_vec AS vector) ASC
            LIMIT :limit
            """
        )
        sem_res = await db.execute(
            sem_sql,
            {**base_params, "query_vec": _format_pgvector_literal(query_vec)},
        )
        semantic_rows = [dict(r) for r in sem_res.mappings().all()]

    # 2. Lexical PostgreSQL FTS / BM25-style leg (ts_rank_cd over generated tsvector)
    lex_sql = text(
        f"""
        SELECT id, provider, external_id, citation_key, title, url, chunk_text, metadata_json,
               ts_rank_cd(tsv, websearch_to_tsquery('english', :query)) AS lexical_score
        FROM document_chunks
        WHERE user_id = :user_id
          AND tsv @@ websearch_to_tsquery('english', :query)
          {provider_clause}
        ORDER BY lexical_score DESC
        LIMIT :limit
        """
    )
    lex_res = await db.execute(lex_sql, {**base_params, "query": cleaned_query})
    lexical_rows = [dict(r) for r in lex_res.mappings().all()]

    fused_rows = reciprocal_rank_fusion(
        semantic_rows,
        lexical_rows,
        rrf_k=rrf_k,
        top_k=top_k,
    )

    results: list[dict[str, Any]] = []
    for row in fused_rows:
        ev = _chunk_row_to_evidence(row)
        ev["rrf_score"] = row["rrf_score"]
        results.append(ev)
    return results
