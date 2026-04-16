"""Welcome flows (bot/ta/welcome.py)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_dm_welcome_sends_once_then_never_again():
    fake_bot = MagicMock()
    with patch("bot.ta.welcome.bot", fake_bot), \
         patch("bot.ta.welcome.mark_dm_welcomed", side_effect=[True, False]):
        from bot.ta.welcome import send_dm_welcome_once
        assert send_dm_welcome_once(42, 42) is True
        assert fake_bot.send_message.call_count == 1
        # Second invocation: gate returns False → no send.
        assert send_dm_welcome_once(42, 42) is False
        assert fake_bot.send_message.call_count == 1


def test_dm_welcome_swallows_send_errors():
    fake_bot = MagicMock()
    fake_bot.send_message.side_effect = RuntimeError("can't initiate DM")
    with patch("bot.ta.welcome.bot", fake_bot), \
         patch("bot.ta.welcome.mark_dm_welcomed", return_value=True):
        from bot.ta.welcome import send_dm_welcome_once
        assert send_dm_welcome_once(42, 42) is False


def test_group_welcome_registers_and_sends_once():
    fake_bot = MagicMock()
    with patch("bot.ta.welcome.bot", fake_bot), \
         patch("bot.ta.welcome.register_group") as reg, \
         patch("bot.ta.welcome.mark_group_welcomed", side_effect=[True, False]):
        from bot.ta.welcome import send_group_welcome_once
        send_group_welcome_once(-100, "Cohort A")
        send_group_welcome_once(-100, "Cohort A")
        # register_group always fires (it's idempotent upstream).
        assert reg.call_count == 2
        # Send only the first time.
        assert fake_bot.send_message.call_count == 1


def test_group_welcome_swallows_errors():
    fake_bot = MagicMock()
    fake_bot.send_message.side_effect = RuntimeError("bot not in chat")
    with patch("bot.ta.welcome.bot", fake_bot), \
         patch("bot.ta.welcome.register_group"), \
         patch("bot.ta.welcome.mark_group_welcomed", return_value=True):
        from bot.ta.welcome import send_group_welcome_once
        # Should not raise.
        send_group_welcome_once(-100, "Cohort A")


def test_welcome_copy_mentions_permanent_admin():
    from bot.ta.welcome import DM_WELCOME, GROUP_WELCOME
    assert "@ediksimonian" in GROUP_WELCOME
    assert "@ediksimonian" in DM_WELCOME
