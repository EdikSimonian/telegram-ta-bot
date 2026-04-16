"""Stage 3 admin command handlers.

Commands expect a ``Prepared`` dataclass; router gating is tested
elsewhere in test_ta_admin.py. Each test asserts what the command
writes to Telegram + to Redis state.
"""
from unittest.mock import MagicMock, patch


def _prepared(
    *,
    user_id=42,
    username="alice",
    command="",
    command_args="",
    group_key="-100123",
    is_dm=True,
):
    p = MagicMock()
    p.user_id = user_id
    p.username = username
    p.chat_id = user_id if is_dm else -100123
    p.command = command
    p.command_args = command_args
    p.group_key = group_key
    p.is_dm = is_dm
    return p


# ── /help ─────────────────────────────────────────────────────────────────
def test_help_lists_commands_without_models_section():
    with patch("bot.ta.commands.send_message") as sm:
        from bot.ta.commands import _cmd_help
        _cmd_help(_prepared(command="help"))
        text = sm.call_args.args[1]
        assert "/help" in text
        assert "/admin add" in text
        assert "/group" in text
        # /help no longer dumps the model list — that's /model's job.
        assert "Valid models" not in text


# ── /info ─────────────────────────────────────────────────────────────────
def test_info_shows_env_and_group():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_active_group_id", return_value="-100123"), \
         patch("bot.ta.commands.get_active_model", return_value=None):
        from bot.ta.commands import _cmd_info
        _cmd_info(_prepared(command="info"))
        text = sm.call_args.args[1]
        assert "-100123" in text
        assert "@ediksimonian" in text


# ── /admin (list) ─────────────────────────────────────────────────────────
def test_admin_bare_lists_admins():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.list_admins", return_value=["ediksimonian", "alice"]):
        from bot.ta.commands import _cmd_admin
        _cmd_admin(_prepared(command="admin", command_args=""))
        text = sm.call_args.args[1]
        assert "@ediksimonian" in text
        assert "@alice" in text


def test_admin_list_subcommand():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.list_admins", return_value=["ediksimonian"]):
        from bot.ta.commands import _cmd_admin
        _cmd_admin(_prepared(command="admin", command_args="list"))
        assert "@ediksimonian" in sm.call_args.args[1]


# ── /admin add ────────────────────────────────────────────────────────────
def test_admin_add_requires_username():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.add_admin") as add:
        from bot.ta.commands import _cmd_admin
        _cmd_admin(_prepared(command="admin", command_args="add"))
        assert "Usage" in sm.call_args.args[1]
        add.assert_not_called()


def test_admin_add_happy_path():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.add_admin", return_value=True), \
         patch("bot.ta.commands.get_user_chat", return_value=None):
        from bot.ta.commands import _cmd_admin
        _cmd_admin(_prepared(command="admin", command_args="add @bob"))
        assert any("@bob" in c.args[1] for c in sm.call_args_list)


def test_admin_add_dms_new_ta_if_known():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.add_admin", return_value=True), \
         patch("bot.ta.commands.get_user_chat", return_value="9001"):
        from bot.ta.commands import _cmd_admin
        _cmd_admin(_prepared(command="admin", command_args="add @bob"))
        dmed = [c for c in sm.call_args_list if c.args[0] == "9001"]
        assert len(dmed) == 1


# ── /admin remove ─────────────────────────────────────────────────────────
def test_admin_remove_blocks_permanent():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.remove_admin") as rm:
        from bot.ta.commands import _cmd_admin
        _cmd_admin(_prepared(command="admin", command_args="remove @ediksimonian"))
        assert "permanent" in sm.call_args.args[1].lower()
        rm.assert_not_called()


def test_admin_remove_blocks_self():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.remove_admin") as rm:
        from bot.ta.commands import _cmd_admin
        _cmd_admin(_prepared(
            command="admin", username="alice", command_args="remove @alice",
        ))
        assert "yourself" in sm.call_args.args[1].lower()
        rm.assert_not_called()


def test_admin_remove_happy_path():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.remove_admin", return_value=True):
        from bot.ta.commands import _cmd_admin
        _cmd_admin(_prepared(
            command="admin", username="alice", command_args="remove @bob",
        ))
        assert "@bob" in sm.call_args.args[1]


def test_admin_unknown_subcommand_shows_usage():
    with patch("bot.ta.commands.send_message") as sm:
        from bot.ta.commands import _cmd_admin
        _cmd_admin(_prepared(command="admin", command_args="foo"))
        assert "Usage" in sm.call_args.args[1]


# ── /reset ────────────────────────────────────────────────────────────────
def test_reset_clears_history_and_model():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.clear_history") as ch, \
         patch("bot.ta.commands.clear_active_model") as cm:
        from bot.ta.commands import _cmd_reset
        p = _prepared(command="reset", group_key="-100123")
        _cmd_reset(p)
        ch.assert_called_once_with("-100123")
        cm.assert_called_once_with("-100123")
        assert "-100123" in sm.call_args.args[1]


