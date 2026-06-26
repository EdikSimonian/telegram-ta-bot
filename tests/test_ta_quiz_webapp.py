"""Quiz Mini App mode: parsing, per-user shuffle, serve/grade, start_quiz."""

import time
from unittest.mock import MagicMock, patch

import pytest

CHAT = -100123
MSG = 77
RAW = "QUESTION: What is 2+2?\nA) 3\nB) 4\nC) 5\nD) 22\nANSWER: B"


@pytest.fixture(autouse=True)
def _allow_membership():
    """Default every test to "caller is a group member" so the anti-share gate
    in serve_quiz/submit_answer passes. Tests that exercise the gate itself
    re-patch is_chat_member=False locally (the inner patch wins)."""
    with patch("bot.ta.quiz.is_chat_member", return_value=True):
        yield


def _prepared(*, user_id=42, is_dm=True):
    p = MagicMock()
    p.user_id = user_id
    p.username = "alice"
    p.first_name = "Alice"
    p.chat_id = CHAT
    p.group_key = str(CHAT)
    p.is_dm = is_dm
    return p


def _active(**over):
    base = {
        "questionMessageId": MSG,
        "correctAnswer": "B",
        "correctIndex": 1,
        "question": "What is 2+2?",
        "options": ["3", "4", "5", "22"],
        "mode": "webapp",
        "token": "tok123",
        "answers": {},
        "startTime": int(time.time()),
    }
    base.update(over)
    return base


# ── parse_question_parts ──────────────────────────────────────────────────
def test_parse_question_parts_happy():
    from bot.ta.quiz import parse_question_parts

    out = parse_question_parts(RAW)
    assert out == {
        "question": "What is 2+2?",
        "options": ["3", "4", "5", "22"],
        "correctIndex": 1,
        "topic": "",  # no TOPIC line in RAW
    }


def test_parse_question_parts_missing_option_returns_none():
    from bot.ta.quiz import parse_question_parts

    assert parse_question_parts("QUESTION: x\nA) a\nB) b\nANSWER: A") is None


def test_parse_question_parts_no_answer_returns_none():
    from bot.ta.quiz import parse_question_parts

    assert parse_question_parts("QUESTION: x\nA) a\nB) b\nC) c\nD) d") is None


# ── per-user option order ─────────────────────────────────────────────────
def test_user_option_order_is_permutation_and_deterministic():
    from bot.ta.quiz import _user_option_order

    o1 = _user_option_order(CHAT, MSG, 42)
    o2 = _user_option_order(CHAT, MSG, 42)
    assert o1 == o2  # deterministic
    assert sorted(o1) == [0, 1, 2, 3]  # bijection over the 4 options


def test_user_option_order_varies_by_user():
    from bot.ta.quiz import _user_option_order

    # Some pair of distinct users must get a different order, else the
    # shuffle gives no anti-cheat value.
    orders = {u: tuple(_user_option_order(CHAT, MSG, u)) for u in range(20)}
    assert len(set(orders.values())) > 1


# ── submit_answer ─────────────────────────────────────────────────────────
def _patches(active, *, answered=False, answers=None):
    return (
        patch("bot.ta.quiz.get_quiz_token_chat", return_value=str(CHAT)),
        patch("bot.ta.quiz.get_active_quiz", return_value=active),
        patch("bot.ta.quiz.has_quiz_answer", return_value=answered),
        patch("bot.ta.quiz.get_quiz_answers", return_value=answers or {}),
    )


def test_submit_correct_position_scores_right():
    from bot.ta.quiz import _user_option_order, submit_answer

    active = _active()
    order = _user_option_order(CHAT, MSG, 42)
    correct_pos = order.index(1)  # canonical index 1 == "B"
    p1, p2, p3, p4 = _patches(active)
    with p1, p2, p3, p4, patch("bot.ta.quiz.record_quiz_answer_nx") as rec:
        out = submit_answer("tok123", {"id": 42, "first_name": "Alice"}, correct_pos)
    assert out["ok"] is True
    assert out["accepted"] is True
    assert "correct" not in out  # verdict withheld until the quiz ends
    # Recorded as the canonical letter so reveal_now tallies correctly.
    assert rec.call_args.args[2]["letter"] == "B"


