"""Thin telegram wrappers (bot/ta/tg.py)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_send_message_returns_message_id():
    fake_bot = MagicMock()
    fake_bot.send_message.return_value = MagicMock(message_id=42)
    with patch("bot.ta.tg.bot", fake_bot):
        from bot.ta.tg import send_message
        assert send_message(-100, "hi", parse_mode="HTML") == 42
        fake_bot.send_message.assert_called_once_with(-100, "hi", parse_mode="HTML")


def test_send_message_swallows_errors_returns_none():
    fake_bot = MagicMock()
    fake_bot.send_message.side_effect = RuntimeError("403 forbidden")
    with patch("bot.ta.tg.bot", fake_bot):
        from bot.ta.tg import send_message
        assert send_message(-100, "hi") is None


def test_send_message_missing_message_id_returns_none():
    fake_bot = MagicMock()
    # Some Telegram responses lack message_id (shouldn't, but defensive).
    resp = MagicMock(spec=[])
    fake_bot.send_message.return_value = resp
    with patch("bot.ta.tg.bot", fake_bot):
        from bot.ta.tg import send_message
        assert send_message(-100, "hi") is None


def test_delete_message_happy_path():
    fake_bot = MagicMock()
    with patch("bot.ta.tg.bot", fake_bot):
        from bot.ta.tg import delete_message
        assert delete_message(-100, 77) is True
        fake_bot.delete_message.assert_called_once_with(-100, 77)


def test_delete_message_swallows_errors_returns_false():
    fake_bot = MagicMock()
    fake_bot.delete_message.side_effect = RuntimeError("message too old")
    with patch("bot.ta.tg.bot", fake_bot):
        from bot.ta.tg import delete_message
        assert delete_message(-100, 77) is False


def test_set_reaction_uses_telebot_types():
    fake_bot = MagicMock()
    with patch("bot.ta.tg.bot", fake_bot):
        from bot.ta.tg import set_reaction
        assert set_reaction(-100, 5, "🫡") is True
        fake_bot.set_message_reaction.assert_called_once()


def test_set_reaction_returns_false_on_error():
    fake_bot = MagicMock()
    fake_bot.set_message_reaction.side_effect = RuntimeError("bad request")
    with patch("bot.ta.tg.bot", fake_bot):
        from bot.ta.tg import set_reaction
        assert set_reaction(-100, 5, "🤔") is False
