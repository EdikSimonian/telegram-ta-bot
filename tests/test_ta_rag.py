"""RAG pipeline: chunking, embeddings, vector query, score filter."""
from unittest.mock import MagicMock, patch


# ── Chunking ──────────────────────────────────────────────────────────────
def test_chunk_short_text_is_single_chunk():
    from bot.ta.rag import chunk_text
    assert chunk_text("hello world") == ["hello world"]


def test_chunk_empty_text_is_empty():
    from bot.ta.rag import chunk_text
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_exact_boundary_size_is_single_chunk():
    from bot.ta.rag import chunk_text
    text = "x" * 800
    assert chunk_text(text, chunk_size=800, overlap=100) == [text]


def test_chunk_over_boundary_splits_with_overlap():
    from bot.ta.rag import chunk_text
    # 1500 chars → chunks at [0:800], [700:1500] (step = 700)
    text = "".join(str(i % 10) for i in range(1500))
    chunks = chunk_text(text, chunk_size=800, overlap=100)
    assert len(chunks) == 2
    assert len(chunks[0]) == 800
    # Overlap of last 100 chars of chunk 0 with first 100 of chunk 1
    assert chunks[0][-100:] == chunks[1][:100]


def test_chunk_rejects_bad_overlap():
    from bot.ta.rag import chunk_text
    import pytest
    with pytest.raises(ValueError):
        chunk_text("x" * 100, chunk_size=50, overlap=50)
    with pytest.raises(ValueError):
        chunk_text("x" * 100, chunk_size=50, overlap=-1)


# ── slugify ───────────────────────────────────────────────────────────────
def test_slugify_basic():
    from bot.ta.rag import slugify
    assert slugify("CS 101 — Intro to Python") == "cs-101-intro-to-python"


def test_slugify_empty_falls_back_to_hash():
    from bot.ta.rag import slugify
    out = slugify("")
    assert out and out.isalnum()


# ── embed ─────────────────────────────────────────────────────────────────
def test_embed_calls_openai():
    with patch("bot.ta.rag.embeddings_client") as mock_client:
        mock_client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[0.1] * 1536)]
        )
        from bot.ta.rag import embed
        out = embed("hello")
        assert out == [0.1] * 1536
        mock_client.embeddings.create.assert_called_once()


def test_embed_empty_text_returns_none():
    with patch("bot.ta.rag.embeddings_client") as mock_client:
        from bot.ta.rag import embed
        assert embed("") is None
        assert embed("   ") is None
        mock_client.embeddings.create.assert_not_called()


def test_embed_handles_api_failure():
    with patch("bot.ta.rag.embeddings_client") as mock_client:
        mock_client.embeddings.create.side_effect = Exception("rate limit")
        from bot.ta.rag import embed
        assert embed("hello") is None


# ── embed_many batch order ────────────────────────────────────────────────
def test_embed_many_preserves_input_order():
    with patch("bot.ta.rag.embeddings_client") as mock_client:
        mock_client.embeddings.create.return_value = MagicMock(
            data=[
                MagicMock(embedding=[1.0]),
                MagicMock(embedding=[2.0]),
                MagicMock(embedding=[3.0]),
            ]
        )
        from bot.ta.rag import embed_many
        out = embed_many(["a", "b", "c"])
        assert out == [[1.0], [2.0], [3.0]]


# ── upsert_doc ────────────────────────────────────────────────────────────
def test_upsert_doc_skipped_when_no_vector_index():
    with patch("bot.ta.rag.vector_index", None):
        from bot.ta.rag import upsert_doc
        assert upsert_doc("s", "title", "some text") == 0


def test_upsert_doc_embeds_and_upserts_with_namespace():
    with patch("bot.ta.rag.vector_index") as vi, \
         patch("bot.ta.rag.embed_many", return_value=[[0.1], [0.2]]), \
         patch("bot.ta.rag.chunk_text", return_value=["chunk1", "chunk2"]), \
         patch("bot.ta.rag.VECTOR_NAMESPACE", "test"):
        from bot.ta.rag import upsert_doc
        n = upsert_doc("cs101", "CS101", "text", blob_url="https://blob/...", added_by="alice")
        assert n == 2
        call = vi.upsert.call_args
        assert call.kwargs["namespace"] == "test"
        payload = call.kwargs["vectors"]
        assert len(payload) == 2
        assert payload[0]["id"] == "cs101-0"
        assert payload[0]["metadata"]["title"] == "CS101"
        assert payload[0]["metadata"]["chunkText"] == "chunk1"


def test_upsert_doc_bails_when_embed_count_mismatches():
    with patch("bot.ta.rag.vector_index") as vi, \
         patch("bot.ta.rag.embed_many", return_value=[[0.1]]), \
         patch("bot.ta.rag.chunk_text", return_value=["chunk1", "chunk2"]):
        from bot.ta.rag import upsert_doc
        assert upsert_doc("s", "t", "text") == 0
        vi.upsert.assert_not_called()


# ── delete_doc ────────────────────────────────────────────────────────────
def test_delete_doc_deletes_all_chunk_ids_in_namespace():
    with patch("bot.ta.rag.vector_index") as vi, \
         patch("bot.ta.rag.VECTOR_NAMESPACE", "prod"):
        from bot.ta.rag import delete_doc
        assert delete_doc("cs101", 3) is True
        vi.delete.assert_called_once_with(
            ids=["cs101-0", "cs101-1", "cs101-2"], namespace="prod",
        )


# ── retrieve ──────────────────────────────────────────────────────────────
def test_retrieve_returns_nothing_when_no_vector_index():
    with patch("bot.ta.rag.vector_index", None):
        from bot.ta.rag import retrieve
        assert retrieve("q") == []


def test_retrieve_filters_below_threshold():
    r1 = MagicMock(score=0.8, metadata={"title": "A", "chunkText": "aaa"})
    r2 = MagicMock(score=0.5, metadata={"title": "B", "chunkText": "bbb"})
    r3 = MagicMock(score=0.75, metadata={"title": "C", "chunkText": "ccc"})
    with patch("bot.ta.rag.vector_index") as vi, \
         patch("bot.ta.rag.embed", return_value=[0.1] * 1536), \
         patch("bot.ta.rag.RAG_MIN_SCORE", 0.6):
        vi.query.return_value = [r1, r2, r3]
        from bot.ta.rag import retrieve
        out = retrieve("what is python")
        titles = {m["title"] for m in out}
        assert titles == {"A", "C"}


def test_retrieve_uses_namespace():
    with patch("bot.ta.rag.vector_index") as vi, \
         patch("bot.ta.rag.embed", return_value=[0.1] * 1536), \
         patch("bot.ta.rag.VECTOR_NAMESPACE", "test"):
        vi.query.return_value = []
        from bot.ta.rag import retrieve
        retrieve("hello")
        assert vi.query.call_args.kwargs["namespace"] == "test"


# ── format_context ────────────────────────────────────────────────────────
def test_format_context_joins_blocks_with_separator():
    from bot.ta.rag import format_context
    matches = [
        {"title": "Intro", "chunkText": "Python is a language."},
        {"title": "NumPy", "chunkText": "Arrays are fast."},
    ]
    out = format_context(matches)
    assert "[Intro]" in out
    assert "Python is a language." in out
    assert "---" in out
    assert "[NumPy]" in out


def test_format_context_empty_input():
    from bot.ta.rag import format_context
    assert format_context([]) == ""
