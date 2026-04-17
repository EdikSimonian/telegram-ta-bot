"""bot/ai.answer() — RAG + group history + model override + prefix."""
from unittest.mock import MagicMock, patch


def _prepared(*, stripped_text="what is python", group_key="-100123",
              is_dm=False, is_mention=False):
    p = MagicMock()
    p.stripped_text = stripped_text
    p.group_key = group_key
    p.user_id = 42
    p.username = "student"
    p.is_dm = is_dm
    p.is_mention = is_mention
    p.is_reply_to_bot = False
    p.is_instructor = False
    p.mentions_other_user = False
    p.reply_to_username = None
    return p


def _mock_ai_response(text="42 is the answer"):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=text))]
    return resp


def test_answer_returns_none_on_empty_input():
    from bot.ai import answer
    p = _prepared(stripped_text="")
    assert answer(p) is None


def test_answer_no_rag_hits_calls_model_without_context():
    with patch("bot.ai.rag.retrieve", return_value=[]), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history") as ah, \
         patch("bot.ai.save_last_group_qa"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response("hello")
        from bot.ai import answer
        out = answer(_prepared())
        assert out.startswith("hello")
        assert "DM me" in out  # group replies get the follow-up nudge
        system_msg = client.chat.completions.create.call_args.kwargs["messages"][0]
        assert system_msg["role"] == "system"
        assert "Course context" not in system_msg["content"]
        assert ah.call_count == 2


def _matches():
    return [
        {"title": "CS101", "chunkText": "Python is a language.", "blobUrl": "https://b/a", "score": 0.9},
        {"title": "CS101", "chunkText": "More on Python.",        "blobUrl": "https://b/a", "score": 0.8},
        {"title": "NumPy", "chunkText": "Arrays are fast.",       "blobUrl": "https://b/b", "score": 0.7},
    ]


def test_answer_cites_only_sources_listed_in_trailer():
    with patch("bot.ai.rag.retrieve", return_value=_matches()), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "NumPy arrays are fast.\n\nSOURCES_USED: 3"
        )
        from bot.ai import answer
        out = answer(_prepared())
        assert out is not None
        # Trailer stripped from user-visible reply
        assert "SOURCES_USED" not in out
        assert "Sources:" in out
        # Only source #3 (NumPy / https://b/b) cited — not CS101 (1 or 2)
        assert "https://b/b" in out
        assert "https://b/a" not in out
        # Context passed to model is numbered
        system_msg = client.chat.completions.create.call_args.kwargs["messages"][0]
        assert "[1]" in system_msg["content"]
        assert "[3]" in system_msg["content"]


def test_answer_skips_citations_when_trailer_says_none():
    with patch("bot.ai.rag.retrieve", return_value=_matches()), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "Python is a general-purpose language.\nSOURCES_USED: none"
        )
        from bot.ai import answer
        out = answer(_prepared())
        assert out is not None
        assert "SOURCES_USED" not in out
        assert "Sources:" not in out


def test_answer_skips_citations_when_trailer_missing():
    # Legacy / non-compliant model output: no trailer at all. We prefer
    # silence over citing everything the retriever returned.
    with patch("bot.ai.rag.retrieve", return_value=_matches()), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response("because of arrays")
        from bot.ai import answer
        out = answer(_prepared())
        assert out is not None
        assert "Sources:" not in out


def test_answer_dedups_citations_by_blob_url():
    # Trailer lists both chunks of the CS101 doc (same blobUrl) — should
    # collapse to a single citation line.
    with patch("bot.ai.rag.retrieve", return_value=_matches()), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "Python notes.\nSOURCES_USED: 1,2"
        )
        from bot.ai import answer
        out = answer(_prepared())
        assert out is not None
        assert out.count("https://b/a") == 1
        assert "https://b/b" not in out


def test_answer_uses_group_active_model_when_set():
    with patch("bot.ai.rag.retrieve", return_value=[]), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value="gpt-5.4-mini"), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response("ok")
        from bot.ai import answer
        answer(_prepared())
        assert client.chat.completions.create.call_args.kwargs["model"] == "gpt-5.4-mini"


def test_answer_falls_back_to_default_model():
    with patch("bot.ai.rag.retrieve", return_value=[]), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response("ok")
        from bot.ai import answer
        answer(_prepared())
        assert client.chat.completions.create.call_args.kwargs["model"] == "gpt-5.4-nano"


