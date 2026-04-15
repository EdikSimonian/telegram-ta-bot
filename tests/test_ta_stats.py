"""Engagement scoring + /stats /grade /purge command handlers."""
import time
from unittest.mock import MagicMock, patch


def _prepared(*, command_args="", group_key="-100123", is_dm=True, message_id=100):
    p = MagicMock()
    p.user_id = 42
    p.username = "alice"
    p.chat_id = 42 if is_dm else -100123
    p.command = "stats"
    p.command_args = command_args
    p.group_key = group_key
    p.is_dm = is_dm
    msg = MagicMock()
    msg.message_id = message_id
    p.message = msg
    return p


# ── stats_mod.compute ─────────────────────────────────────────────────────
def test_engagement_perfect_student():
    from bot.ta.stats import compute
    stat = {"messageCount": 50, "lastActive": int(time.time()), "username": "alice", "firstName": "Alice"}
    score = {"correct": 5, "total": 5}
    e = compute("42", stat, score, total_quizzes=5)
    # 20/20 * 30 + 5/5 * 40 + 5/5 * 30 = 100
    assert e.total_pts == 100.0
    assert e.inactive is False


def test_engagement_zero_for_no_data():
    from bot.ta.stats import compute
    e = compute("42", None, None, total_quizzes=0)
    assert e.total_pts == 0.0
    assert e.inactive is False  # no lastActive = not flagged


def test_engagement_inactive_flag_after_7_days():
    from bot.ta.stats import compute
    now = 10_000_000
    stat = {"messageCount": 5, "lastActive": now - 8 * 86400}
    e = compute("42", stat, None, total_quizzes=0, now=now)
    assert e.inactive is True


def test_engagement_participation_only_when_quizzes_exist():
    from bot.ta.stats import compute
    stat = {"messageCount": 0, "lastActive": 0}
    score = {"correct": 3, "total": 4}
    e = compute("42", stat, score, total_quizzes=4)
    # participation 4/4 * 40 = 40
    # accuracy 3/4 * 30 = 22.5
    assert e.particip_pts == 40.0
    assert round(e.accuracy_pts, 1) == 22.5


def test_engagement_message_cap():
    from bot.ta.stats import compute
    stat = {"messageCount": 1000, "lastActive": int(time.time())}
    e = compute("42", stat, None, total_quizzes=0)
    # capped at 20, full 30 points
    assert e.messages_pts == 30.0


# ── /stats ────────────────────────────────────────────────────────────────
def test_stats_empty_state():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_group_stats", return_value={}), \
         patch("bot.ta.commands.get_quiz_scores", return_value={}), \
         patch("bot.ta.commands.get_total_quizzes", return_value=0):
        from bot.ta.commands import _cmd_stats
        _cmd_stats(_prepared())
        assert "No stats" in sm.call_args.args[1]


def test_stats_sorts_messages_desc_and_scores_by_accuracy():
    stats = {
        "42": {"firstName": "Alice",  "messageCount": 10},
        "99": {"firstName": "Bob",    "messageCount": 3},
    }
    scores = {
        "42": {"firstName": "Alice", "correct": 1, "total": 4},    # 25%
        "99": {"firstName": "Bob",   "correct": 3, "total": 4},    # 75%
    }
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_group_stats", return_value=stats), \
         patch("bot.ta.commands.get_quiz_scores", return_value=scores), \
         patch("bot.ta.commands.get_total_quizzes", return_value=5):
        from bot.ta.commands import _cmd_stats
        _cmd_stats(_prepared())
        text = sm.call_args.args[1]
        # Alice has more messages → appears before Bob in Messages section
        a_idx, b_idx = text.index("Alice"), text.index("Bob")
        assert a_idx < b_idx
        # Bob has higher accuracy → appears before Alice in Quiz scores section
        # (second occurrence of each)
        a_idx2 = text.index("Alice", a_idx + 1)
        b_idx2 = text.index("Bob", b_idx + 1)
        assert b_idx2 < a_idx2


def test_stats_reset_clears_and_confirms():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.reset_group_stats") as rgs:
        from bot.ta.commands import _cmd_stats
        _cmd_stats(_prepared(command_args="reset"))
        rgs.assert_called_once_with("-100123")
        assert "Cleared" in sm.call_args.args[1]


