"""Quiz Mini App mode: parsing, per-user shuffle, serve/grade, start_quiz."""

import time
from unittest.mock import MagicMock, patch

CHAT = -100123
MSG = 77
RAW = "QUESTION: What is 2+2?\nA) 3\nB) 4\nC) 5\nD) 22\nANSWER: B"


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
    with p1, p2, p3, p4, patch("bot.ta.quiz.record_quiz_answer") as rec:
        out = submit_answer("tok123", {"id": 42, "first_name": "Alice"}, correct_pos)
    assert out["ok"] is True
    assert out["correct"] is True
    assert out["correctPosition"] == correct_pos
    # Recorded as the canonical letter so reveal_now tallies correctly.
    assert rec.call_args.args[2]["letter"] == "B"


def test_submit_wrong_position_scores_wrong():
    from bot.ta.quiz import _user_option_order, submit_answer

    active = _active()
    order = _user_option_order(CHAT, MSG, 42)
    wrong_pos = (order.index(1) + 1) % 4
    p1, p2, p3, p4 = _patches(active)
    with p1, p2, p3, p4, patch("bot.ta.quiz.record_quiz_answer") as rec:
        out = submit_answer("tok123", {"id": 42}, wrong_pos)
    assert out["correct"] is False
    assert rec.call_args.args[2]["letter"] != "B"


def test_submit_is_one_shot():
    from bot.ta.quiz import submit_answer

    active = _active()
    answers = {"42": {"letter": "A"}}  # already answered with canonical "A"
    p1, p2, p3, p4 = _patches(active, answered=True, answers=answers)
    with p1, p2, p3, p4, patch("bot.ta.quiz.record_quiz_answer") as rec:
        out = submit_answer("tok123", {"id": 42}, 0)
    assert out["alreadyAnswered"] is True
    assert out["correct"] is False  # their stored "A" != correct "B"
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


def test_serve_expired_is_expired():
    from bot.ta.quiz import serve_quiz

    active = _active(startTime=1)  # ancient → expired
    p1, p2, p3, p4 = _patches(active)
    with p1, p2, p3, p4:
        out = serve_quiz("tok123", {"id": 42})
    assert out["ok"] is False
    assert out["error"] == "expired"


def test_submit_rejects_out_of_range_position():
    from bot.ta.quiz import submit_answer

    active = _active()
    p1, p2, p3, p4 = _patches(active)
    with p1, p2, p3, p4, patch("bot.ta.quiz.record_quiz_answer"):
        assert submit_answer("tok123", {"id": 42}, 9)["error"] == "bad_position"


# ── serve_quiz ────────────────────────────────────────────────────────────
def test_serve_hides_correct_position_until_answered():
    from bot.ta.quiz import serve_quiz

    active = _active()
    p1, p2, p3, p4 = _patches(active)
    with p1, p2, p3, p4:
        out = serve_quiz("tok123", {"id": 42})
    assert out["ok"] is True
    assert out["answered"] is False
    assert "correctPosition" not in out  # never leak before commit
    assert sorted(out["options"]) == ["22", "3", "4", "5"]  # all 4, some order


def test_serve_shows_result_after_answered():
    from bot.ta.quiz import _user_option_order, serve_quiz

    active = _active()
    order = _user_option_order(CHAT, MSG, 42)
    answers = {"42": {"letter": "B"}}  # they got it right
    p1, p2, p3, p4 = _patches(active, answered=True, answers=answers)
    with p1, p2, p3, p4:
        out = serve_quiz("tok123", {"id": 42})
    assert out["answered"] is True
    assert out["correct"] is True
    assert out["correctPosition"] == order.index(1)


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
    ):
        from bot.ta.quiz import start_quiz

        start_quiz(_prepared(), "math", CHAT)

        state = set_q.call_args.args[1]
        assert state["mode"] == "webapp"
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
