"""Full quiz lifecycle scenario: 5 quizzes, 20 students, mixed accuracy.

Drives the real state.py + quiz.py code paths via a fake Redis. For each
quiz: set_active_quiz → 20 record_answer calls → reveal_now. Verifies
record_quiz_score totals and update_streak counters end up correct in
Redis afterwards.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from tests.test_ta_grade_scenario import FakeRedis


CORRECT = "A"  # every quiz in this scenario has correct answer "A"


# Four distinct answering patterns, 5 students each.
# Group 0: always "A" → 5/5 correct, streak 5
# Group 1: alternating A,B,A,B,A → 3/5, streak ends at 1
# Group 2: always "B" → 0/5, streak 0
# Group 3: skips quiz 0, then always "A" → 4/4, streak 4
def _student_letter(group: int, quiz_idx: int) -> str | None:
    if group == 0:
        return "A"
    if group == 1:
        return "A" if quiz_idx % 2 == 0 else "B"
    if group == 2:
        return "B"
    if group == 3:
        return None if quiz_idx == 0 else "A"
    raise AssertionError(group)


EXPECTED = {
    0: {"attempts": 5, "correct": 5, "streak": 5},
    1: {"attempts": 5, "correct": 3, "streak": 1},   # A(✓) B(✗→0) A(✓→1) B(✗→0) A(✓→1)
    2: {"attempts": 5, "correct": 0, "streak": 0},
    3: {"attempts": 4, "correct": 4, "streak": 4},
}


def _make_prepared(*, user_id, username, first_name, chat_id, message_id):
    p = MagicMock()
    p.user_id = user_id
    p.username = username
    p.first_name = first_name
    p.chat_id = chat_id
    msg = MagicMock()
    msg.message_id = message_id
    p.message = msg
    return p


def test_quiz_scenario_20_students_5_quizzes():
    fake = FakeRedis()
    chat_id = -100999
    group_key = str(chat_id)

    students = []
    for i in range(20):
        students.append({
            "user_id":    2000 + i,
            "username":   f"stu{i:02d}",
            "first_name": f"Stu{i:02d}",
            "group":      i // 5,
        })

    with patch("bot.ta.state.redis", fake), \
         patch("bot.ta.quiz.send_message") as sm_quiz, \
         patch("bot.ta.quiz.set_reaction"):
        from bot.ta.quiz import record_answer, reveal_now, is_active_quiz_in
        from bot.ta.state import bump_total_quizzes, set_active_quiz

        for qi in range(5):
            set_active_quiz(chat_id, {
                "questionMessageId": 5000 + qi,
                "correctAnswer":     CORRECT,
                "topic":             f"topic-{qi}",
                "answers":           {},
                "startTime":         int(time.time()),
            })
            bump_total_quizzes(group_key)
            assert is_active_quiz_in(chat_id)

            for si, s in enumerate(students):
                letter = _student_letter(s["group"], qi)
                if letter is None:
                    continue
                record_answer(
                    _make_prepared(
                        user_id=s["user_id"],
                        username=s["username"],
                        first_name=s["first_name"],
                        chat_id=chat_id,
                        message_id=9000 + qi * 100 + si,
                    ),
                    letter,
                )

            assert reveal_now(chat_id) is True
            assert not is_active_quiz_in(chat_id)

        # reveal_now posts a summary to the chat each round.
        assert sm_quiz.call_count == 5

    # Verify final tallies via state.py reads (same fake).
    with patch("bot.ta.state.redis", fake):
        from bot.ta.state import (
            get_quiz_scores,
            get_streak,
            get_total_quizzes,
        )
        scores = get_quiz_scores(group_key)
        total  = get_total_quizzes(group_key)

        assert total == 5
        # Everyone who attempted at least once has a score entry.
        assert len(scores) == 20

        for s in students:
            uid = str(s["user_id"])
            exp = EXPECTED[s["group"]]
            row = scores[uid]
            assert row["total"]   == exp["attempts"], f"{s['first_name']} attempts"
            assert row["correct"] == exp["correct"],  f"{s['first_name']} correct"
            assert get_streak(group_key, s["user_id"]) == exp["streak"], \
                f"{s['first_name']} streak"


# ── Reveal messaging: right vs wrong buckets and streak badges ─────────────
def test_quiz_reveal_renders_right_wrong_buckets():
    fake = FakeRedis()
    chat_id = -100111

    with patch("bot.ta.state.redis", fake), \
         patch("bot.ta.quiz.set_reaction"):
        from bot.ta.quiz import record_answer
        from bot.ta.state import set_active_quiz

        set_active_quiz(chat_id, {
            "questionMessageId": 1,
            "correctAnswer": "A",
            "topic": "t",
            "answers": {},
            "startTime": int(time.time()),
        })

        # One right, one wrong.
        record_answer(
            _make_prepared(user_id=1, username="alice", first_name="Alice",
                           chat_id=chat_id, message_id=10),
            "A",
        )
        record_answer(
            _make_prepared(user_id=2, username="bob", first_name="Bob",
                           chat_id=chat_id, message_id=11),
            "B",
        )

    with patch("bot.ta.state.redis", fake), \
         patch("bot.ta.quiz.send_message") as sm:
        from bot.ta.quiz import reveal_now
        assert reveal_now(chat_id) is True

    text = sm.call_args.args[1]
    assert "Correct answer:" in text
    assert "Alice" in text and "Bob" in text
    # Alice is in the "got it right" bucket, Bob in "got it wrong" — Alice
    # appears first because right bucket renders before wrong.
    assert text.index("Got it right") < text.index("Got it wrong")


def test_quiz_reveal_noop_when_no_active_quiz():
    fake = FakeRedis()
    with patch("bot.ta.state.redis", fake), \
         patch("bot.ta.quiz.send_message") as sm:
        from bot.ta.quiz import reveal_now
        assert reveal_now(-100999) is False
        sm.assert_not_called()
