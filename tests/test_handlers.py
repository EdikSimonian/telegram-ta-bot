from unittest.mock import patch, MagicMock


def make_message(text="hello", user_id=123, chat_id=456, chat_type="private"):
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = user_id
    msg.chat.id = chat_id
    msg.chat.type = chat_type
    msg.reply_to_message = None
    return msg


HANDLER_PATCHES = {
    "bot.handlers.should_respond": True,
    "bot.handlers.is_rate_limited": False,
    "bot.handlers.BOT_INFO": MagicMock(id=42, username="testbot"),
}


def test_handle_message_calls_ask_ai():
    with patch("bot.handlers.should_respond", return_value=True), \
         patch("bot.handlers.is_rate_limited", return_value=False), \
         patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")), \
         patch("bot.handlers.ask_ai", return_value="AI reply") as mock_ask, \
         patch("bot.handlers.send_reply") as mock_send, \
         patch("bot.handlers.bot"):
        from bot.handlers import handle_message
        msg = make_message(text="hello")
        handle_message(msg)
        mock_ask.assert_called_once_with(123, "hello")
        mock_send.assert_called_once_with(msg, "AI reply")


def test_handle_message_skips_when_not_responding():
    with patch("bot.handlers.should_respond", return_value=False), \
         patch("bot.handlers.ask_ai") as mock_ask:
        from bot.handlers import handle_message
        handle_message(make_message())
        mock_ask.assert_not_called()


def test_handle_message_rate_limited():
    with patch("bot.handlers.should_respond", return_value=True), \
         patch("bot.handlers.is_rate_limited", return_value=True), \
         patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")), \
         patch("bot.handlers.ask_ai") as mock_ask, \
         patch("bot.handlers.bot") as mock_bot:
        from bot.handlers import handle_message
        handle_message(make_message())
        mock_ask.assert_not_called()
        mock_bot.send_message.assert_called_once()
        assert "daily limit" in mock_bot.send_message.call_args[0][1]


def test_handle_message_sends_generic_error():
    with patch("bot.handlers.should_respond", return_value=True), \
         patch("bot.handlers.is_rate_limited", return_value=False), \
         patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")), \
         patch("bot.handlers.ask_ai", side_effect=Exception("API key invalid")), \
         patch("bot.handlers.bot") as mock_bot:
        from bot.handlers import handle_message
        handle_message(make_message())
        error_msg = mock_bot.send_message.call_args[0][1]
        assert "Something went wrong" in error_msg
        assert "API key" not in error_msg


def test_handle_message_none_text():
    with patch("bot.handlers.should_respond", return_value=True), \
         patch("bot.handlers.is_rate_limited", return_value=False), \
         patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")), \
         patch("bot.handlers.ask_ai", return_value="reply") as mock_ask, \
         patch("bot.handlers.send_reply"), \
         patch("bot.handlers.bot"):
        from bot.handlers import handle_message
        msg = make_message()
        msg.text = None
        handle_message(msg)
        mock_ask.assert_called_once_with(msg.from_user.id, "")


# ── /model command ────────────────────────────────────────────────────────────

def _reload_handlers_with(hf="", armgpt_url="", armgpt_key=""):
    """Reload bot.handlers with specific provider env vars set.

    Patches both bot.config and bot.preferences (which is what
    enabled_providers() actually reads), then reloads handlers so its
    module-level _MODEL_COMMAND_ENABLED recomputes.
    """
    import importlib
    import bot.config
    import bot.preferences
    import bot.handlers
    bot.config.HF_SPACE_ID = hf
    bot.config.ARMGPT_BASE_URL = armgpt_url
    bot.config.ARMGPT_API_KEY = armgpt_key
    bot.preferences.HF_SPACE_ID = hf
    bot.preferences.ARMGPT_BASE_URL = armgpt_url
    bot.preferences.ARMGPT_API_KEY = armgpt_key
    if hasattr(bot.handlers, "cmd_model"):
        delattr(bot.handlers, "cmd_model")
    importlib.reload(bot.handlers)
    return bot.handlers


def test_cmd_model_no_args_shows_current_with_hf():
    handlers = _reload_handlers_with(hf="fake/space")
    assert hasattr(handlers, "cmd_model")
    with patch("bot.handlers.get_provider", return_value="openai"), \
         patch("bot.handlers.bot") as mock_bot:
        msg = make_message(text="/model")
        handlers.cmd_model(msg)
        sent = mock_bot.send_message.call_args[0][1]
        assert "Current provider: openai" in sent
        assert "/model openai" in sent
        assert "/model hf" in sent


