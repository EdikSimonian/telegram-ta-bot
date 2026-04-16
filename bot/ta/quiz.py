"""Quiz generation, answering, and reveal.

Flow:
    /quiz [topic]       → generate MC question via LLM → post to group
                        → QStash publish /api/autoreveal (+3 min)
    student types A-D   → record_answer → react 👍, text blanked
    student types E-Z   → react 🤔 during active quiz
    /reveal             → reveal_now (admin only)
    QStash callback     → api/autoreveal.py → reveal_now
    inline fallback     → router checks expiry on every incoming message
"""
from __future__ import annotations

import html as _html
import re
import time

from bot.clients import ai
from bot.config import (
    DEFAULT_MODEL,
    PUBLIC_URL,
    QUIZ_MODEL,
    QUIZ_TIMEOUT_SECONDS,
)
from bot import qstash
from bot.ta.prepare import Prepared
from bot.ta.state import (
    bump_total_quizzes,
    clear_active_quiz,
    get_active_quiz,
    get_quiz_history,
    push_quiz_history,
    record_quiz_score,
    set_active_quiz,
)
from bot.ta.tg import send_message, set_reaction


# ── Answer regex cascade (§5.5) ──────────────────────────────────────────
# First match wins; later patterns are fallbacks for LLMs that deviate
# from the ANSWER: X line.
_ANSWER_PATTERNS = [
    re.compile(r"ANSWER:\s*([A-Da-d])"),
    re.compile(r"correct\s*(?:answer)?\s*(?:is)?\s*[:=]?\s*([A-Da-d])", re.IGNORECASE),
    re.compile(r"\*\*([A-Da-d])\*\*"),
    re.compile(r"\b([A-D])\)\s*(?:is correct|✓|✅)"),
    re.compile(r"(?:^|\n)\s*([A-D])\s*$", re.MULTILINE),
    re.compile(r"\b([A-D])\)?\s*$"),
]


def parse_correct_answer(text: str) -> str | None:
    """Extract the letter A–D using the fallback cascade."""
    if not text:
        return None
    for pat in _ANSWER_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).upper()
    # Last resort: look for **A) / **B) / etc. marker formatting anywhere.
    for letter in "ABCD":
        if f"**{letter})" in text:
            return letter
    return None


def strip_answer_line(text: str) -> str:
    """Remove the ANSWER: X line from the LLM output before displaying."""
    return re.sub(r"(?mi)^\s*ANSWER:\s*[A-Da-d].*$\n?", "", text).rstrip()


def format_question_for_display(raw: str) -> str:
    """Clean + decorate the LLM output for posting in the group."""
    body = strip_answer_line(raw).strip()
    body = re.sub(r"^QUESTION:\s*", "", body, flags=re.IGNORECASE)
    # Guarantee each option starts on its own line.
    body = re.sub(r"\s*\n?([A-D])\)", r"\n\1)", body).lstrip("\n")
    return (
        "✨✨✨ <b>QUIZ TIME!</b> ✨✨✨\n\n"
        f"{body}\n\n"
        "⏰ <i>Reply with A, B, C, or D — you have 3 minutes!</i>"
    )


# ── Generation ────────────────────────────────────────────────────────────
def _history_block(group_key: str) -> str:
    prior = get_quiz_history(group_key)
    if not prior:
        return ""
    joined = "\n".join(f"- {q}" for q in prior[-20:])
    return (
        "\nDo NOT repeat these recent questions — generate something "
        f"different:\n{joined}\n"
    )


def _first_line(text: str) -> str:
    for ln in text.splitlines():
        stripped = ln.strip()
        if stripped:
            return stripped[:200]
    return text[:200]


