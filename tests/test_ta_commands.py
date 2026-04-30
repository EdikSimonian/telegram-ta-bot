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
        assert "<b>Workspace</b>" in text
        assert "Workspace Info" not in text
        assert "-100123" in text
        assert "@ediksimonian" in text


def test_info_title_is_workspace_even_without_active_group():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_active_group_id", return_value=None), \
         patch("bot.ta.commands.get_active_model", return_value=None):
        from bot.ta.commands import _cmd_info
        _cmd_info(_prepared(command="info"))
        text = sm.call_args.args[1]
        assert "<b>Workspace</b>" in text
        assert "Workspace Info" not in text
        assert "(none)" in text


# ── /vstats ───────────────────────────────────────────────────────────────
def test_vstats_shows_totals_and_namespaces():
    info = {
        "vector_count": 1234,
        "pending_vector_count": 5,
        "index_size": 2 * 1024 * 1024,
        "dimension": 1536,
        "similarity_function": "COSINE",
        "namespaces": {
            "prod": {"vector_count": 1000, "pending_vector_count": 0},
            "test": {"vector_count": 234,  "pending_vector_count": 5},
        },
    }
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.rag_mod.index_info", return_value=info), \
         patch("bot.ta.commands.VECTOR_NAMESPACE", "prod"):
        from bot.ta.commands import _cmd_vstats
        _cmd_vstats(_prepared(command="vstats"))
        text = sm.call_args.args[1]
        assert "1,234" in text
        assert "1536" in text
        assert "COSINE" in text
        assert "prod" in text and "test" in text
        assert "2.00 MB" in text


def test_vstats_passes_through_real_shape_from_upstash_info():
    """rag.index_info() reads from an attr-shaped InfoResult. This test
    goes through that path with a MagicMock-shaped vector_index so a rename
    on the Upstash SDK side (vector_count → something else) would surface."""
    from unittest.mock import MagicMock as _MM
    ns_prod = _MM(vector_count=900, pending_vector_count=0)
    ns_test = _MM(vector_count=100, pending_vector_count=2)
    info_obj = _MM(
        vector_count=1000,
        pending_vector_count=2,
        index_size=5 * 1024 * 1024,
        dimension=1536,
        similarity_function="COSINE",
        namespaces={"prod": ns_prod, "test": ns_test},
    )
    fake_index = _MM()
    fake_index.info.return_value = info_obj
    with patch("bot.ta.rag.vector_index", fake_index), \
         patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.VECTOR_NAMESPACE", "test"):
        from bot.ta.commands import _cmd_vstats
        _cmd_vstats(_prepared(command="vstats"))
        text = sm.call_args.args[1]
        assert "1,000" in text     # total vectors, thousands-separated
        assert "5.00 MB" in text   # index size
        assert "1536" in text      # dimension
        assert "COSINE" in text    # similarity function
        # Active namespace is "test" — marker sits on its per-namespace row
        # (format: "✅ <code>test</code> — 100"). The "Active ns:" header row
        # uses "Active ns:" prefix, so filter on the trailing vector count.
        test_line = next(
            ln for ln in text.splitlines()
            if "<code>test</code>" in ln and "100" in ln
        )
        assert "✅" in test_line


def test_vstats_unconfigured():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.rag_mod.index_info", return_value=None):
        from bot.ta.commands import _cmd_vstats
        _cmd_vstats(_prepared(command="vstats"))
        assert "not configured" in sm.call_args.args[1].lower()


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
        assert "gpt-5.5-nano" in text
        assert "gpt-5.5-mini" in text
        # Current (default) should be marked
        assert "(active)" in text
        # And only the active line carries the marker
        active_lines = [ln for ln in text.splitlines() if "(active)" in ln]
        assert len(active_lines) == 1
        assert "gpt-5.5-nano" in active_lines[0]


def test_model_no_args_marks_overridden_model_active():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_active_model", return_value="gpt-5.5-mini"):
        from bot.ta.commands import _cmd_model
        _cmd_model(_prepared(command="model"))
        text = sm.call_args.args[1]
        active_lines = [ln for ln in text.splitlines() if "(active)" in ln]
        assert len(active_lines) == 1
        assert "gpt-5.5-mini" in active_lines[0]


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
        _cmd_model(_prepared(command="model", command_args="gpt-5.5-mini"))
        sam.assert_called_once_with("-100123", "gpt-5.5-mini")
        assert "gpt-5.5-mini" in sm.call_args.args[1]


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