def test_submit_wrong_position_scores_wrong():
    from bot.ta.quiz import _user_option_order, submit_answer

    active = _active()
    order = _user_option_order(CHAT, MSG, 42)
    wrong_pos = (order.index(1) + 1) % 4
    p1, p2, p3, p4 = _patches(active)
    with p1, p2, p3, p4, patch("bot.ta.quiz.record_quiz_answer_nx") as rec:
        out = submit_answer("tok123", {"id": 42}, wrong_pos)
    assert out["accepted"] is True
    assert "correct" not in out  # no verdict at answer time
    assert rec.call_args.args[2]["letter"] != "B"


def test_submit_is_one_shot():
    from bot.ta.quiz import submit_answer

    active = _active()
    answers = {"42": {"letter": "A"}}  # already answered with canonical "A"
    p1, p2, p3, p4 = _patches(active, answered=True, answers=answers)
    with p1, p2, p3, p4, patch("bot.ta.quiz.record_quiz_answer_nx") as rec:
        out = submit_answer("tok123", {"id": 42}, 0)
    assert out["accepted"] is True
    assert out["alreadyAnswered"] is True
    assert "correct" not in out  # no verdict, even on re-tap
    rec.assert_not_called()  # no overwrite


def test_submit_bad_token_ended():
    from bot.ta.quiz import submit_answer

    with patch("bot.ta.quiz.get_quiz_token_chat", return_value=None):
        out = submit_answer("nope", {"id": 42}, 0)
    assert out["ok"] is False
    assert out["error"] == "ended"


def test_submit_empty_token_is_no_token():
    from bot.ta.quiz import submit_answer

    out = submit_answer("", {"id": 42}, 0)
    assert out["error"] == "no_token"


def test_serve_empty_token_is_no_token():
    from bot.ta.quiz import serve_quiz

    assert serve_quiz("", {"id": 42})["error"] == "no_token"


def test_serve_pending_when_expired_no_result_yet():
    from bot.ta.quiz import serve_quiz

    active = _active(startTime=1)  # ancient → expired, not yet revealed
    p1, p2, p3, p4 = _patches(active)
    with p1, p2, p3, p4, patch("bot.ta.state.get_quiz_result", return_value=None):
        out = serve_quiz("tok123", {"id": 42})
    assert out["ok"] is True
    assert out["state"] == "pending"


def test_submit_rejects_out_of_range_position():
    from bot.ta.quiz import submit_answer

    active = _active()
    p1, p2, p3, p4 = _patches(active)
    with p1, p2, p3, p4, patch("bot.ta.quiz.record_quiz_answer_nx"):
        assert submit_answer("tok123", {"id": 42}, 9)["error"] == "bad_position"


# ── serve_quiz ────────────────────────────────────────────────────────────
def test_serve_live_returns_shuffled_options_no_verdict():
    from bot.ta.quiz import serve_quiz

    active = _active()
    p1, p2, p3, p4 = _patches(active)  # answered=False
    with p1, p2, p3, p4:
        out = serve_quiz("tok123", {"id": 42})
    assert out["state"] == "live"
    # No verdict / correct option leaked while the quiz is running.
    assert "correct" not in out and "correctOption" not in out
    assert sorted(out["options"]) == ["22", "3", "4", "5"]  # all 4, some order


def test_serve_accepted_when_answered_and_live():
    from bot.ta.quiz import serve_quiz

    active = _active()
    answers = {"42": {"letter": "B"}}
    p1, p2, p3, p4 = _patches(active, answered=True, answers=answers)
    with p1, p2, p3, p4:
        out = serve_quiz("tok123", {"id": 42})
    assert out["state"] == "accepted"
    assert "correct" not in out  # still no verdict while the quiz runs
    assert "options" not in out  # don't re-serve the question