def test_cmd_model_no_args_shows_armgpt_when_enabled():
    handlers = _reload_handlers_with(armgpt_url="https://x/v1", armgpt_key="k")
    assert hasattr(handlers, "cmd_model")
    with patch("bot.handlers.get_provider", return_value="openai"), \
         patch("bot.handlers.bot") as mock_bot:
        msg = make_message(text="/model")
        handlers.cmd_model(msg)
        sent = mock_bot.send_message.call_args[0][1]
        assert "/model armgpt" in sent
        assert "/model hf" not in sent


def test_cmd_model_switch_to_hf():
    handlers = _reload_handlers_with(hf="fake/space")
    with patch("bot.handlers.set_provider", return_value=True) as mock_set, \
         patch("bot.handlers.bot") as mock_bot:
        msg = make_message(text="/model hf")
        handlers.cmd_model(msg)
        mock_set.assert_called_once_with(123, "hf")
        sent = mock_bot.send_message.call_args[0][1]
        assert "hf" in sent
        assert "Armenian" in sent


def test_cmd_model_switch_to_armgpt():
    handlers = _reload_handlers_with(armgpt_url="https://x/v1", armgpt_key="k")
    with patch("bot.handlers.set_provider", return_value=True) as mock_set, \
         patch("bot.handlers.bot") as mock_bot:
        msg = make_message(text="/model armgpt")
        handlers.cmd_model(msg)
        mock_set.assert_called_once_with(123, "armgpt")
        sent = mock_bot.send_message.call_args[0][1]
        assert "armgpt" in sent
        assert "Modal" in sent


def test_cmd_model_switch_to_openai():
    handlers = _reload_handlers_with(hf="fake/space")
    with patch("bot.handlers.set_provider", return_value=True) as mock_set, \
         patch("bot.handlers.bot") as mock_bot:
        msg = make_message(text="/model openai")
        handlers.cmd_model(msg)
        mock_set.assert_called_once_with(123, "openai")
        sent = mock_bot.send_message.call_args[0][1]
        assert "openai" in sent


def test_cmd_model_rejects_disabled_provider():
    """Asking for armgpt when only hf is configured should be rejected."""
    handlers = _reload_handlers_with(hf="fake/space")
    with patch("bot.handlers.set_provider") as mock_set, \
         patch("bot.handlers.bot") as mock_bot:
        msg = make_message(text="/model armgpt")
        handlers.cmd_model(msg)
        mock_set.assert_not_called()
        assert "Invalid" in mock_bot.send_message.call_args[0][1]


def test_cmd_model_invalid_choice():
    handlers = _reload_handlers_with(hf="fake/space")
    with patch("bot.handlers.set_provider") as mock_set, \
         patch("bot.handlers.bot") as mock_bot:
        msg = make_message(text="/model bogus")
        handlers.cmd_model(msg)
        mock_set.assert_not_called()
        assert "Invalid" in mock_bot.send_message.call_args[0][1]


def test_cmd_model_redis_error_reports_failure():
    handlers = _reload_handlers_with(hf="fake/space")
    with patch("bot.handlers.set_provider", return_value=False), \
         patch("bot.handlers.bot") as mock_bot:
        msg = make_message(text="/model hf")
        handlers.cmd_model(msg)
        assert "Could not save" in mock_bot.send_message.call_args[0][1]


def test_cmd_model_not_registered_when_only_openai():
    """No alternate providers configured → /model not registered."""
    handlers = _reload_handlers_with()
    assert not hasattr(handlers, "cmd_model")


def test_handle_message_uses_keep_typing():
    """handle_message should wrap ask_ai in the keep_typing context."""
    with patch("bot.handlers.should_respond", return_value=True), \
         patch("bot.handlers.is_rate_limited", return_value=False), \
         patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")), \
         patch("bot.handlers.ask_ai", return_value="reply"), \
         patch("bot.handlers.send_reply"), \
         patch("bot.handlers.keep_typing") as mock_keep, \
         patch("bot.handlers.bot"):
        mock_keep.return_value.__enter__ = MagicMock(return_value=None)
        mock_keep.return_value.__exit__ = MagicMock(return_value=None)
        from bot.handlers import handle_message
        msg = make_message()
        handle_message(msg)
        mock_keep.assert_called_once_with(456)
