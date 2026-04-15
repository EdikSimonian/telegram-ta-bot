"""Retrieval-augmented generation over course docs.

Pipeline:
    /doc add  → chunk_text → embed(passage) → Vector.upsert → Redis ta:docs
    student Q → embed(query) → Vector.query(top_k, namespace) → filter by score
               → concat chunkText blocks → passed to ai.ask_ai as context

OpenAI ``text-embedding-3-small`` emits 1536-dim vectors. The Upstash
Vector index must be created with the same dimension + cosine metric.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

from bot.clients import embeddings_client, vector_index
from bot.config import (
    EMBEDDINGS_MODEL,
    RAG_CHUNK_OVERLAP,
    RAG_CHUNK_SIZE,
    RAG_MIN_SCORE,
    RAG_TOP_K,
    VECTOR_NAMESPACE,
)


# ── Slug ──────────────────────────────────────────────────────────────────
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    """Stable, URL-safe slug from a human title. Empty titles → hash fallback."""
    base = _SLUG_RE.sub("-", (title or "").lower()).strip("-")
    if base:
        return base[:60]
    return hashlib.sha1((title or "").encode("utf-8")).hexdigest()[:12]


# ── Chunking ──────────────────────────────────────────────────────────────
def chunk_text(
    text: str,
    chunk_size: int = RAG_CHUNK_SIZE,
    overlap: int = RAG_CHUNK_OVERLAP,
) -> list[str]:
    """Split ``text`` into overlapping character windows.

    Exact spec §5.8: 800-char windows, 100-char overlap. Short inputs
    return a single chunk. Trailing whitespace-only chunks are dropped.
    """
    if not text:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be 0 <= overlap < chunk_size")

    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    step = chunk_size - overlap
    for start in range(0, len(text), step):
        piece = text[start : start + chunk_size].strip()
        if piece:
            chunks.append(piece)
        if start + chunk_size >= len(text):
            break
    return chunks


# ── Embeddings ────────────────────────────────────────────────────────────
def embed(text: str) -> list[float] | None:
    """Single-shot embedding. Returns None on API failure."""
    if embeddings_client is None or not text.strip():
        return None
    try:
        resp = embeddings_client.embeddings.create(
            model=EMBEDDINGS_MODEL, input=text,
        )
        return list(resp.data[0].embedding)
    except Exception as e:
        print(f"[rag] embed error: {e}")
        return None


def embed_many(texts: list[str]) -> list[list[float]]:
    """Batch-embed a list of strings. Preserves input order; drops nothing."""
    if embeddings_client is None or not texts:
        return []
    try:
        resp = embeddings_client.embeddings.create(
            model=EMBEDDINGS_MODEL, input=texts,
        )
        # OpenAI returns data in input order, each with `.embedding`
        return [list(d.embedding) for d in resp.data]
    except Exception as e:
        print(f"[rag] embed_many error: {e}")
        return []


# ── Vector ops ────────────────────────────────────────────────────────────
def upsert_doc(
    slug: str,
    title: str,
    text: str,
    *,
    blob_url: str | None = None,
    added_by: str | None = None,
) -> int:
    """Embed ``text`` in chunks and upsert into the vector index.

    Returns the number of chunks written (0 on failure or when vector is
    unconfigured).
    """
    if vector_index is None:
        print("[rag] vector_index unset — skipping upsert_doc")
        return 0
    chunks = chunk_text(text)
    if not chunks:
        return 0
    vectors = embed_many(chunks)
    if len(vectors) != len(chunks):
        print(f"[rag] embed_many returned {len(vectors)} for {len(chunks)} chunks")
        return 0
    payload = []
    for idx, (vec, chunk) in enumerate(zip(vectors, chunks)):
        payload.append({
            "id": f"{slug}-{idx}",
            "vector": vec,
            "metadata": {
                "slug": slug,
                "title": title,
                "chunkIdx": idx,
                "chunkText": chunk,
                "blobUrl": blob_url or "",
                "addedBy": added_by or "",
            },
        })
    try:
        vector_index.upsert(vectors=payload, namespace=VECTOR_NAMESPACE)
        return len(payload)
    except Exception as e:
        print(f"[rag] upsert error: {e}")
        return 0


def delete_doc(slug: str, chunk_count: int) -> bool:
    """Remove all chunk vectors for a doc. Best-effort; returns False on error."""
    if vector_index is None:
        return False
    ids = [f"{slug}-{i}" for i in range(chunk_count)]
    try:
        vector_index.delete(ids=ids, namespace=VECTOR_NAMESPACE)
        return True
    except Exception as e:
        print(f"[rag] delete error: {e}")
        return False


def retrieve(
    question: str,
    top_k: int = RAG_TOP_K,
    min_score: float = RAG_MIN_SCORE,
) -> list[dict]:
    """Embed the question and return matching chunks above the score floor.

    Return format: ``[{"title", "chunkText", "blobUrl", "score"}]``.
    """
    if vector_index is None or not question.strip():
        return []
    vec = embed(question)
    if vec is None:
        return []
    try:
        results = vector_index.query(
            vector=vec,
            top_k=top_k,
            include_metadata=True,
            namespace=VECTOR_NAMESPACE,
        )
    except Exception as e:
        print(f"[rag] query error: {e}")
        return []

    matches: list[dict] = []
    for r in results or []:
        score = float(getattr(r, "score", 0) or 0)
        if score < min_score:
            continue
        meta = getattr(r, "metadata", None) or {}
        matches.append({
            "title":     meta.get("title", ""),
            "chunkText": meta.get("chunkText", ""),
            "blobUrl":   meta.get("blobUrl", ""),
            "score":     score,
        })
    return matches


def format_context(matches: Iterable[dict]) -> str:
    """Render retrieved chunks as an LLM-friendly context block.

    Empty iterable → empty string so callers can ``if context:`` cheaply.
    """
    blocks = []
    for m in matches:
        title = m.get("title") or "Untitled"
        text = (m.get("chunkText") or "").strip()
        if not text:
            continue
        blocks.append(f"[{title}]\n{text}")
    return "\n\n---\n\n".join(blocks)