def test_serve_ended_shows_each_students_own_result():
    from bot.ta.quiz import serve_quiz

    result = {
        "correctIndex": 1,
        "options": ["3", "4", "5", "22"],
        "answers": {"42": "B", "99": "C"},
    }
    # No active quiz (revealed) → serve reads the persisted result snapshot.
    with (
        patch("bot.ta.quiz.get_quiz_token_chat", return_value=None),
        patch("bot.ta.state.get_quiz_result", return_value=result),
    ):
        right = serve_quiz("tok123", {"id": 42})
        wrong = serve_quiz("tok123", {"id": 99})
        none = serve_quiz("tok123", {"id": 7})  # didn't answer
    assert right["state"] == "ended"
    assert right["answered"] is True and right["correct"] is True
    assert right["correctOption"] == "4"
    assert wrong["correct"] is False
    assert wrong["yourOption"] == "5" and wrong["correctOption"] == "4"
    assert none["answered"] is False and none["correctOption"] == "4"


# ── start_quiz web-app path ───────────────────────────────────────────────
def test_start_quiz_webapp_posts_button_and_stores_mode():
    with (
        patch("bot.ta.quiz.QUIZ_WEBAPP_ENABLED", True),
        patch("bot.ta.quiz.get_active_quiz", return_value=None),
        patch("bot.ta.quiz.generate_question", return_value=(RAW, "B")),
        patch("bot.ta.quiz.send_message", return_value=MSG) as sm,
        patch("bot.ta.quiz.set_active_quiz") as set_q,
        patch("bot.ta.quiz.set_quiz_token") as set_tok,
        patch("bot.ta.quiz.push_quiz_history"),
        patch("bot.ta.quiz.bump_total_quizzes"),
        patch("bot.ta.quiz._schedule_autoreveal", return_value=True),
        patch("bot.ta.quiz.schedule_quiz_tick") as tick,
    ):
        from bot.ta.quiz import start_quiz

        start_quiz(_prepared(), "math", CHAT)

        state = set_q.call_args.args[1]
        assert state["mode"] == "webapp"
        tick.assert_called_once()  # live answered-counter started
        assert state["options"] == ["3", "4", "5", "22"]
        assert state["correctIndex"] == 1
        assert state["correctAnswer"] == "B"  # keeps reveal_now working
        token = state["token"]
        # Token registered for resolution, and the group message carries a button.
        set_tok.assert_called_once()
        assert set_tok.call_args.args[0] == token
        group_msg = sm.call_args_list[0]
        assert group_msg.kwargs.get("reply_markup") is not None
        # Question-in-app-only: the question text must NOT leak into the group.
        group_text = group_msg.args[1]
        assert "2+2" not in group_text
        assert "QUIZ TIME" in group_text
        # Instructional line removed — the button speaks for itself.
        assert "Open quiz" not in group_text
        assert "private" not in group_text
        assert "minute" not in group_text


def test_start_quiz_falls_back_to_text_when_disabled():
    with (
        patch("bot.ta.quiz.QUIZ_WEBAPP_ENABLED", False),
        patch("bot.ta.quiz.get_active_quiz", return_value=None),
        patch("bot.ta.quiz.generate_question", return_value=(RAW, "B")),
        patch("bot.ta.quiz.send_message", return_value=MSG),
        patch("bot.ta.quiz.set_active_quiz") as set_q,
        patch("bot.ta.quiz.push_quiz_history"),
        patch("bot.ta.quiz.bump_total_quizzes"),
        patch("bot.ta.quiz._schedule_autoreveal", return_value=True),
    ):
        from bot.ta.quiz import start_quiz

        start_quiz(_prepared(), "math", CHAT)
        state = set_q.call_args.args[1]
        assert "mode" not in state  # legacy text quiz
        assert "options" not in state