# ── /model ────────────────────────────────────────────────────────────────
def test_model_no_args_lists_all_with_active_marker():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_active_model", return_value=None):
        from bot.ta.commands import _cmd_model
        _cmd_model(_prepared(command="model"))
        text = sm.call_args.args[1]
        assert "gpt-5.4-nano" in text
        assert "gpt-5.4-mini" in text
        # Current (default) should be marked
        assert "(active)" in text
        # And only the active line carries the marker
        active_lines = [ln for ln in text.splitlines() if "(active)" in ln]
        assert len(active_lines) == 1
        assert "gpt-5.4-nano" in active_lines[0]


def test_model_no_args_marks_overridden_model_active():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_active_model", return_value="gpt-5.4-mini"):
        from bot.ta.commands import _cmd_model
        _cmd_model(_prepared(command="model"))
        text = sm.call_args.args[1]
        active_lines = [ln for ln in text.splitlines() if "(active)" in ln]
        assert len(active_lines) == 1
        assert "gpt-5.4-mini" in active_lines[0]


def test_model_invalid_rejected():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.set_active_model") as sam:
        from bot.ta.commands import _cmd_model
        _cmd_model(_prepared(command="model", command_args="gpt-9000"))
        assert "Invalid" in sm.call_args.args[1]
        sam.assert_not_called()


def test_model_valid_persists():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.set_active_model") as sam:
        from bot.ta.commands import _cmd_model
        _cmd_model(_prepared(command="model", command_args="gpt-5.4-mini"))
        sam.assert_called_once_with("-100123", "gpt-5.4-mini")
        assert "gpt-5.4-mini" in sm.call_args.args[1]


# ── /group ────────────────────────────────────────────────────────────────
def test_group_no_args_lists():
    groups = [
        {"chatId": "-100123", "title": "Workshop"},
        {"chatId": "-100456", "title": "Other"},
    ]
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.list_groups", return_value=groups), \
         patch("bot.ta.commands.get_active_group_id", return_value="-100123"), \
         patch("bot.ta.commands.set_active_group_id") as sag:
        from bot.ta.commands import _cmd_group
        _cmd_group(_prepared(command="group"))
        text = sm.call_args.args[1]
        assert "-100123" in text
        assert "Workshop" in text
        sag.assert_not_called()


def test_group_list_subcommand_same_as_bare():
    groups = [{"chatId": "-100123", "title": "Workshop"}]
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.list_groups", return_value=groups), \
         patch("bot.ta.commands.get_active_group_id", return_value="-100123"), \
         patch("bot.ta.commands.set_active_group_id") as sag:
        from bot.ta.commands import _cmd_group
        _cmd_group(_prepared(command="group", command_args="list"))
        assert "Workshop" in sm.call_args.args[1]
        sag.assert_not_called()


def test_group_by_index_switches():
    groups = [
        {"chatId": "-100123", "title": "Workshop"},
        {"chatId": "-100456", "title": "Other"},
    ]
    with patch("bot.ta.commands.send_message"), \
         patch("bot.ta.commands.list_groups", return_value=groups), \
         patch("bot.ta.commands.get_active_group_id", return_value="-100123"), \
         patch("bot.ta.commands.set_active_group_id") as sag:
        from bot.ta.commands import _cmd_group
        _cmd_group(_prepared(command="group", command_args="2"))
        sag.assert_called_once_with("-100456")


def test_group_by_chat_id_switches():
    groups = [
        {"chatId": "-100123", "title": "Workshop"},
        {"chatId": "-100456", "title": "Other"},
    ]
    with patch("bot.ta.commands.send_message"), \
         patch("bot.ta.commands.list_groups", return_value=groups), \
         patch("bot.ta.commands.get_active_group_id", return_value="-100123"), \
         patch("bot.ta.commands.set_active_group_id") as sag:
        from bot.ta.commands import _cmd_group
        _cmd_group(_prepared(command="group", command_args="-100456"))
        sag.assert_called_once_with("-100456")


def test_group_unknown_rejected():
    groups = [{"chatId": "-100123", "title": "Workshop"}]
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.list_groups", return_value=groups), \
         patch("bot.ta.commands.get_active_group_id", return_value="-100123"), \
         patch("bot.ta.commands.set_active_group_id") as sag:
        from bot.ta.commands import _cmd_group
        _cmd_group(_prepared(command="group", command_args="999"))
        assert "No linked group matches" in sm.call_args.args[1]
        sag.assert_not_called()


# ── dispatch ──────────────────────────────────────────────────────────────
def test_dispatch_unknown_command_replies_not_implemented():
    with patch("bot.ta.commands.send_message") as sm:
        from bot.ta.commands import dispatch
        dispatch(_prepared(command="nosuchthing"))
        text = sm.call_args.args[1].lower()
        assert "not-yet-implemented" in text or "unknown" in text


def test_dispatch_routes_to_registered_handler():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.list_admins", return_value=["ediksimonian"]):
        from bot.ta.commands import dispatch
        dispatch(_prepared(command="admin"))
        assert "@ediksimonian" in sm.call_args.args[1]