# ── /purge ────────────────────────────────────────────────────────────────
def test_purge_caps_range_to_500_messages():
    """Even with a high message_id, purge only attempts the most recent 500."""
    msg = MagicMock()
    msg.message_id = 60000
    p = _prepared(command="purge", is_dm=False)
    p.message = msg
    p.chat_id = -100123

    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_active_group_id", return_value="-100123"), \
         patch("bot.ta.commands._bot") as mock_bot, \
         patch("bot.ta.commands.reset_group_stats"):
        from bot.ta.commands import _cmd_purge
        _cmd_purge(p)
        # Should start at max(2, 60000-499)=59501, so 500 calls (59501..60000)
        assert mock_bot.delete_message.call_count == 500
        first_call_mid = mock_bot.delete_message.call_args_list[0].args[1]
        assert first_call_mid == 59501


def test_purge_small_chat_starts_at_2():
    """When message_id is small (< 501), range starts at 2."""
    msg = MagicMock()
    msg.message_id = 10
    p = _prepared(command="purge", is_dm=False)
    p.message = msg
    p.chat_id = -100123

    with patch("bot.ta.commands.send_message"), \
         patch("bot.ta.commands.get_active_group_id", return_value="-100123"), \
         patch("bot.ta.commands._bot") as mock_bot, \
         patch("bot.ta.commands.reset_group_stats"):
        from bot.ta.commands import _cmd_purge
        _cmd_purge(p)
        # range(2, 11) = 9 calls
        assert mock_bot.delete_message.call_count == 9
        first_call_mid = mock_bot.delete_message.call_args_list[0].args[1]
        assert first_call_mid == 2


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


# ── /feedback ────────────────────────────────────────────────────────────
def test_feedback_student_stores_text():
    """A non-admin student submitting feedback via the command handler."""
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.add_feedback") as af:
        from bot.ta.commands import _cmd_feedback
        p = _prepared(command="feedback", command_args="great class today", username="student1")
        p.is_admin = False
        _cmd_feedback(p)
        af.assert_called_once_with("great class today", "student1")
        assert "Feedback received" in sm.call_args.args[1]


def test_feedback_admin_stores_text():
    """An admin submitting feedback (no sub-command) also stores it."""
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.add_feedback") as af:
        from bot.ta.commands import _cmd_feedback
        p = _prepared(command="feedback", command_args="could be better")
        _cmd_feedback(p)
        af.assert_called_once_with("could be better", "alice")
        assert "Feedback received" in sm.call_args.args[1]


def test_feedback_list_returns_entries():
    entries = [
        {"text": "nice!", "username": "bob", "ts": 1},
        {"text": "more quizzes", "username": None, "ts": 2},
    ]
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.list_feedback", return_value=entries):
        from bot.ta.commands import _cmd_feedback
        _cmd_feedback(_prepared(command="feedback", command_args="list"))
        text = sm.call_args.args[1]
        assert "nice!" in text
        assert "more quizzes" in text
        assert "@bob" in text
        assert "(anon)" in text


def test_feedback_list_empty():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.list_feedback", return_value=[]):
        from bot.ta.commands import _cmd_feedback
        _cmd_feedback(_prepared(command="feedback", command_args="list"))
        assert "No feedback yet" in sm.call_args.args[1]


def test_feedback_clear():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.clear_feedback") as cf:
        from bot.ta.commands import _cmd_feedback
        _cmd_feedback(_prepared(command="feedback", command_args="clear"))
        cf.assert_called_once()
        assert "cleared" in sm.call_args.args[1].lower()


def test_feedback_no_text_shows_usage():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.add_feedback") as af:
        from bot.ta.commands import _cmd_feedback
        _cmd_feedback(_prepared(command="feedback", command_args=""))
        assert "Usage" in sm.call_args.args[1]
        af.assert_not_called()


# ── /roll ─────────────────────────────────────────────────────────────────
def test_roll_picks_integer_within_inclusive_bounds():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.random.randint", return_value=7) as ri:
        from bot.ta.commands import _cmd_roll
        _cmd_roll(_prepared(command="roll", command_args="1 15", is_dm=False))
        ri.assert_called_once_with(1, 15)
        chat_id, text = sm.call_args.args[0], sm.call_args.args[1]
        # Result posts to the same chat (group in this case).
        assert chat_id == -100123
        assert "7" in text
        assert "1" in text and "15" in text