# ── reveal expires the group message ──────────────────────────────────────
def test_reveal_expires_webapp_message_and_drops_button():
    active = _active(questionMessageId=699, topic="python")
    with (
        patch("bot.ta.quiz.get_active_quiz", return_value=active),
        patch("bot.ta.quiz.get_quiz_answers", return_value={}),
        patch("bot.ta.quiz.record_quiz_score"),
        patch("bot.ta.quiz.update_streak", return_value=0),
        patch("bot.ta.quiz.clear_active_quiz"),
        patch("bot.ta.quiz.send_message"),
        patch("bot.ta.tg.edit_message_quiet") as edit,
    ):
        from bot.ta.quiz import reveal_now

        assert reveal_now(CHAT) is True
        edit.assert_called_once()
        args, kwargs = edit.call_args
        assert args[0] == CHAT and args[1] == 699
        assert "expired" in args[2].lower() or "ended" in args[2].lower()
        # No reply_markup passed → Telegram drops the inline button.
        assert "reply_markup" not in kwargs


def test_reveal_writes_result_snapshot():
    active = _active(questionMessageId=699, token="tok123")
    answers = {
        "42": {"letter": "B", "firstName": "Alice"},
        "99": {"letter": "C", "firstName": "Bob"},
    }
    with (
        patch("bot.ta.quiz.get_active_quiz", return_value=active),
        patch("bot.ta.quiz.get_quiz_answers", return_value=answers),
        patch("bot.ta.quiz.record_quiz_score"),
        patch("bot.ta.quiz.update_streak", return_value=0),
        patch("bot.ta.quiz.clear_active_quiz"),
        patch("bot.ta.quiz.send_message"),
        patch("bot.ta.tg.edit_message_quiet"),
        patch("bot.ta.state.set_quiz_result") as setres,
    ):
        from bot.ta.quiz import reveal_now

        reveal_now(CHAT)
        setres.assert_called_once()
        tok, data = setres.call_args.args[0], setres.call_args.args[1]
        assert tok == "tok123"
        assert data["correctIndex"] == 1
        assert data["options"] == ["3", "4", "5", "22"]
        assert data["answers"] == {"42": "B", "99": "C"}


def test_reveal_legacy_quiz_does_not_edit_message():
    active = {  # legacy text quiz — no mode
        "correctAnswer": "B",
        "answers": {},
        "startTime": int(time.time()),
        "questionMessageId": 5,
    }
    with (
        patch("bot.ta.quiz.get_active_quiz", return_value=active),
        patch("bot.ta.quiz.get_quiz_answers", return_value={}),
        patch("bot.ta.quiz.clear_active_quiz"),
        patch("bot.ta.quiz.send_message"),
        patch("bot.ta.tg.edit_message_quiet") as edit,
    ):
        from bot.ta.quiz import reveal_now

        reveal_now(CHAT)
        edit.assert_not_called()


# ── is_webapp_quiz ────────────────────────────────────────────────────────
def test_is_webapp_quiz():
    from bot.ta.quiz import is_webapp_quiz

    with patch("bot.ta.quiz.get_active_quiz", return_value=_active()):
        assert is_webapp_quiz(CHAT) is True
    with patch("bot.ta.quiz.get_active_quiz", return_value={"correctAnswer": "B"}):
        assert is_webapp_quiz(CHAT) is False
    with patch("bot.ta.quiz.get_active_quiz", return_value=None):
        assert is_webapp_quiz(CHAT) is False


# ── generated topic ───────────────────────────────────────────────────────
def test_parse_question_parts_extracts_topic():
    from bot.ta.quiz import parse_question_parts

    raw = RAW + "\nTOPIC: Basic Arithmetic"
    out = parse_question_parts(raw)
    assert out["topic"] == "Basic Arithmetic"
    assert out["question"] == "What is 2+2?"  # TOPIC not folded into the stem