def test_answer_loads_group_history_not_user_history():
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
    ]
    with patch("bot.ai.rag.retrieve", return_value=[]), \
         patch("bot.ai.get_history", return_value=history) as gh, \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response("ok")
        from bot.ai import answer
        answer(_prepared(group_key="-100999"))
        gh.assert_called_with("-100999", limit=20)
        msgs = client.chat.completions.create.call_args.kwargs["messages"]
        # history goes between system and the new user message
        assert msgs[-1]["role"] == "user"
        assert msgs[-2]["role"] == "assistant"
        assert msgs[-2]["content"] == "reply"


def test_answer_applies_prompt_prefix_for_instructor():
    with patch("bot.ai.rag.retrieve", return_value=[]), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client, \
         patch("bot.ai.prompt_prefix", return_value="[INSTRUCTOR @ediksimonian]:"):
        client.chat.completions.create.return_value = _mock_ai_response("ok")
        from bot.ai import answer
        answer(_prepared(stripped_text="help"))
        last = client.chat.completions.create.call_args.kwargs["messages"][-1]
        assert last["role"] == "user"
        assert last["content"].startswith("[INSTRUCTOR @ediksimonian]:")


def test_answer_returns_none_on_api_error():
    with patch("bot.ai.rag.retrieve", return_value=[]), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history") as ah, \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.side_effect = Exception("boom")
        from bot.ai import answer
        assert answer(_prepared()) is None
        ah.assert_not_called()  # don't persist when we have no reply


# ── needs_search ──────────────────────────────────────────────────────────
def test_needs_search_trigger_words():
    from bot.ai import needs_search
    assert needs_search("what's the latest news today") is True
    assert needs_search("explain recursion") is False


# ── _format_numbered_context ──────────────────────────────────────────────
def test_format_numbered_context_empty():
    from bot.ai import _format_numbered_context
    assert _format_numbered_context([]) == ""


def test_format_numbered_context_numbers_each_match():
    from bot.ai import _format_numbered_context
    out = _format_numbered_context([
        {"title": "A", "chunkText": "first"},
        {"title": "B", "chunkText": "second"},
    ])
    assert "[1] A" in out
    assert "first" in out
    assert "[2] B" in out
    assert "second" in out
    assert "---" in out  # separator between blocks


def test_format_numbered_context_missing_title_falls_back_to_untitled():
    from bot.ai import _format_numbered_context
    out = _format_numbered_context([{"title": "", "chunkText": "text"}])
    assert "[1] Untitled" in out


def test_format_numbered_context_assumes_caller_filtered_empty_chunks():
    """Empty-chunk filtering happens in answer() so this helper renders
    every input as-is. Numbering aligns 1:1 with the input list."""
    from bot.ai import _format_numbered_context
    out = _format_numbered_context([
        {"title": "A", "chunkText": "first"},
        {"title": "B", "chunkText": "second"},
    ])
    assert "[1] A" in out
    assert "[2] B" in out


def test_format_numbered_context_whitespace_only_title_falls_back():
    from bot.ai import _format_numbered_context
    out = _format_numbered_context([{"title": "   ", "chunkText": "text"}])
    assert "[1] Untitled" in out
    assert "[1]    " not in out


def test_answer_filters_empty_chunk_matches_before_numbering():
    """A retrieved match with empty chunkText is dropped entirely so the
    model never sees a label that points to a phantom slot, and the
    citation lookup can't accidentally cite an unseen doc."""
    matches = [
        {"title": "Phantom", "chunkText": "",          "blobUrl": "https://b/phantom", "score": 0.9},
        {"title": "Real",    "chunkText": "real text", "blobUrl": "https://b/real",    "score": 0.8},
    ]
    with patch("bot.ai.rag.retrieve", return_value=matches), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "Answer.\nSOURCES_USED: 1"
        )
        from bot.ai import answer
        out = answer(_prepared())
        assert out is not None
        sys_content = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        # Phantom doc never makes it into the prompt
        assert "Phantom" not in sys_content
        assert "[1] Real" in sys_content
        # And the citation maps to the real doc, not the phantom URL
        assert "https://b/real" in out
        assert "https://b/phantom" not in out


# ── _extract_sources_used ─────────────────────────────────────────────────
def test_extract_no_trailer_returns_none_marker():
    from bot.ai import _extract_sources_used
    clean, used = _extract_sources_used("just an answer with no trailer")
    assert clean == "just an answer with no trailer"
    assert used is None


