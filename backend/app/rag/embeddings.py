"""Async embedding client with explicit timeouts and graceful degradation."""
from __future__ import annotations

import logging
import os
from typing import Sequence

import httpx

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_URL = "https://api.openai.com/v1/embeddings"
EMBEDDING_TIMEOUT_SECONDS = 10.0


async def embed_texts(
    texts: Sequence[str],
    *,
    client: httpx.AsyncClient | None = None,
) -> list[list[float] | None]:
    """Compute embeddings for *texts* via OpenAI-compatible embeddings API.

    If `OPENAI_API_KEY` (or `EMBEDDING_API_KEY`) is not configured or the upstream
    call fails/times out, logs a sanitized warning and returns `[None, ...]` so
    PostgreSQL lexical BM25/FTS ingestion and search continue without failing.
    """
    if not texts:
        return []

    api_key = (
        os.getenv("EMBEDDING_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()
    if not api_key:
        return [None for _ in texts]

    model = os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip() or DEFAULT_EMBEDDING_MODEL
    url = os.getenv("EMBEDDING_API_URL", DEFAULT_EMBEDDING_URL).strip() or DEFAULT_EMBEDDING_URL
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "input": list(texts),
        "dimensions": EMBEDDING_DIM,
    }

    async def _post(http_client: httpx.AsyncClient) -> list[list[float] | None]:
        resp = await http_client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data", [])
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        vectors: list[list[float] | None] = []
        for idx in range(len(texts)):
            vec = ordered[idx].get("embedding") if idx < len(ordered) else None
            if isinstance(vec, list) and len(vec) == EMBEDDING_DIM:
                vectors.append([float(v) for v in vec])
            else:
                vectors.append(None)
        return vectors

    try:
        if client is not None:
            return await _post(client)
        async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT_SECONDS) as owned_client:
            return await _post(owned_client)
    except Exception as exc:
        logger.warning("Embedding generation unavailable (%s); falling back to lexical FTS", type(exc).__name__)
        return [None for _ in texts]