def test_start_quiz_webapp_uses_generated_topic():
    raw = "QUESTION: q?\nA) a\nB) b\nC) c\nD) d\nANSWER: A\nTOPIC: Recursion Basics"
    with (
        patch("bot.ta.quiz.QUIZ_WEBAPP_ENABLED", True),
        patch("bot.ta.quiz.get_active_quiz", return_value=None),
        patch("bot.ta.quiz.generate_question", return_value=(raw, "A")),
        patch("bot.ta.quiz.send_message", return_value=MSG) as sm,
        patch("bot.ta.quiz.set_active_quiz") as set_q,
        patch("bot.ta.quiz.set_quiz_token"),
        patch("bot.ta.quiz.push_quiz_history"),
        patch("bot.ta.quiz.bump_total_quizzes"),
        patch("bot.ta.quiz._schedule_autoreveal", return_value=True),
        patch("bot.ta.quiz.schedule_quiz_tick"),
    ):
        from bot.ta.quiz import start_quiz

        start_quiz(_prepared(), "", CHAT)  # no instructor topic
        assert "Recursion Basics" in sm.call_args_list[0].args[1]
        assert set_q.call_args.args[1]["topic"] == "Recursion Basics"


# ── live answered-counter (tick_quiz) ─────────────────────────────────────
def test_tick_quiz_edits_count_and_keeps_button():
    active = _active(questionMessageId=MSG, topic="python")
    with (
        patch("bot.ta.quiz.get_active_quiz", return_value=active),
        patch("bot.ta.state.count_quiz_answers", return_value=3),
        patch("bot.ta.tg.edit_message_quiet") as edit,
    ):
        from bot.ta.quiz import tick_quiz

        assert tick_quiz(CHAT, MSG, "tok123") is True
        args, kwargs = edit.call_args
        assert args[0] == CHAT and args[1] == MSG
        assert "3" in args[2] and "answered" in args[2]
        assert kwargs.get("reply_markup") is not None  # button preserved


def test_tick_quiz_stops_when_gone_replaced_or_expired():
    from bot.ta.quiz import tick_quiz

    with patch("bot.ta.quiz.get_active_quiz", return_value=None):
        assert tick_quiz(CHAT, MSG, "tok123") is False
    with patch(
        "bot.ta.quiz.get_active_quiz", return_value=_active(questionMessageId=999)
    ):
        assert tick_quiz(CHAT, MSG, "tok123") is False  # newer quiz, different msg
    with patch("bot.ta.quiz.get_active_quiz", return_value=_active(startTime=1)):
        assert tick_quiz(CHAT, MSG, "tok123") is False  # expired


def test_count_quiz_answers_uses_hlen():
    import bot.ta.state as state

    with patch.object(state, "redis") as r:
        r.hlen.return_value = 4
        assert state.count_quiz_answers(CHAT) == 4


# ── reveal spells out question + full answer ──────────────────────────────
def test_reveal_webapp_message_has_question_and_full_answer():
    active = _active(questionMessageId=699, token="tok123")
    with (
        patch("bot.ta.quiz.get_active_quiz", return_value=active),
        patch("bot.ta.quiz.get_quiz_answers", return_value={}),
        patch("bot.ta.quiz.record_quiz_score"),
        patch("bot.ta.quiz.update_streak", return_value=0),
        patch("bot.ta.quiz.clear_active_quiz"),
        patch("bot.ta.quiz.send_message") as sm,
        patch("bot.ta.tg.edit_message_quiet"),
        patch("bot.ta.state.set_quiz_result"),
    ):
        from bot.ta.quiz import reveal_now

        reveal_now(CHAT)
        text = sm.call_args.args[1]
        assert "What is 2+2?" in text  # full question text
        assert "B) 4" in text  # full correct option, not just the letter


# ── anti-share membership gate ────────────────────────────────────────────
def test_submit_denied_for_non_member():
    from bot.ta.quiz import submit_answer

    active = _active()
    p1, p2, p3, p4 = _patches(active)
    with p1, p2, p3, p4, patch("bot.ta.quiz.is_chat_member", return_value=False):
        out = submit_answer("tok123", {"id": 999}, 0)
    assert out["ok"] is False
    assert out["error"] == "not_member"


def test_serve_denied_for_non_member():
    from bot.ta.quiz import serve_quiz

    active = _active()
    p1, p2, p3, p4 = _patches(active)
    with p1, p2, p3, p4, patch("bot.ta.quiz.is_chat_member", return_value=False):
        out = serve_quiz("tok123", {"id": 999})
    assert out["ok"] is False
    assert out["error"] == "not_member"