def test_extract_none_payload_returns_empty_set():
    from bot.ai import _extract_sources_used
    clean, used = _extract_sources_used("Reply.\nSOURCES_USED: none")
    assert clean == "Reply."
    assert used == set()


def test_extract_empty_payload_returns_empty_set():
    from bot.ai import _extract_sources_used
    clean, used = _extract_sources_used("Reply.\nSOURCES_USED:")
    assert clean == "Reply."
    assert used == set()


def test_extract_whitespace_only_payload_returns_empty_set():
    from bot.ai import _extract_sources_used
    clean, used = _extract_sources_used("Reply.\nSOURCES_USED:    ")
    assert clean == "Reply."
    assert used == set()


def test_extract_comma_list_with_whitespace():
    from bot.ai import _extract_sources_used
    clean, used = _extract_sources_used("Reply.\nSOURCES_USED: 1, 2 , 3")
    assert clean == "Reply."
    assert used == {1, 2, 3}


def test_extract_is_case_insensitive():
    from bot.ai import _extract_sources_used
    _, used = _extract_sources_used("X\nsources_used: 1")
    assert used == {1}
    _, used = _extract_sources_used("X\nSoUrCeS_UsEd: 2")
    assert used == {2}


def test_extract_filters_non_numeric_tokens():
    from bot.ai import _extract_sources_used
    _, used = _extract_sources_used("X\nSOURCES_USED: 1, foo, 2, bar")
    assert used == {1, 2}


def test_extract_dedups_repeated_indices():
    from bot.ai import _extract_sources_used
    _, used = _extract_sources_used("X\nSOURCES_USED: 1,1,2,2,3")
    assert used == {1, 2, 3}


def test_extract_ignores_negative_via_digit_check():
    # "-1" has a "-" which fails .isdigit() → dropped.
    from bot.ai import _extract_sources_used
    _, used = _extract_sources_used("X\nSOURCES_USED: -1, 2")
    assert used == {2}


def test_extract_only_matches_at_end_of_string():
    """A SOURCES_USED line in the middle of the reply (followed by more
    content) is NOT a trailer — leave the reply alone."""
    from bot.ai import _extract_sources_used
    text = "First line.\nSOURCES_USED: 1\nMore content after."
    clean, used = _extract_sources_used(text)
    assert clean == text
    assert used is None


def test_extract_handles_user_text_mentioning_trailer_keyword():
    """Model echoes 'SOURCES_USED' inside its prose but also emits a real
    trailer at the end. Only the trailer should be parsed; prose is kept."""
    from bot.ai import _extract_sources_used
    text = "The SOURCES_USED variable is special.\nSOURCES_USED: none"
    clean, used = _extract_sources_used(text)
    assert clean == "The SOURCES_USED variable is special."
    assert used == set()


def test_extract_handles_blank_lines_before_trailer():
    from bot.ai import _extract_sources_used
    clean, used = _extract_sources_used("Body.\n\n\nSOURCES_USED: 1,2")
    assert clean == "Body."
    assert used == {1, 2}


def test_extract_tolerates_trailing_whitespace_after_payload():
    from bot.ai import _extract_sources_used
    clean, used = _extract_sources_used("Reply.\nSOURCES_USED: 1,2   ")
    assert clean == "Reply."
    assert used == {1, 2}


def test_extract_trailer_with_no_body_returns_empty_clean():
    from bot.ai import _extract_sources_used
    clean, used = _extract_sources_used("SOURCES_USED: 1")
    assert clean == ""
    assert used == {1}


# ── answer() — additional citation edge cases ─────────────────────────────
def test_answer_filters_out_of_range_indices():
    """Model hallucinates source numbers outside the retrieved set —
    drop them silently rather than crash or render bogus citations."""
    with patch("bot.ai.rag.retrieve", return_value=_matches()), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "Answer.\nSOURCES_USED: 99, 0, 2"
        )
        from bot.ai import answer
        out = answer(_prepared())
        assert out is not None
        # Only idx 2 was valid (CS101 / https://b/a)
        assert "https://b/a" in out
        assert "https://b/b" not in out


def test_answer_no_citation_when_all_indices_invalid():
    with patch("bot.ai.rag.retrieve", return_value=_matches()), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "Answer.\nSOURCES_USED: 99, 100"
        )
        from bot.ai import answer
        out = answer(_prepared())
        assert out is not None
        assert "Sources:" not in out


