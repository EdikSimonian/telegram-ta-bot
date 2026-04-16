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


def test_answer_with_rag_hits_injects_context_and_citations():
    matches = [
        {"title": "CS101", "chunkText": "Python is a language.", "blobUrl": "https://b/a", "score": 0.9},
        {"title": "CS101", "chunkText": "More on Python.",        "blobUrl": "https://b/a", "score": 0.8},
        {"title": "NumPy", "chunkText": "Arrays are fast.",       "blobUrl": "https://b/b", "score": 0.7},
    ]
    with patch("bot.ai.rag.retrieve", return_value=matches), \
         patch("bot.ai.rag.format_context", return_value="<ctx>"), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = _mock_ai_response("because of arrays")
        from bot.ai import answer
        out = answer(_prepared())
        assert out is not None
        assert "Sources:" in out
        # Dedup: two hits for CS101 (same blobUrl) collapse to one citation
        assert out.count("https://b/a") == 1
        assert "https://b/b" in out
        system_msg = client.chat.completions.create.call_args.kwargs["messages"][0]
        assert "<ctx>" in system_msg["content"]


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