def generate_question(topic: str, group_key: str) -> tuple[str, str] | None:
    """Ask the LLM for an MC question on ``topic``. Returns (raw_llm, letter)."""
    prompt = (
        f"You are a quiz generator for an AI & Software Engineering workshop. "
        f"Generate exactly one multiple-choice quiz question about: "
        f"{topic or 'a core concept from the course so far'}.\n"
        f"{_history_block(group_key)}"
        "Format your response EXACTLY like this (no extra text):\n"
        "QUESTION: <the question>\n"
        "A) <option>\n"
        "B) <option>\n"
        "C) <option>\n"
        "D) <option>\n"
        "ANSWER: <single letter A, B, C, or D>"
    )
    try:
        resp = ai.chat.completions.create(
            model=QUIZ_MODEL or DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[ta.quiz] generate error: {e}")
        return None
    letter = parse_correct_answer(raw)
    if not letter:
        print(f"[ta.quiz] could not parse answer from:\n{raw[:400]}")
        return None
    return raw, letter


# ── Scheduling ────────────────────────────────────────────────────────────
def _schedule_autoreveal(chat_id: int | str) -> bool:
    if not PUBLIC_URL:
        print("[ta.quiz] PUBLIC_URL unset — cannot schedule QStash callback")
        return False
    callback = f"{PUBLIC_URL}/api/autoreveal"
    msg_id = qstash.publish(
        callback,
        body={"chatId": str(chat_id)},
        delay_seconds=QUIZ_TIMEOUT_SECONDS,
    )
    return bool(msg_id)


# ── Start ─────────────────────────────────────────────────────────────────
def start_quiz(p: Prepared, topic: str, chat_id: int | str) -> None:
    """/quiz handler. Caller is responsible for admin gating."""
    if get_active_quiz(chat_id) is not None:
        send_message(
            p.user_id,
            "A quiz is already active in that chat. Use /reveal first.",
        )
        return

    gen = generate_question(topic, p.group_key)
    if gen is None:
        send_message(p.user_id, "Couldn't generate a quiz — see logs.")
        return
    raw, correct = gen

    question_text = format_question_for_display(raw)
    msg_id = send_message(chat_id, question_text, parse_mode="HTML")
    if msg_id is None:
        send_message(p.user_id, "Telegram rejected the quiz message.")
        return

    set_active_quiz(chat_id, {
        "questionMessageId": msg_id,
        "correctAnswer":     correct,
        "topic":             topic,
        "answers":           {},
        "startTime":         int(time.time()),
    })
    push_quiz_history(p.group_key, _first_line(raw))
    bump_total_quizzes(p.group_key)

    scheduled = _schedule_autoreveal(chat_id)
    send_message(
        p.user_id,
        f"✅ Quiz posted (correct: <b>{correct}</b>). "
        f"{'Auto-reveal in 3 min.' if scheduled else 'QStash unavailable — reveal inline on next message.'}",
        parse_mode="HTML",
    )


# ── Answer handling (called by router) ────────────────────────────────────
_ANSWER_RE = re.compile(r"^\s*([A-Za-z])\s*$")


def maybe_single_letter(p: Prepared) -> str | None:
    """Return the uppercased letter if message is exactly one A-Z char."""
    if not p.text:
        return None
    m = _ANSWER_RE.match(p.text)
    return m.group(1).upper() if m else None


def is_active_quiz_in(chat_id: int | str) -> bool:
    return get_active_quiz(chat_id) is not None


def record_answer(p: Prepared, letter: str) -> None:
    """Record a student's answer (overwrites any previous). React 👍."""
    active = get_active_quiz(p.chat_id)
    if active is None:
        return
    answers = dict(active.get("answers") or {})
    answers[str(p.user_id)] = {
        "letter":    letter,
        "username":  p.username,
        "firstName": p.first_name,
        "ts":        int(time.time()),
    }
    active["answers"] = answers
    set_active_quiz(p.chat_id, active)
    set_reaction(p.chat_id, p.message.message_id, "🫡")


def react_invalid(p: Prepared) -> None:
    """A single letter E–Z during an active quiz. React 🤔, don't hit LLM."""
    set_reaction(p.chat_id, p.message.message_id, "🤔")


def react_quiet(p: Prepared) -> None:
    """Off-topic chatter during an active quiz. Shush: 🤫."""
    set_reaction(p.chat_id, p.message.message_id, "🤫")


# ── Reveal ────────────────────────────────────────────────────────────────
def reveal_now(chat_id: int | str) -> bool:
    """End the active quiz in ``chat_id`` and post results.

    Idempotent: if no active quiz, returns False without side effects.
    Updates per-group scores as a side effect.
    """
    active = get_active_quiz(chat_id)
    if not active:
        return False
    correct = active.get("correctAnswer") or ""
    answers: dict = active.get("answers") or {}
    group_key = str(chat_id)

    right: list[str] = []
    wrong: list[str] = []
    for uid, data in answers.items():
        letter = (data.get("letter") or "").upper()
        raw_name = data.get("firstName") or data.get("username") or f"user:{uid}"
        name = _html.escape(raw_name)
        is_right = letter == correct.upper()
        record_quiz_score(
            group_key, uid, data.get("username"), data.get("firstName"),
            correct=is_right,
        )
        (right if is_right else wrong).append(name)

    lines = [
        "⏰ <b>Time's up!</b>",
        f"✅ Correct answer: <b>{correct}</b>",
        "",
    ]
    if right:
        lines.append(f"🎉 Got it right ({len(right)}): {', '.join(right)}")
    if wrong:
        lines.append(f"📚 Got it wrong ({len(wrong)}): {', '.join(wrong)}")
    if not right and not wrong:
        lines.append("No one answered — better luck next time!")
    send_message(chat_id, "\n".join(lines), parse_mode="HTML")
    clear_active_quiz(chat_id)
    return True


def is_expired(active: dict, now: int | None = None) -> bool:
    start = int(active.get("startTime") or 0)
    ts = int(now if now is not None else time.time())
    return start > 0 and ts - start >= QUIZ_TIMEOUT_SECONDS


def maybe_inline_reveal(chat_id: int | str) -> bool:
    """Inline fallback for when QStash drops the callback.

    Called by the router before quiz-answer matching. If the active quiz
    has passed the timeout, reveal it now. Returns True if a reveal
    happened (caller should NOT treat the incoming message as an answer).
    """
    active = get_active_quiz(chat_id)
    if active is None:
        return False
    if is_expired(active):
        reveal_now(chat_id)
        return True
    return False
