from unittest.mock import patch, MagicMock, call


def make_message(chat_type="private", reply_from_id=None, text="hello"):
    message = MagicMock()
    message.chat.type = chat_type
    message.text = text
    message.reply_to_message = None
    if reply_from_id:
        message.reply_to_message = MagicMock()
        message.reply_to_message.from_user.id = reply_from_id
    return message


# ── send_reply ─────────────────────────────────────────────────────────────────

def test_send_reply_short_text():
    with patch("bot.helpers.bot") as mock_bot:
        with patch("bot.helpers.BOT_INFO", MagicMock(id=42, username="testbot")):
            from bot.helpers import send_reply
            msg = make_message()
            send_reply(msg, "Hello!")
            mock_bot.send_message.assert_called_once_with(msg.chat.id, "Hello!", parse_mode="Markdown")


def test_send_reply_splits_long_text():
    with patch("bot.helpers.bot") as mock_bot:
        with patch("bot.helpers.BOT_INFO", MagicMock(id=42, username="testbot")):
            with patch("bot.helpers.MAX_MSG_LEN", 10):
                from bot.helpers import send_reply
                msg = make_message()
                send_reply(msg, "A" * 25)
                assert mock_bot.send_message.call_count == 3


# ── should_respond ─────────────────────────────────────────────────────────────

def test_should_respond_private_chat():
    with patch("bot.helpers.BOT_INFO", MagicMock(id=42, username="testbot")):
        from bot.helpers import should_respond
        assert should_respond(make_message(chat_type="private")) is True


def test_should_respond_group_no_mention():
    with patch("bot.helpers.BOT_INFO", MagicMock(id=42, username="testbot")):
        from bot.helpers import should_respond
        assert should_respond(make_message(chat_type="group", text="just chatting")) is False


def test_should_respond_group_with_mention():
    with patch("bot.helpers.BOT_INFO", MagicMock(id=42, username="testbot")):
        from bot.helpers import should_respond
        msg = make_message(chat_type="group", text="hey @testbot what is Python?")
        assert should_respond(msg) is True


def test_should_respond_group_reply_to_bot():
    with patch("bot.helpers.BOT_INFO", MagicMock(id=42, username="testbot")):
        from bot.helpers import should_respond
        msg = make_message(chat_type="group", reply_from_id=42)
        assert should_respond(msg) is True


def test_should_respond_group_reply_to_other_user():
    with patch("bot.helpers.BOT_INFO", MagicMock(id=42, username="testbot")):
        from bot.helpers import should_respond
        msg = make_message(chat_type="group", reply_from_id=99)
        assert should_respond(msg) is False
