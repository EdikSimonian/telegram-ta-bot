from unittest.mock import patch, MagicMock
from bot.ai import needs_search


# ── needs_search ───────────────────────────────────────────────────────────────

def test_needs_search_detects_news():
    assert needs_search("what is the latest news about Iran?") is True


def test_needs_search_detects_today():
    assert needs_search("what happened today?") is True


def test_needs_search_detects_current():
    assert needs_search("who is the current president?") is True


def test_needs_search_false_for_general_question():
    assert needs_search("what is the capital of France?") is False


def test_needs_search_false_for_coding_question():
    assert needs_search("how do I reverse a list in Python?") is False


def test_needs_search_case_insensitive():
    assert needs_search("What is TODAY's weather?") is True


# ── ask_ai orchestration ──────────────────────────────────────────────────────

def test_ask_ai_returns_reply():
    with patch("bot.ai.generate", return_value="Hello there!"), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.save_history"), \
         patch("bot.ai.get_provider", return_value="openai"):
        from bot.ai import ask_ai
        reply = ask_ai(123, "hi")
        assert reply == "Hello there!"


def test_ask_ai_saves_history():
    with patch("bot.ai.generate", return_value="reply"), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.save_history") as mock_save, \
         patch("bot.ai.get_provider", return_value="openai"):
        from bot.ai import ask_ai
        ask_ai(123, "hi")
        mock_save.assert_called_once()
        saved_history = mock_save.call_args[0][1]
        assert saved_history[0] == {"role": "user", "content": "hi"}
        assert saved_history[1]["role"] == "assistant"


def test_ask_ai_appends_sources_when_search_used():
    sources = [{"title": "BBC", "url": "https://bbc.com"}]
    with patch("bot.ai.generate", return_value="Here is the news."), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.save_history"), \
         patch("bot.ai.get_provider", return_value="openai"), \
         patch("bot.ai.TAVILY_API_KEY", "fake_key"), \
         patch("bot.ai.needs_search", return_value=True), \
         patch("bot.search.web_search", return_value=("search text", sources)):
        from bot.ai import ask_ai
        reply = ask_ai(123, "latest news")
        assert "**Sources:**" in reply
        assert "[BBC](https://bbc.com)" in reply


def test_ask_ai_no_sources_for_general_question():
    with patch("bot.ai.generate", return_value="Paris."), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.save_history"), \
         patch("bot.ai.get_provider", return_value="openai"):
        from bot.ai import ask_ai
        reply = ask_ai(123, "what is the capital of France?")
        assert "Sources" not in reply


def test_ask_ai_skips_search_for_hf_provider():
    """HF (ArmGPT) is Armenian-only; don't pollute it with English search results."""
    sources = [{"title": "BBC", "url": "https://bbc.com"}]
    with patch("bot.ai.generate", return_value="Հայաստան"), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.save_history"), \
         patch("bot.ai.get_provider", return_value="hf"), \
         patch("bot.ai.TAVILY_API_KEY", "fake_key"), \
         patch("bot.ai.needs_search", return_value=True), \
         patch("bot.search.web_search", return_value=("search text", sources)) as mock_search:
        from bot.ai import ask_ai
        reply = ask_ai(123, "latest news")
        mock_search.assert_not_called()
        assert "Sources" not in reply


def test_ask_ai_passes_user_id_to_generate():
    with patch("bot.ai.generate", return_value="hi") as mock_gen, \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.save_history"), \
         patch("bot.ai.get_provider", return_value="openai"):
        from bot.ai import ask_ai
        ask_ai(456, "hello")
        assert mock_gen.call_args[0][0] == 456
