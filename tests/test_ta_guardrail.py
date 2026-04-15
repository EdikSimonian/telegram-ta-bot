"""LLM output cleanup (spec §5.10)."""


# ── strip_thinking ────────────────────────────────────────────────────────
def test_strip_thinking_removes_single_block():
    from bot.ta.guardrail import strip_thinking
    text = "<think>planning...</think>Hello world"
    assert strip_thinking(text) == "Hello world"


def test_strip_thinking_multiline_block():
    from bot.ta.guardrail import strip_thinking
    text = "<think>line 1\nline 2\nline 3</think>\nactual reply"
    assert strip_thinking(text) == "actual reply"


def test_strip_thinking_case_insensitive():
    from bot.ta.guardrail import strip_thinking
    text = "<THINK>x</Think>body"
    assert strip_thinking(text) == "body"


def test_strip_thinking_multiple_blocks():
    from bot.ta.guardrail import strip_thinking
    text = "<think>a</think>before<think>b</think>after"
    assert strip_thinking(text) == "beforeafter"


def test_strip_thinking_no_blocks_passthrough():
    from bot.ta.guardrail import strip_thinking
    assert strip_thinking("just a reply") == "just a reply"


def test_strip_thinking_empty_input():
    from bot.ta.guardrail import strip_thinking
    assert strip_thinking("") == ""


# ── trim_leading_reasoning ────────────────────────────────────────────────
def test_trim_leading_reasoning_removes_okay_preamble():
    from bot.ta.guardrail import trim_leading_reasoning
    text = (
        "Okay, the user is asking about Python.\n\n"
        "Python is a programming language."
    )
    assert trim_leading_reasoning(text) == "Python is a programming language."


def test_trim_leading_reasoning_removes_multiple_preamble_paragraphs():
    from bot.ta.guardrail import trim_leading_reasoning
    text = (
        "Looking at the context, the user wants info.\n\n"
        "I think I should explain Python basics.\n\n"
        "Python is a language."
    )
    assert trim_leading_reasoning(text) == "Python is a language."


def test_trim_leading_reasoning_keeps_normal_reply():
    from bot.ta.guardrail import trim_leading_reasoning
    text = "Python is a language."
    assert trim_leading_reasoning(text) == "Python is a language."


def test_trim_leading_reasoning_empty():
    from bot.ta.guardrail import trim_leading_reasoning
    assert trim_leading_reasoning("") == ""


# ── hedging ───────────────────────────────────────────────────────────────
def test_is_hedging_detects_phrases():
    from bot.ta.guardrail import is_hedging
    assert is_hedging("I don't have access to the course schedule.") is True
    assert is_hedging("That is outside my knowledge.") is True
    assert is_hedging("I cannot answer that.") is True


def test_is_hedging_false_for_real_answers():
    from bot.ta.guardrail import is_hedging
    assert is_hedging("Python is a language.") is False
    assert is_hedging("The answer is 42.") is False


# ── IGNORE ────────────────────────────────────────────────────────────────
def test_is_ignore_marker_true_for_exact():
    from bot.ta.guardrail import is_ignore_marker
    assert is_ignore_marker("IGNORE") is True
    assert is_ignore_marker("ignore") is True
    assert is_ignore_marker("  IGNORE  ") is True


def test_is_ignore_marker_false_for_longer():
    from bot.ta.guardrail import is_ignore_marker
    assert is_ignore_marker("please ignore this") is False


# ── clean ─────────────────────────────────────────────────────────────────
def test_clean_full_pipeline_ok():
    from bot.ta.guardrail import clean
    text = (
        "<think>plan</think>"
        "Okay, the user is asking.\n\n"
        "Python is a programming language."
    )
    assert clean(text) == "Python is a programming language."


def test_clean_returns_none_for_empty_after_strip():
    from bot.ta.guardrail import clean
    assert clean("<think>all planning</think>") is None


def test_clean_returns_none_for_ignore():
    from bot.ta.guardrail import clean
    assert clean("IGNORE") is None


def test_clean_returns_none_for_hedging():
    from bot.ta.guardrail import clean
    assert clean("I don't have access to that.") is None


def test_clean_returns_none_for_empty_input():
    from bot.ta.guardrail import clean
    assert clean("") is None
    assert clean(None) is None


# ── integration with ai.answer ────────────────────────────────────────────
def test_ai_answer_suppresses_hedged_reply():
    from unittest.mock import MagicMock, patch
    with patch("bot.ai.rag.retrieve", return_value=[]), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.append_history") as ah, \
         patch("bot.ai.get_active_model", return_value=None), \
         patch("bot.ai.ai") as client:
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="I don't have access to that."))]
        )
        from bot.ai import answer
        p = MagicMock(stripped_text="when is class", group_key="-100123",
                      is_dm=False, is_mention=False, is_reply_to_bot=False,
                      is_instructor=False, mentions_other_user=False,
                      reply_to_username=None, username="student")
        out = answer(p)
        assert out is None
        ah.assert_not_called()  # no history pollution
