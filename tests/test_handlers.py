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

def _import_cmd_model_with_hf_enabled():
    """Re-import handlers module with HF_SPACE_ID set so cmd_model exists."""
    import importlib
    import bot.config
    import bot.handlers
    original = bot.config.HF_SPACE_ID
    bot.config.HF_SPACE_ID = "fake/space"
    # Also patch the import in handlers module (already imported via `from ... import HF_SPACE_ID`)
    bot.handlers.HF_SPACE_ID = "fake/space"
    importlib.reload(bot.handlers)
    cmd_model = getattr(bot.handlers, "cmd_model", None)
    # Restore
    bot.config.HF_SPACE_ID = original
    bot.handlers.HF_SPACE_ID = original
    return cmd_model


def test_cmd_model_no_args_shows_current():
    cmd_model = _import_cmd_model_with_hf_enabled()
    assert cmd_model is not None
    with patch("bot.handlers.get_provider", return_value="openai"), \
         patch("bot.handlers.bot") as mock_bot:
        msg = make_message(text="/model")
        cmd_model(msg)
        sent = mock_bot.send_message.call_args[0][1]
        assert "Current provider: openai" in sent
        assert "/model openai" in sent
        assert "/model hf" in sent


def test_cmd_model_switch_to_hf():
    cmd_model = _import_cmd_model_with_hf_enabled()
    with patch("bot.handlers.set_provider", return_value=True) as mock_set, \
         patch("bot.handlers.bot") as mock_bot:
        msg = make_message(text="/model hf")
        cmd_model(msg)
        mock_set.assert_called_once_with(123, "hf")
        sent = mock_bot.send_message.call_args[0][1]
        assert "hf" in sent
        assert "Armenian" in sent


def test_cmd_model_switch_to_openai():
    cmd_model = _import_cmd_model_with_hf_enabled()
    with patch("bot.handlers.set_provider", return_value=True) as mock_set, \
         patch("bot.handlers.bot") as mock_bot:
        msg = make_message(text="/model openai")
        cmd_model(msg)
        mock_set.assert_called_once_with(123, "openai")
        sent = mock_bot.send_message.call_args[0][1]
        assert "openai" in sent


def test_cmd_model_invalid_choice():
    cmd_model = _import_cmd_model_with_hf_enabled()
    with patch("bot.handlers.set_provider") as mock_set, \
         patch("bot.handlers.bot") as mock_bot:
        msg = make_message(text="/model bogus")
        cmd_model(msg)
        mock_set.assert_not_called()
        assert "Invalid" in mock_bot.send_message.call_args[0][1]


def test_cmd_model_redis_error_reports_failure():
    cmd_model = _import_cmd_model_with_hf_enabled()
    with patch("bot.handlers.set_provider", return_value=False), \
         patch("bot.handlers.bot") as mock_bot:
        msg = make_message(text="/model hf")
        cmd_model(msg)
        assert "Could not save" in mock_bot.send_message.call_args[0][1]


def test_cmd_model_not_registered_without_hf_space_id():
    """When HF_SPACE_ID is empty, cmd_model should not exist."""
    import importlib
    import bot.config
    import bot.handlers
    bot.config.HF_SPACE_ID = ""
    bot.handlers.HF_SPACE_ID = ""
    # reload() doesn't delete existing attributes, so clear it first
    if hasattr(bot.handlers, "cmd_model"):
        delattr(bot.handlers, "cmd_model")
    importlib.reload(bot.handlers)
    assert not hasattr(bot.handlers, "cmd_model")


def test_handle_message_sends_typing():
    with patch("bot.handlers.should_respond", return_value=True), \
         patch("bot.handlers.is_rate_limited", return_value=False), \
         patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")), \
         patch("bot.handlers.ask_ai", return_value="reply"), \
         patch("bot.handlers.send_reply"), \
         patch("bot.handlers.bot") as mock_bot:
        from bot.handlers import handle_message
        msg = make_message()
        handle_message(msg)
        typing_calls = [c for c in mock_bot.send_chat_action.call_args_list
                        if c[0] == (456, "typing")]
        assert len(typing_calls) == 2
