"""Multi-tenant pgvector + PostgreSQL FTS hybrid RAG package."""
from __future__ import annotations

from app.rag.chunker import chunk_text
from app.rag.embeddings import EMBEDDING_DIM, embed_texts
from app.rag.hybrid_search import (
    delete_user_provider_chunks,
    hybrid_search_chunks,
    ingest_connector_records,
    reciprocal_rank_fusion,
)

__all__ = [
    "EMBEDDING_DIM",
    "chunk_text",
    "delete_user_provider_chunks",
    "embed_texts",
    "hybrid_search_chunks",
    "ingest_connector_records",
    "reciprocal_rank_fusion",
]
