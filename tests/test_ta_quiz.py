"""Quiz generation, parsing, answering, and reveal."""
import time
from unittest.mock import MagicMock, patch


def _prepared(*, text="", user_id=42, username="alice", first_name="Alice",
              chat_id=-100123, group_key="-100123", is_dm=False, message_id=7):
    p = MagicMock()
    p.user_id = user_id
    p.username = username
    p.first_name = first_name
    p.chat_id = chat_id
    p.group_key = group_key
    p.is_dm = is_dm
    p.text = text
    msg = MagicMock()
    msg.message_id = message_id
    p.message = msg
    return p


# ── Parse cascade (§5.5) ──────────────────────────────────────────────────
def test_parse_answer_colon_format():
    from bot.ta.quiz import parse_correct_answer
    assert parse_correct_answer("... ANSWER: B") == "B"


def test_parse_answer_lowercase_letter():
    from bot.ta.quiz import parse_correct_answer
    assert parse_correct_answer("ANSWER: c") == "C"


def test_parse_answer_correct_is_phrase():
    from bot.ta.quiz import parse_correct_answer
    assert parse_correct_answer("The correct answer is D.") == "D"


def test_parse_answer_bold_marker():
    from bot.ta.quiz import parse_correct_answer
    assert parse_correct_answer("some text **A** yes") == "A"


def test_parse_answer_is_correct_suffix():
    from bot.ta.quiz import parse_correct_answer
    assert parse_correct_answer("B) is correct because...") == "B"


def test_parse_answer_trailing_letter_line():
    from bot.ta.quiz import parse_correct_answer
    txt = "A) x\nB) y\nC) z\nD) w\n\nC"
    assert parse_correct_answer(txt) == "C"


def test_parse_answer_none_when_absent():
    from bot.ta.quiz import parse_correct_answer
    assert parse_correct_answer("some random text") is None


def test_parse_answer_star_option_marker_fallback():
    from bot.ta.quiz import parse_correct_answer
    txt = "A) wrong\n**B) right**\nC) wrong\nD) wrong"
    assert parse_correct_answer(txt) == "B"


# ── Display formatting ────────────────────────────────────────────────────
def test_format_question_strips_answer_and_adds_newlines():
    raw = (
        "QUESTION: What is Python?\n"
        "A) a snake B) a language C) a coffee D) a movie\n"
        "ANSWER: B"
    )
    from bot.ta.quiz import format_question_for_display
    out = format_question_for_display(raw)
    assert "ANSWER:" not in out
    assert "QUIZ TIME" in out
    assert "\nA)" in out
    assert "\nB)" in out
    assert "\nC)" in out
    assert "\nD)" in out


# ── maybe_single_letter ───────────────────────────────────────────────────
def test_single_letter_detection():
    from bot.ta.quiz import maybe_single_letter
    assert maybe_single_letter(_prepared(text="A")) == "A"
    assert maybe_single_letter(_prepared(text="  b ")) == "B"
    assert maybe_single_letter(_prepared(text="Z")) == "Z"
    assert maybe_single_letter(_prepared(text="AB")) is None
    assert maybe_single_letter(_prepared(text="1")) is None
    assert maybe_single_letter(_prepared(text="")) is None


# ── Generation ────────────────────────────────────────────────────────────
def _mock_llm_quiz(letter="B"):
    return (
        "QUESTION: what is 2+2?\n"
        "A) 1\nB) 4\nC) 5\nD) 7\n"
        f"ANSWER: {letter}"
    )


def test_generate_question_happy_path():
    with patch("bot.ta.quiz.ai") as client, \
         patch("bot.ta.quiz.get_quiz_history", return_value=[]):
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=_mock_llm_quiz("C")))]
        )
        from bot.ta.quiz import generate_question
        out = generate_question("math", "-100123")
        assert out is not None
        raw, letter = out
        assert letter == "C"
        assert "QUESTION:" in raw


def test_generate_question_returns_none_on_unparseable():
    with patch("bot.ta.quiz.ai") as client, \
         patch("bot.ta.quiz.get_quiz_history", return_value=[]):
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="gibberish no answer"))]
        )
        from bot.ta.quiz import generate_question
        assert generate_question("x", "-100123") is None


def test_generate_question_includes_history_in_prompt():
    with patch("bot.ta.quiz.ai") as client, \
         patch("bot.ta.quiz.get_quiz_history", return_value=["prior q 1", "prior q 2"]):
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=_mock_llm_quiz()))]
        )
        from bot.ta.quiz import generate_question
        generate_question("math", "-100123")
        prompt = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "prior q 1" in prompt


# ── start_quiz ────────────────────────────────────────────────────────────
def test_start_quiz_sets_state_and_schedules():
    with patch("bot.ta.quiz.get_active_quiz", return_value=None), \
         patch("bot.ta.quiz.set_active_quiz") as set_q, \
         patch("bot.ta.quiz.push_quiz_history"), \
         patch("bot.ta.quiz.bump_total_quizzes"), \
         patch("bot.ta.quiz.generate_question", return_value=(_mock_llm_quiz("D"), "D")), \
         patch("bot.ta.quiz.send_message", return_value=77), \
         patch("bot.ta.quiz._schedule_autoreveal", return_value=True):
        from bot.ta.quiz import start_quiz
        start_quiz(_prepared(is_dm=True), "math", -100123)
        call = set_q.call_args
        state = call.args[1]
        assert state["correctAnswer"] == "D"
        assert state["questionMessageId"] == 77