def test_permanent_admin_bypasses_membership():
    from bot.ta.quiz import serve_quiz

    active = _active()
    p1, p2, p3, p4 = _patches(active)
    # Admin id matches → access granted even though membership lookup says no.
    with (
        p1,
        p2,
        p3,
        p4,
        patch("bot.ta.quiz.PERMANENT_ADMIN_ID", 555),
        patch("bot.ta.quiz.is_chat_member", return_value=False),
    ):
        out = serve_quiz("tok123", {"id": 555})
    assert out["state"] == "live"


# ── atomic one-shot (HSETNX race) ─────────────────────────────────────────
def test_submit_atomic_loser_is_already_answered():
    from bot.ta.quiz import submit_answer

    active = _active()
    # Fast-path check misses (answered=False) but the atomic insert loses the
    # race with the student's own concurrent tap → treated as already answered.
    p1, p2, p3, p4 = _patches(active, answered=False)
    with p1, p2, p3, p4, patch("bot.ta.quiz.record_quiz_answer_nx", return_value=False):
        out = submit_answer("tok123", {"id": 42}, 0)
    assert out["accepted"] is True
    assert out["alreadyAnswered"] is True


# ── reveal idempotency claim ──────────────────────────────────────────────
def test_reveal_double_claim_short_circuits():
    active = _active(questionMessageId=699)
    with (
        patch("bot.ta.quiz.get_active_quiz", return_value=active),
        patch("bot.ta.quiz.claim_reveal", return_value=False),  # another reveal won
        patch("bot.ta.quiz.send_message") as sm,
        patch("bot.ta.quiz.record_quiz_score") as score,
        patch("bot.ta.quiz.clear_active_quiz") as clear,
    ):
        from bot.ta.quiz import reveal_now

        assert reveal_now(CHAT) is False
        sm.assert_not_called()  # no duplicate group post
        score.assert_not_called()  # no double scoring
        clear.assert_not_called()


# ── tick idempotency claim ────────────────────────────────────────────────
def test_tick_quiz_dedup_duplicate_seq_stops():
    active = _active(questionMessageId=MSG)
    with (
        patch("bot.ta.quiz.get_active_quiz", return_value=active),
        patch("bot.ta.quiz.claim_quiz_tick", return_value=False),  # duplicate seq
        patch("bot.ta.tg.edit_message_quiet") as edit,
    ):
        from bot.ta.quiz import tick_quiz

        assert tick_quiz(CHAT, MSG, "tok123", 5) is False
        edit.assert_not_called()  # the original tick already handled this seq


# ── stale-quiz recovery on /quiz ──────────────────────────────────────────
def test_start_quiz_reveals_expired_existing_then_continues():
    stale = _active(startTime=1)  # expired, never revealed (autoreveal dropped)
    with (
        patch("bot.ta.quiz.QUIZ_WEBAPP_ENABLED", True),
        patch("bot.ta.quiz.get_active_quiz", return_value=stale),
        patch("bot.ta.quiz.reveal_now") as rev,
        patch("bot.ta.quiz.clear_quiz_answers") as clear_ans,
        patch("bot.ta.quiz.generate_question", return_value=(RAW, "B")),
        patch("bot.ta.quiz.send_message", return_value=MSG),
        patch("bot.ta.quiz.set_active_quiz") as set_q,
        patch("bot.ta.quiz.set_quiz_token"),
        patch("bot.ta.quiz.push_quiz_history"),
        patch("bot.ta.quiz.bump_total_quizzes"),
        patch("bot.ta.quiz._schedule_autoreveal", return_value=True),
        patch("bot.ta.quiz.schedule_quiz_tick"),
    ):
        from bot.ta.quiz import start_quiz

        start_quiz(_prepared(), "math", CHAT)
        rev.assert_called_once_with(CHAT)  # stale quiz closed out, not wedged
        clear_ans.assert_called_once_with(CHAT)  # clean slate for the new quiz
        set_q.assert_called_once()  # the new quiz still started