# ── /grade ────────────────────────────────────────────────────────────────
def test_grade_no_data():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_group_stats", return_value={}), \
         patch("bot.ta.commands.get_quiz_scores", return_value={}), \
         patch("bot.ta.commands.get_total_quizzes", return_value=0):
        from bot.ta.commands import _cmd_grade
        _cmd_grade(_prepared())
        assert "No data" in sm.call_args.args[1]


def test_grade_group_summary_sorts_desc_by_total_pts():
    stats = {
        "42": {"firstName": "Alice",  "messageCount": 20, "lastActive": int(time.time())},
        "99": {"firstName": "Bob",    "messageCount": 5,  "lastActive": int(time.time())},
    }
    scores = {
        "42": {"firstName": "Alice", "correct": 3, "total": 3},
        "99": {"firstName": "Bob",   "correct": 0, "total": 3},
    }
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_group_stats", return_value=stats), \
         patch("bot.ta.commands.get_quiz_scores", return_value=scores), \
         patch("bot.ta.commands.get_total_quizzes", return_value=3):
        from bot.ta.commands import _cmd_grade
        _cmd_grade(_prepared())
        text = sm.call_args.args[1]
        # Alice should be above Bob
        assert text.index("Alice") < text.index("Bob")


def test_grade_single_user_detail():
    stats = {"42": {"username": "alice", "firstName": "Alice", "messageCount": 10, "lastActive": int(time.time())}}
    scores = {"42": {"username": "alice", "firstName": "Alice", "correct": 2, "total": 4}}
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_group_stats", return_value=stats), \
         patch("bot.ta.commands.get_quiz_scores", return_value=scores), \
         patch("bot.ta.commands.get_total_quizzes", return_value=5):
        from bot.ta.commands import _cmd_grade
        _cmd_grade(_prepared(command_args="@alice"))
        text = sm.call_args.args[1]
        assert "Alice" in text
        assert "Messages" in text
        assert "Accuracy" in text


def test_grade_unknown_user():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_group_stats", return_value={}), \
         patch("bot.ta.commands.get_quiz_scores", return_value={}), \
         patch("bot.ta.commands.get_total_quizzes", return_value=0):
        from bot.ta.commands import _cmd_grade
        _cmd_grade(_prepared(command_args="@ghost"))
        assert "No data for @ghost" in sm.call_args.args[1]


def test_grade_flags_inactive_students():
    now = int(time.time())
    stats = {
        "42": {"firstName": "Alice", "messageCount": 20, "lastActive": now - 10 * 86400},  # 10d stale
    }
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_group_stats", return_value=stats), \
         patch("bot.ta.commands.get_quiz_scores", return_value={}), \
         patch("bot.ta.commands.get_total_quizzes", return_value=0):
        from bot.ta.commands import _cmd_grade
        _cmd_grade(_prepared())
        text = sm.call_args.args[1]
        assert "⚠️" in text


# ── /purge ────────────────────────────────────────────────────────────────
def test_purge_refuses_when_message_id_too_low():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands._bot") as bot_mock, \
         patch("bot.ta.commands.reset_group_stats") as rgs:
        from bot.ta.commands import _cmd_purge
        _cmd_purge(_prepared(is_dm=False, message_id=1))
        bot_mock.delete_message.assert_not_called()
        rgs.assert_not_called()
        assert "Nothing to purge" in sm.call_args.args[1]


def test_purge_deletes_range_and_resets():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands._bot") as bot_mock, \
         patch("bot.ta.commands.reset_group_stats") as rgs:
        from bot.ta.commands import _cmd_purge
        _cmd_purge(_prepared(is_dm=False, message_id=10))
        # Deletes ids 2..10 inclusive
        assert bot_mock.delete_message.call_count == 9
        rgs.assert_called_once()


def test_purge_handles_supergroup_migration():
    import telebot  # already mocked via conftest

    call_count = {"n": 0}

    def _delete(chat_id, message_id):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise Exception("Bad Request: migrate_to_chat_id=-100999")
        return True

    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands._bot") as bot_mock, \
         patch("bot.ta.commands.reset_group_stats"):
        bot_mock.delete_message.side_effect = _delete
        from bot.ta.commands import _cmd_purge
        _cmd_purge(_prepared(is_dm=False, message_id=5))
        text = sm.call_args.args[1]
        assert "-100999" in text
