"""/announce two-step flow."""
from unittest.mock import MagicMock, patch


def _prepared(*, text="", command_args="", user_id=42, username="alice"):
    p = MagicMock()
    p.user_id = user_id
    p.username = username
    p.chat_id = user_id  # DM
    p.command = "announce"
    p.command_args = command_args
    p.text = text
    p.group_key = "-100123"
    p.is_dm = True
    return p


# ── start ─────────────────────────────────────────────────────────────────
def test_start_requires_message():
    with patch("bot.ta.announcements.send_message") as sm, \
         patch("bot.ta.announcements.set_pending_announcement") as spa:
        from bot.ta.announcements import start
        start(_prepared(command_args=""))
        spa.assert_not_called()
        assert "Usage" in sm.call_args.args[1]


def test_start_requires_active_group():
    with patch("bot.ta.announcements.send_message") as sm, \
         patch("bot.ta.announcements.get_active_group_id", return_value=None), \
         patch("bot.ta.announcements.set_pending_announcement") as spa:
        from bot.ta.announcements import start
        start(_prepared(command_args="Class cancelled"))
        spa.assert_not_called()
        assert "No active group" in sm.call_args.args[1]


def test_start_stages_and_previews():
    with patch("bot.ta.announcements.send_message") as sm, \
         patch("bot.ta.announcements.get_active_group_id", return_value="-100123"), \
         patch("bot.ta.announcements.set_pending_announcement") as spa:
        from bot.ta.announcements import start
        start(_prepared(command_args="Class cancelled Monday"))
        spa.assert_called_once_with(42, "Class cancelled Monday", "-100123")
        preview = sm.call_args.args[1]
        assert "Preview" in preview
        assert "Class cancelled Monday" in preview


# ── handle_reply ──────────────────────────────────────────────────────────
def test_handle_reply_returns_false_when_no_pending():
    with patch("bot.ta.announcements.get_pending_announcement", return_value=None):
        from bot.ta.announcements import handle_reply
        assert handle_reply(_prepared(text="whatever")) is False


def test_handle_reply_cancel_clears_and_consumes():
    with patch("bot.ta.announcements.send_message") as sm, \
         patch("bot.ta.announcements.get_pending_announcement",
               return_value={"text": "x", "groupChatId": "-100123"}), \
         patch("bot.ta.announcements.clear_pending_announcement") as cpa:
        from bot.ta.announcements import handle_reply
        assert handle_reply(_prepared(text="cancel")) is True
        cpa.assert_called_once_with(42)
        assert "cancelled" in sm.call_args.args[1].lower()


def test_handle_reply_send_it_posts_and_clears():
    with patch("bot.ta.announcements.send_message") as sm, \
         patch("bot.ta.announcements.get_pending_announcement",
               return_value={"text": "Class Monday", "groupChatId": "-100123"}), \
         patch("bot.ta.announcements.clear_pending_announcement") as cpa:
        from bot.ta.announcements import handle_reply
        assert handle_reply(_prepared(text="send it")) is True
        cpa.assert_called_once_with(42)
        targets = [c.args[0] for c in sm.call_args_list]
        assert "-100123" in targets  # posted to group
        assert 42 in targets          # confirmation DM


def test_handle_reply_send_it_handles_malformed_pending():
    with patch("bot.ta.announcements.send_message") as sm, \
         patch("bot.ta.announcements.get_pending_announcement",
               return_value={"text": "", "groupChatId": ""}), \
         patch("bot.ta.announcements.clear_pending_announcement") as cpa:
        from bot.ta.announcements import handle_reply
        assert handle_reply(_prepared(text="send it")) is True
        cpa.assert_called_once()
        assert "malformed" in sm.call_args.args[1].lower()


def test_handle_reply_other_text_falls_through_and_keeps_pending():
    with patch("bot.ta.announcements.send_message") as sm, \
         patch("bot.ta.announcements.get_pending_announcement",
               return_value={"text": "x", "groupChatId": "-100123"}), \
         patch("bot.ta.announcements.clear_pending_announcement") as cpa:
        from bot.ta.announcements import handle_reply
        assert handle_reply(_prepared(text="what's up")) is False
        cpa.assert_not_called()
        sm.assert_not_called()


def test_handle_reply_case_insensitive():
    with patch("bot.ta.announcements.send_message"), \
         patch("bot.ta.announcements.get_pending_announcement",
               return_value={"text": "x", "groupChatId": "-100123"}), \
         patch("bot.ta.announcements.clear_pending_announcement") as cpa:
        from bot.ta.announcements import handle_reply
        assert handle_reply(_prepared(text="SEND IT")) is True
        assert handle_reply(_prepared(text="Cancel")) is True