def test_roll_handles_reversed_arguments():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.random.randint", return_value=5) as ri:
        from bot.ta.commands import _cmd_roll
        _cmd_roll(_prepared(command="roll", command_args="15 1"))
        # Bounds are normalized so low <= high before calling randint.
        ri.assert_called_once_with(1, 15)
        assert "5" in sm.call_args.args[1]


def test_roll_handles_equal_bounds():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.random.randint", return_value=5) as ri:
        from bot.ta.commands import _cmd_roll
        _cmd_roll(_prepared(command="roll", command_args="5 5"))
        ri.assert_called_once_with(5, 5)
        assert "5" in sm.call_args.args[1]


def test_roll_handles_negative_bounds():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.random.randint", return_value=-4) as ri:
        from bot.ta.commands import _cmd_roll
        _cmd_roll(_prepared(command="roll", command_args="-10 -1"))
        ri.assert_called_once_with(-10, -1)
        assert "-4" in sm.call_args.args[1]


def test_roll_in_dm_posts_to_dm_chat():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.random.randint", return_value=3):
        from bot.ta.commands import _cmd_roll
        _cmd_roll(_prepared(command="roll", command_args="1 6", is_dm=True, user_id=42))
        # DM invocation: result goes to the DM chat (== user_id for Telegram DMs).
        assert sm.call_args.args[0] == 42


def test_roll_missing_args_in_dm_replies_to_dm_chat():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.random.randint") as ri:
        from bot.ta.commands import _cmd_roll
        _cmd_roll(_prepared(command="roll", command_args="", user_id=42))
        ri.assert_not_called()
        # In DM, chat_id == user_id, so the usage reply lands in the DM.
        assert sm.call_args.args[0] == 42
        assert "Usage" in sm.call_args.args[1]


def test_roll_single_arg_shows_usage():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.random.randint") as ri:
        from bot.ta.commands import _cmd_roll
        _cmd_roll(_prepared(command="roll", command_args="7"))
        ri.assert_not_called()
        assert "Usage" in sm.call_args.args[1]


def test_roll_too_many_args_shows_usage():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.random.randint") as ri:
        from bot.ta.commands import _cmd_roll
        _cmd_roll(_prepared(command="roll", command_args="1 5 9"))
        ri.assert_not_called()
        assert "Usage" in sm.call_args.args[1]


def test_roll_non_integer_arg_shows_error():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.random.randint") as ri:
        from bot.ta.commands import _cmd_roll
        _cmd_roll(_prepared(command="roll", command_args="abc 15"))
        ri.assert_not_called()
        assert "integer" in sm.call_args.args[1].lower()


def test_roll_invalid_args_from_group_routes_to_chat():
    """Bad-args path in a group must reply to the group, not p.user_id —
    so we never depend on the admin having an open DM with the bot."""
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.random.randint") as ri:
        from bot.ta.commands import _cmd_roll
        _cmd_roll(_prepared(
            command="roll", command_args="abc 15", is_dm=False, user_id=42,
        ))
        ri.assert_not_called()
        assert sm.call_args.args[0] == -100123
        assert sm.call_args.args[0] != 42
        assert "integer" in sm.call_args.args[1].lower()


def test_roll_missing_args_from_group_routes_to_chat():
    """No-args usage path in a group also goes to the group, not p.user_id."""
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.random.randint") as ri:
        from bot.ta.commands import _cmd_roll
        _cmd_roll(_prepared(
            command="roll", command_args="", is_dm=False, user_id=42,
        ))
        ri.assert_not_called()
        assert sm.call_args.args[0] == -100123
        assert sm.call_args.args[0] != 42
        assert "Usage" in sm.call_args.args[1]


def test_roll_registered_in_dispatcher():
    from bot.ta.commands import _REGISTRY
    assert "roll" in _REGISTRY


def test_help_lists_roll_command():
    with patch("bot.ta.commands.send_message") as sm:
        from bot.ta.commands import _cmd_help
        _cmd_help(_prepared(command="help"))
        text = sm.call_args.args[1]
        assert "/roll" in text
