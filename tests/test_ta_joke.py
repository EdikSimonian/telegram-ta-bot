"""Tests for /joke generation, formatting, and posting."""
from unittest.mock import MagicMock, patch


def _llm(text: str) -> MagicMock:
    return MagicMock(choices=[MagicMock(message=MagicMock(content=text))])


# ── _build_prompt ─────────────────────────────────────────────────────────
def test_build_prompt_includes_theme_when_provided():
    from bot.ta.joke import _build_prompt
    out = _build_prompt("about python")
    assert "about python" in out
    assert "1-3 sentences" in out


def test_build_prompt_uses_fallback_when_theme_blank():
    from bot.ta.joke import _build_prompt
    out = _build_prompt("   ")
    # Falls back to the generic "any fun subject" wording — not the user's theme.
    assert "any fun subject" in out


# ── generate_joke ─────────────────────────────────────────────────────────
def test_generate_joke_returns_llm_text():
    with patch("bot.ta.joke.ai") as client, \
         patch("bot.ta.joke.get_active_model", return_value=None):
        client.chat.completions.create.return_value = _llm(
            "Why did the dev go broke? Because he used up all his cache."
        )
        from bot.ta.joke import generate_joke
        out = generate_joke("about python", "-100123")
        assert out == "Why did the dev go broke? Because he used up all his cache."


def test_generate_joke_passes_active_model_when_set():
    with patch("bot.ta.joke.ai") as client, \
         patch("bot.ta.joke.get_active_model", return_value="gpt-5.4-mini"):
        client.chat.completions.create.return_value = _llm("knock knock")
        from bot.ta.joke import generate_joke
        generate_joke("about cats", "-100123")
        kwargs = client.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == "gpt-5.4-mini"


def test_generate_joke_works_with_blank_theme():
    with patch("bot.ta.joke.ai") as client, \
         patch("bot.ta.joke.get_active_model", return_value=None):
        client.chat.completions.create.return_value = _llm("a generic joke")
        from bot.ta.joke import generate_joke
        out = generate_joke("", "-100123")
        assert out == "a generic joke"


def test_generate_joke_returns_none_on_llm_exception():
    with patch("bot.ta.joke.ai") as client, \
         patch("bot.ta.joke.get_active_model", return_value=None):
        client.chat.completions.create.side_effect = RuntimeError("boom")
        from bot.ta.joke import generate_joke
        assert generate_joke("about python", "-100123") is None


def test_generate_joke_returns_none_on_empty_response():
    with patch("bot.ta.joke.ai") as client, \
         patch("bot.ta.joke.get_active_model", return_value=None):
        client.chat.completions.create.return_value = _llm("   ")
        from bot.ta.joke import generate_joke
        assert generate_joke("about python", "-100123") is None


def test_generate_joke_returns_none_when_choices_missing():
    with patch("bot.ta.joke.ai") as client, \
         patch("bot.ta.joke.get_active_model", return_value=None):
        client.chat.completions.create.return_value = MagicMock(choices=[])
        from bot.ta.joke import generate_joke
        assert generate_joke("about python", "-100123") is None


def test_generate_joke_returns_none_when_message_is_none():
    with patch("bot.ta.joke.ai") as client, \
         patch("bot.ta.joke.get_active_model", return_value=None):
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=None)]
        )
        from bot.ta.joke import generate_joke
        assert generate_joke("about python", "-100123") is None


def test_generate_joke_returns_none_when_content_is_non_string():
    with patch("bot.ta.joke.ai") as client, \
         patch("bot.ta.joke.get_active_model", return_value=None):
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=[{"type": "text", "text": "hi"}]))]
        )
        from bot.ta.joke import generate_joke
        assert generate_joke("about python", "-100123") is None


# ── format_joke_for_display ───────────────────────────────────────────────
def test_format_includes_theme_in_header():
    from bot.ta.joke import format_joke_for_display
    out = format_joke_for_display("about python", "snek joke")
    assert "Joke — about python" in out
    assert "snek joke" in out


def test_format_omits_theme_when_blank():
    from bot.ta.joke import format_joke_for_display
    out = format_joke_for_display("", "raw joke")
    # No dash, no trailing whitespace before the body.
    assert "Joke —" not in out
    assert out.startswith("😂 Joke\n\nraw joke")


