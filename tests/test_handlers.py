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
