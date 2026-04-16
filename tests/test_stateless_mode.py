"""Redis-down / unconfigured behavior across bot/ta/state.py.

When ``bot.clients.redis`` is None, every state function must return a
safe default rather than raise. This keeps the bot answering basic LLM
questions even when Upstash is unavailable.
"""
from __future__ import annotations

from unittest.mock import patch


def test_stateless_is_admin_only_permanent():
    with patch("bot.ta.state.redis", None):
        from bot.ta.state import is_admin
        assert is_admin("ediksimonian") is True
        assert is_admin("someoneelse") is False
        assert is_admin(None) is False


def test_stateless_list_admins_returns_permanent_only():
    with patch("bot.ta.state.redis", None):
        from bot.ta.state import list_admins
        assert list_admins() == ["ediksimonian"]


def test_stateless_add_admin_noop():
    with patch("bot.ta.state.redis", None):
        from bot.ta.state import add_admin
        # Permanent admin is a short-circuit True even in stateless mode.
        assert add_admin("ediksimonian") is True
        # Everyone else: _safe returns default (False).
        assert add_admin("alice") is False


def test_stateless_rate_limit_fails_open():
    with patch("bot.ta.state.redis", None):
        from bot.ta.state import ta_rate_check_and_inc, ta_rate_should_notify
        allowed, remaining = ta_rate_check_and_inc(42, limit=5)
        assert allowed is True
        assert remaining == 5
        assert ta_rate_should_notify(42) is True


def test_stateless_history_round_trip_empty():
    with patch("bot.ta.state.redis", None):
        from bot.ta.state import append_history, get_history, clear_history
        # Writes are no-ops; reads return [].
        append_history("g", "user", "hi")
        assert get_history("g") == []
        clear_history("g")  # no raise


def test_stateless_stats_round_trip_empty():
    with patch("bot.ta.state.redis", None):
        from bot.ta.state import (
            bump_message_count,
            get_group_stats,
            get_quiz_scores,
            get_total_quizzes,
            record_quiz_score,
        )
        bump_message_count("g", 1, "alice", "Alice")
        record_quiz_score("g", 1, "alice", "Alice", correct=True)
        assert get_group_stats("g") == {}
        assert get_quiz_scores("g") == {}
        assert get_total_quizzes("g") == 0


def test_stateless_welcome_gates_return_true_so_welcome_fires():
    """Without Redis we can't dedupe — send the welcome anyway."""
    with patch("bot.ta.state.redis", None):
        from bot.ta.state import mark_dm_welcomed, mark_group_welcomed
        assert mark_dm_welcomed(42) is True
        assert mark_group_welcomed(-100, "Cohort") is True


def test_stateless_groups_empty():
    with patch("bot.ta.state.redis", None):
        from bot.ta.state import (
            get_active_group_id,
            list_groups,
            register_group,
            unregister_group,
        )
        register_group(-100, "Cohort")    # no raise
        unregister_group(-100)             # no raise
        assert list_groups() == []
        assert get_active_group_id() is None


def test_stateless_active_quiz_none():
    with patch("bot.ta.state.redis", None):
        from bot.ta.state import (
            clear_active_quiz,
            get_active_quiz,
            set_active_quiz,
        )
        set_active_quiz(-100, {"correctAnswer": "A"})
        assert get_active_quiz(-100) is None
        clear_active_quiz(-100)


def test_stateless_streaks_and_reset_noop():
    with patch("bot.ta.state.redis", None):
        from bot.ta.state import (
            get_streak,
            reset_group_stats,
            update_streak,
        )
        assert get_streak("g", 1) == 0
        assert update_streak("g", 1, True) == 0
        reset_group_stats("g")  # no raise