# ── tell_joke ─────────────────────────────────────────────────────────────
def test_tell_joke_sends_to_target_chat_on_success():
    with patch("bot.ta.joke.send_message", return_value=99) as sm, \
         patch("bot.ta.joke.generate_joke", return_value="ha ha"):
        from bot.ta.joke import tell_joke
        ok = tell_joke("about python", "-100123", -100123)
        assert ok is True
        chat_id, text = sm.call_args.args
        assert chat_id == -100123
        assert "ha ha" in text
        assert "Joke — about python" in text


def test_tell_joke_returns_false_when_generation_fails():
    with patch("bot.ta.joke.send_message") as sm, \
         patch("bot.ta.joke.generate_joke", return_value=None):
        from bot.ta.joke import tell_joke
        assert tell_joke("about python", "-100123", -100123) is False
        sm.assert_not_called()


def test_tell_joke_returns_false_when_send_fails():
    with patch("bot.ta.joke.send_message", return_value=None), \
         patch("bot.ta.joke.generate_joke", return_value="ha ha"):
        from bot.ta.joke import tell_joke
        assert tell_joke("about python", "-100123", -100123) is False


# ── /joke command handler ─────────────────────────────────────────────────
def _prepared(*, command_args="", is_dm=False, chat_id=-100123, user_id=42,
              group_key="-100123"):
    p = MagicMock()
    p.command = "joke"
    p.command_args = command_args
    p.is_dm = is_dm
    p.chat_id = chat_id
    p.user_id = user_id
    p.group_key = group_key
    return p


def test_cmd_joke_in_group_posts_to_same_group():
    with patch("bot.ta.commands.joke_mod.tell_joke", return_value=True) as tj, \
         patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_active_group_id", return_value="-200999"):
        from bot.ta.commands import _cmd_joke
        _cmd_joke(_prepared(command_args="about python", is_dm=False, chat_id=-100123))
        # Group invocation ignores active group; posts back to same chat.
        tj.assert_called_once_with("about python", "-100123", -100123)
        sm.assert_not_called()


def test_cmd_joke_in_dm_posts_to_active_group_when_set():
    with patch("bot.ta.commands.joke_mod.tell_joke", return_value=True) as tj, \
         patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_active_group_id", return_value="-200999"):
        from bot.ta.commands import _cmd_joke
        _cmd_joke(_prepared(command_args="about late", is_dm=True, chat_id=42,
                            user_id=42, group_key="dm:42"))
        # Model context must be the destination group key, not the DM's group_key.
        tj.assert_called_once_with("about late", "-200999", "-200999")
        sm.assert_not_called()


def test_cmd_joke_in_dm_falls_back_to_dm_chat_when_no_active_group():
    with patch("bot.ta.commands.joke_mod.tell_joke", return_value=True) as tj, \
         patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_active_group_id", return_value=None):
        from bot.ta.commands import _cmd_joke
        _cmd_joke(_prepared(command_args="", is_dm=True, chat_id=42, user_id=42,
                            group_key="dm:42"))
        # No active group → model context stays the DM's own group_key.
        tj.assert_called_once_with("", "dm:42", 42)
        sm.assert_not_called()


def test_cmd_joke_dm_admin_when_generation_fails():
    with patch("bot.ta.commands.joke_mod.tell_joke", return_value=False), \
         patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_active_group_id", return_value=None):
        from bot.ta.commands import _cmd_joke
        _cmd_joke(_prepared(command_args="about python", is_dm=False, chat_id=-100123, user_id=42))
        sm.assert_called_once()
        chat_id, text = sm.call_args.args
        assert chat_id == 42
        assert "Couldn't generate" in text


# ── /help mentions /joke ──────────────────────────────────────────────────
def test_help_lists_joke_command():
    with patch("bot.ta.commands.send_message") as sm:
        from bot.ta.commands import _cmd_help
        p = MagicMock()
        p.user_id = 42
        _cmd_help(p)
        text = sm.call_args.args[1]
        assert "/joke" in text