def test_answer_caps_citations_at_five():
    six = [
        {"title": f"Doc{i}", "chunkText": f"text {i}", "blobUrl": f"https://b/{i}", "score": 0.9}
        for i in range(1, 7)
    ]
    with patch("bot.ai.rag.retrieve", return_value=six), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "Big answer.\nSOURCES_USED: 1,2,3,4,5,6"
        )
        from bot.ai import answer
        out = answer(_prepared())
        assert out is not None
        # Only first 5 unique URLs survive after the slice
        assert out.count("https://b/") == 5
        assert "https://b/6" not in out


def test_answer_cites_match_without_blob_url_by_title():
    matches = [{"title": "Local Notes", "chunkText": "notes", "blobUrl": "", "score": 0.9}]
    with patch("bot.ai.rag.retrieve", return_value=matches), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "Answer.\nSOURCES_USED: 1"
        )
        from bot.ai import answer
        out = answer(_prepared())
        assert out is not None
        assert "Sources:" in out
        assert "Local Notes" in out
        # No URL parens for an entry without a blobUrl
        assert "](" not in out.split("Sources:")[1]


def test_answer_ignore_marker_survives_trailer_extraction():
    """Trailer is stripped BEFORE guardrail so the IGNORE token can still
    be detected and the reply suppressed entirely."""
    with patch("bot.ai.rag.retrieve", return_value=_matches()), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history") as ah, \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "IGNORE\nSOURCES_USED: none"
        )
        from bot.ai import answer
        out = answer(_prepared())
        assert out is None
        ah.assert_not_called()


def test_answer_persists_clean_reply_without_trailer():
    """append_history must store the user-visible reply, not the raw output
    with the trailer baked in — otherwise SOURCES_USED leaks into the next
    turn's context."""
    captured = []
    def _capture(group_key, role, content, **kw):
        captured.append((role, content))
    with patch("bot.ai.rag.retrieve", return_value=_matches()), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history", side_effect=_capture), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "The clean answer.\nSOURCES_USED: 1"
        )
        from bot.ai import answer
        answer(_prepared())
        roles = [r for r, _ in captured]
        contents = [c for _, c in captured]
        assert roles == ["user", "assistant"]
        # Assistant turn in history must NOT contain the trailer or the
        # appended Sources block (history is the model-facing transcript).
        assert "SOURCES_USED" not in contents[1]
        assert "Sources:" not in contents[1]
        assert contents[1] == "The clean answer."


def test_answer_emits_no_citation_when_matches_empty_even_with_trailer():
    """Belt-and-suspenders: if RAG returned nothing but the model invented
    a SOURCES_USED line anyway, never fabricate a Sources block."""
    with patch("bot.ai.rag.retrieve", return_value=[]), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "Just answering.\nSOURCES_USED: 1,2"
        )
        from bot.ai import answer
        out = answer(_prepared())
        assert out is not None
        assert "Sources:" not in out
        # Trailer still stripped from user-visible reply
        assert "SOURCES_USED" not in out


def test_answer_system_prompt_includes_trailer_instructions_when_rag_hits():
    with patch("bot.ai.rag.retrieve", return_value=_matches()), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "Hi.\nSOURCES_USED: none"
        )
        from bot.ai import answer
        answer(_prepared())
        sys_content = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "SOURCES_USED:" in sys_content
        assert "none" in sys_content


def test_answer_system_prompt_omits_trailer_instructions_with_no_rag_hits():
    """No retrieval hits → no point asking the model to emit the trailer.
    Keeps the system prompt minimal for the common knowledge-only path."""
    with patch("bot.ai.rag.retrieve", return_value=[]), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response("answer")
        from bot.ai import answer
        answer(_prepared())
        sys_content = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "SOURCES_USED" not in sys_content


def test_answer_dm_strips_trailer_from_dm_log():
    """The per-user DM transcript stores raw user text + clean assistant
    reply, never the SOURCES_USED line."""
    captured = []
    def _capture(user_id, role, content, **kw):
        captured.append((role, content))
    with patch("bot.ai.rag.retrieve", return_value=_matches()), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.append_dm_log", side_effect=_capture), \
         patch("bot.ai.get_last_group_qa", return_value=None), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "Clean DM reply.\nSOURCES_USED: 1"
        )
        from bot.ai import answer
        answer(_prepared(is_dm=True))
        # Two appends: user + assistant
        assert len(captured) == 2
        assistant_content = captured[1][1]
        assert "SOURCES_USED" not in assistant_content
        assert "Sources:" not in assistant_content


