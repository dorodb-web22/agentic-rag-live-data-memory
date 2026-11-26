"""Paragraph & sentence-aware sliding window text chunker for Notion & Gmail."""
from __future__ import annotations

import re

DEFAULT_MAX_CHARS = 1000
DEFAULT_OVERLAP_CHARS = 150
MAX_CHUNKS_PER_DOCUMENT = 32


def chunk_text(
    text: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP_CHARS,
    max_chunks: int = MAX_CHUNKS_PER_DOCUMENT,
) -> list[str]:
    """Split *text* into bounded overlapping chunks while preserving readability."""
    if not isinstance(text, str):
        return []
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    effective_overlap = max(0, min(overlap, max_chars // 2))

    if len(cleaned) <= max_chars:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    length = len(cleaned)

    while start < length and len(chunks) < max_chunks:
        end = min(start + max_chars, length)
        if end < length:
            # Prefer breaking at a sentence or word boundary in the second half of the window
            window = cleaned[start:end]
            half = max_chars // 2
            boundary = max(
                window.rfind(". ", half),
                window.rfind("? ", half),
                window.rfind("! ", half),
                window.rfind("; ", half),
                window.rfind(" ", half),
            )
            if boundary > 0:
                end = start + boundary + 1

        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)

        if end >= length:
            break
        next_start = end - effective_overlap
        start = next_start if next_start > start else end

    return chunks
