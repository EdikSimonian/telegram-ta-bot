"""Unit tests for bot.ta.jokes.generate_joke."""
from unittest.mock import MagicMock, patch


def _mock_ai_reply(text: str):
    """Return a MagicMock shaped like an OpenAI ChatCompletion response."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    return resp


def test_generate_joke_passes_theme_to_llm():
    with patch("bot.ta.jokes.ai") as ai_mock, \
         patch("bot.ta.jokes.get_active_model", return_value=None):
        ai_mock.chat.completions.create.return_value = _mock_ai_reply(
            "Why did the Python cross the road? To get to the other import."
        )
        from bot.ta.jokes import generate_joke
        out = generate_joke("python", group_key="-100123")
        assert out == "Why did the Python cross the road? To get to the other import."

        kwargs = ai_mock.chat.completions.create.call_args.kwargs
        messages = kwargs["messages"]
        # System + user messages, in that order.
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        # User prompt carries the theme verbatim.
        assert "python" in messages[1]["content"]


def test_generate_joke_without_theme_omits_subject():
    """Empty theme: prompt still asks for a joke, just doesn't specify one."""
    with patch("bot.ta.jokes.ai") as ai_mock, \
         patch("bot.ta.jokes.get_active_model", return_value=None):
        ai_mock.chat.completions.create.return_value = _mock_ai_reply("A joke.")
        from bot.ta.jokes import generate_joke
        out = generate_joke("")
        assert out == "A joke."
        user_prompt = ai_mock.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "about:" not in user_prompt.lower()


def test_generate_joke_caps_long_theme():
    from bot.ta.jokes import MAX_THEME_LEN
    long_theme = "x" * (MAX_THEME_LEN + 500)
    with patch("bot.ta.jokes.ai") as ai_mock, \
         patch("bot.ta.jokes.get_active_model", return_value=None):
        ai_mock.chat.completions.create.return_value = _mock_ai_reply("joke")
        from bot.ta.jokes import generate_joke
        generate_joke(long_theme)
        user_prompt = ai_mock.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        # The theme embedded in the prompt must be truncated to MAX_THEME_LEN.
        assert user_prompt.count("x") == MAX_THEME_LEN


def test_generate_joke_honors_active_model_for_group():
    with patch("bot.ta.jokes.ai") as ai_mock, \
         patch("bot.ta.jokes.get_active_model", return_value="gpt-5.4-mini"):
        ai_mock.chat.completions.create.return_value = _mock_ai_reply("joke")
        from bot.ta.jokes import generate_joke
        generate_joke("coffee", group_key="-100123")
        assert ai_mock.chat.completions.create.call_args.kwargs["model"] == "gpt-5.4-mini"


def test_generate_joke_falls_back_to_default_model_when_no_group_key():
    """Default group_key='default' still consults get_active_model — matching
    bot/ai.py's convention. When no override is set, we use DEFAULT_MODEL."""
    with patch("bot.ta.jokes.ai") as ai_mock, \
         patch("bot.ta.jokes.get_active_model", return_value=None) as gam:
        ai_mock.chat.completions.create.return_value = _mock_ai_reply("joke")
        from bot.ta.jokes import generate_joke
        from bot.config import DEFAULT_MODEL
        generate_joke("coffee")  # no group_key → default
        gam.assert_called_once_with("default")
        assert ai_mock.chat.completions.create.call_args.kwargs["model"] == DEFAULT_MODEL


def test_generate_joke_honors_active_model_for_dm_context():
    """DM context (group_key='default') must still pick up an active-model
    override — same as the regular Q&A path in bot/ai.py."""
    with patch("bot.ta.jokes.ai") as ai_mock, \
         patch("bot.ta.jokes.get_active_model", return_value="qwen-3-235b-a22b-instruct-2507") as gam:
        ai_mock.chat.completions.create.return_value = _mock_ai_reply("joke")
        from bot.ta.jokes import generate_joke
        generate_joke("coffee", group_key="default")
        gam.assert_called_once_with("default")
        assert ai_mock.chat.completions.create.call_args.kwargs["model"] == "qwen-3-235b-a22b-instruct-2507"


def test_generate_joke_returns_none_on_llm_error():
    with patch("bot.ta.jokes.ai") as ai_mock, \
         patch("bot.ta.jokes.get_active_model", return_value=None):
        ai_mock.chat.completions.create.side_effect = RuntimeError("upstream 500")
        from bot.ta.jokes import generate_joke
        assert generate_joke("anything") is None


def test_generate_joke_returns_none_on_empty_llm_reply():
    with patch("bot.ta.jokes.ai") as ai_mock, \
         patch("bot.ta.jokes.get_active_model", return_value=None):
        ai_mock.chat.completions.create.return_value = _mock_ai_reply("   ")
        from bot.ta.jokes import generate_joke
        assert generate_joke("anything") is None


def test_generate_joke_returns_none_when_choices_missing():
    """Malformed response with empty choices list must not raise — return None."""
    with patch("bot.ta.jokes.ai") as ai_mock, \
         patch("bot.ta.jokes.get_active_model", return_value=None):
        ai_mock.chat.completions.create.return_value = MagicMock(choices=[])
        from bot.ta.jokes import generate_joke
        assert generate_joke("python") is None


def test_generate_joke_returns_none_when_message_is_none():
    """Choice without a message attribute (or message=None) must not crash."""
    with patch("bot.ta.jokes.ai") as ai_mock, \
         patch("bot.ta.jokes.get_active_model", return_value=None):
        bad = MagicMock()
        bad.choices = [MagicMock(message=None)]
        ai_mock.chat.completions.create.return_value = bad
        from bot.ta.jokes import generate_joke
        assert generate_joke("python") is None


def test_generate_joke_returns_none_when_content_is_none():
    """choices[0].message.content == None must yield None, not crash."""
    with patch("bot.ta.jokes.ai") as ai_mock, \
         patch("bot.ta.jokes.get_active_model", return_value=None):
        ai_mock.chat.completions.create.return_value = _mock_ai_reply(None)
        from bot.ta.jokes import generate_joke
        assert generate_joke("python") is None


def test_generate_joke_none_group_key_falls_back_to_default():
    """Explicit group_key=None must not crash get_active_model — it
    normalizes to 'default' so the active-model lookup still works."""
    with patch("bot.ta.jokes.ai") as ai_mock, \
         patch("bot.ta.jokes.get_active_model", return_value=None) as gam:
        ai_mock.chat.completions.create.return_value = _mock_ai_reply("joke")
        from bot.ta.jokes import generate_joke
        out = generate_joke("coffee", group_key=None)
        assert out == "joke"
        gam.assert_called_once_with("default")