def test_start_quiz_refuses_when_already_active():
    existing = {"questionMessageId": 1, "correctAnswer": "A"}
    with patch("bot.ta.quiz.get_active_quiz", return_value=existing), \
         patch("bot.ta.quiz.send_message") as sm, \
         patch("bot.ta.quiz.generate_question") as gen:
        from bot.ta.quiz import start_quiz
        start_quiz(_prepared(is_dm=True), "math", -100123)
        gen.assert_not_called()
        assert "already active" in sm.call_args.args[1]


# ── record_answer ─────────────────────────────────────────────────────────
def test_record_answer_stores_and_reacts():
    existing = {
        "questionMessageId": 7, "correctAnswer": "B",
        "topic": "x", "answers": {}, "startTime": int(time.time()),
    }
    with patch("bot.ta.quiz.get_active_quiz", return_value=existing), \
         patch("bot.ta.quiz.set_active_quiz") as set_q, \
         patch("bot.ta.quiz.set_reaction") as react:
        from bot.ta.quiz import record_answer
        record_answer(_prepared(text="A"), "A")
        state = set_q.call_args.args[1]
        assert "42" in state["answers"]
        assert state["answers"]["42"]["letter"] == "A"
        react.assert_called_once()


def test_record_answer_overwrites_previous():
    existing = {
        "questionMessageId": 7, "correctAnswer": "B",
        "topic": "x", "startTime": int(time.time()),
        "answers": {"42": {"letter": "A", "username": "alice", "firstName": "Alice"}},
    }
    with patch("bot.ta.quiz.get_active_quiz", return_value=existing), \
         patch("bot.ta.quiz.set_active_quiz") as set_q, \
         patch("bot.ta.quiz.set_reaction"):
        from bot.ta.quiz import record_answer
        record_answer(_prepared(text="C"), "C")
        state = set_q.call_args.args[1]
        assert state["answers"]["42"]["letter"] == "C"


# ── reveal_now ────────────────────────────────────────────────────────────
def test_reveal_now_scores_correct_and_wrong():
    existing = {
        "correctAnswer": "B",
        "answers": {
            "42": {"letter": "B", "username": "alice", "firstName": "Alice"},
            "99": {"letter": "A", "username": "bob", "firstName": "Bob"},
        },
        "startTime": int(time.time()),
    }
    with patch("bot.ta.quiz.get_active_quiz", return_value=existing), \
         patch("bot.ta.quiz.record_quiz_score") as rqs, \
         patch("bot.ta.quiz.clear_active_quiz") as clear, \
         patch("bot.ta.quiz.send_message") as sm:
        from bot.ta.quiz import reveal_now
        assert reveal_now(-100123) is True
        calls = {c.args[1]: c.kwargs for c in rqs.call_args_list}
        # Alice scored right, Bob wrong
        assert calls["42"]["correct"] is True
        assert calls["99"]["correct"] is False
        clear.assert_called_once_with(-100123)
        assert "Time's up" in sm.call_args.args[1]


def test_reveal_now_idempotent_when_no_active():
    with patch("bot.ta.quiz.get_active_quiz", return_value=None), \
         patch("bot.ta.quiz.send_message") as sm:
        from bot.ta.quiz import reveal_now
        assert reveal_now(-100123) is False
        sm.assert_not_called()


# ── is_expired + maybe_inline_reveal ──────────────────────────────────────
def test_is_expired_before_and_after_timeout():
    from bot.ta.quiz import is_expired
    now = 10_000
    fresh = {"startTime": now - 60}       # 1 min old, timeout is 180s
    stale = {"startTime": now - 200}      # older than 180s
    assert is_expired(fresh, now=now) is False
    assert is_expired(stale, now=now) is True


def test_inline_reveal_triggers_on_stale_quiz():
    stale = {
        "correctAnswer": "A",
        "answers": {},
        "startTime": int(time.time()) - 999,
    }
    with patch("bot.ta.quiz.get_active_quiz", return_value=stale), \
         patch("bot.ta.quiz.reveal_now", return_value=True) as rn:
        from bot.ta.quiz import maybe_inline_reveal
        assert maybe_inline_reveal(-100123) is True
        rn.assert_called_once_with(-100123)


def test_inline_reveal_skips_fresh_quiz():
    fresh = {"correctAnswer": "A", "answers": {}, "startTime": int(time.time())}
    with patch("bot.ta.quiz.get_active_quiz", return_value=fresh), \
         patch("bot.ta.quiz.reveal_now") as rn:
        from bot.ta.quiz import maybe_inline_reveal
        assert maybe_inline_reveal(-100123) is False
        rn.assert_not_called()