def test_extract_handles_crlf_line_endings():
    """Windows-style \\r\\n endings shouldn't break parsing — the \\r is
    swallowed by .strip() on the payload and by .rstrip() on clean."""
    from bot.ai import _extract_sources_used
    clean, used = _extract_sources_used("Body.\r\nSOURCES_USED: 1\r\n")
    assert clean == "Body."
    assert used == {1}


def test_extract_rejects_markdown_wrapped_trailer():
    """`**SOURCES_USED:** 1` is not the documented format — leave it as
    visible reply text rather than parsing it."""
    from bot.ai import _extract_sources_used
    text = "Reply.\n**SOURCES_USED:** 1"
    clean, used = _extract_sources_used(text)
    assert clean == text
    assert used is None


def test_extract_takes_last_trailer_when_multiple_present():
    """If the model emits two trailers (rare), only the last one — anchored
    to end-of-string — counts. The earlier one stays in the body."""
    from bot.ai import _extract_sources_used
    clean, used = _extract_sources_used(
        "Intro.\nSOURCES_USED: 1\nMore body.\nSOURCES_USED: 2"
    )
    assert used == {2}
    assert "SOURCES_USED: 1" in clean   # earlier line preserved
    assert "More body." in clean


def test_extract_zero_padded_numbers_resolve_to_int():
    """`01` is digit-only so we accept it as `1`. Documenting current
    behavior — we don't want surprises if the model emits leading zeros."""
    from bot.ai import _extract_sources_used
    _, used = _extract_sources_used("X\nSOURCES_USED: 01, 02")
    assert used == {1, 2}


def test_extract_rejects_decimal_numbers():
    from bot.ai import _extract_sources_used
    _, used = _extract_sources_used("X\nSOURCES_USED: 1.5, 2")
    assert used == {2}


def test_answer_caps_at_five_after_dedup():
    """Cap should apply to unique-URL citations, not raw indices. Six
    indices that collapse to 4 unique URLs should cite all 4."""
    matches = [
        {"title": "A", "chunkText": "x", "blobUrl": "https://b/a", "score": 0.9},
        {"title": "A", "chunkText": "x", "blobUrl": "https://b/a", "score": 0.8},  # dup of #1
        {"title": "B", "chunkText": "x", "blobUrl": "https://b/b", "score": 0.7},
        {"title": "C", "chunkText": "x", "blobUrl": "https://b/c", "score": 0.6},
        {"title": "C", "chunkText": "x", "blobUrl": "https://b/c", "score": 0.5},  # dup of #4
        {"title": "D", "chunkText": "x", "blobUrl": "https://b/d", "score": 0.4},
    ]
    with patch("bot.ai.rag.retrieve", return_value=matches), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "Answer.\nSOURCES_USED: 1,2,3,4,5,6"
        )
        from bot.ai import answer
        out = answer(_prepared())
        assert out is not None
        for u in ("https://b/a", "https://b/b", "https://b/c", "https://b/d"):
            assert out.count(u) == 1


def test_answer_whitespace_only_title_in_citation_falls_back_to_doc():
    matches = [{"title": "   ", "chunkText": "x", "blobUrl": "https://b/x", "score": 0.9}]
    with patch("bot.ai.rag.retrieve", return_value=matches), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "Answer.\nSOURCES_USED: 1"
        )
        from bot.ai import answer
        out = answer(_prepared())
        assert out is not None
        assert "Sources:" in out
        # No raw whitespace title leaks into the bullet
        assert "[   ]" not in out
        assert "[doc]" in out


def test_answer_returns_none_when_reply_is_only_trailer():
    """Model output with no body but a trailer → empty after extraction →
    guardrail suppresses → no reply, no history persistence."""
    with patch("bot.ai.rag.retrieve", return_value=_matches()), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history") as ah, \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "SOURCES_USED: 1"
        )
        from bot.ai import answer
        assert answer(_prepared()) is None
        ah.assert_not_called()


def test_answer_trailer_in_dm_appends_citation_but_no_followup_nudge():
    with patch("bot.ai.rag.retrieve", return_value=_matches()), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.append_dm_log"), \
         patch("bot.ai.get_last_group_qa", return_value=None), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response(
            "Answer.\nSOURCES_USED: 3"
        )
        from bot.ai import answer
        out = answer(_prepared(is_dm=True))
        assert out is not None
        assert "Sources:" in out
        assert "https://b/b" in out
        assert "DM me" not in out  # no group-only nudge in DMs
