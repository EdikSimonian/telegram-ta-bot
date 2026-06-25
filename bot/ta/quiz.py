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

import hashlib
import html as _html
import re
import secrets
import time

from bot.clients import ai
from bot.config import (
    DEFAULT_MODEL,
    MINIAPP_SHORT_NAME,
    PUBLIC_URL,
    QUIZ_MODEL,
    QUIZ_TIMEOUT_MINUTES,
    QUIZ_TIMEOUT_SECONDS,
    QUIZ_WEBAPP_ENABLED,
    TELEGRAM_TOKEN,
)
from bot import qstash
from bot.ta.prepare import Prepared
from bot.ta.state import (
    bump_total_quizzes,
    clear_active_quiz,
    get_active_quiz,
    get_quiz_answers,
    get_quiz_history,
    get_quiz_token_chat,
    has_quiz_answer,
    push_quiz_history,
    record_quiz_answer,
    record_quiz_score,
    set_active_quiz,
    set_quiz_token,
    update_streak,
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


_OPTION_RE = re.compile(r"(?mi)^\s*([A-D])[\).]\s*(.+?)\s*$")


def parse_question_parts(raw: str) -> dict | None:
    """Pull the stem + 4 options + correct index out of the LLM output.

    Expects the fixed generation format (QUESTION / A) / B) / C) / D) /
    ANSWER). Returns ``{"question", "options": [a,b,c,d], "correctIndex"}``
    or ``None`` when any piece is missing — callers fall back to the legacy
    text quiz on None.
    """
    if not raw:
        return None
    letter = parse_correct_answer(raw)
    if not letter or letter not in "ABCD":
        return None
    opts: dict[str, str] = {}
    for m in _OPTION_RE.finditer(raw):
        # First occurrence wins; ignore a stray "A)" inside a later option.
        opts.setdefault(m.group(1).upper(), m.group(2).strip())
    if not all(k in opts and opts[k] for k in "ABCD"):
        return None
    options = [opts[k] for k in "ABCD"]

    # Stem: text after "QUESTION:" up to the first option line; fall back to
    # everything before "A)" if the LLM dropped the QUESTION: label.
    m = re.search(r"(?is)QUESTION:\s*(.+?)\n\s*A[\).]", raw)
    if m:
        question = m.group(1).strip()
    else:
        head = _OPTION_RE.search(raw)
        question = raw[: head.start()] if head else raw
        question = re.sub(r"(?i)^\s*QUESTION:\s*", "", question.strip()).strip()
    if not question:
        return None
    return {
        "question": question,
        "options": options,
        "correctIndex": "ABCD".index(letter),
    }


def strip_answer_line(text: str) -> str:
    """Remove the ANSWER: X line from the LLM output before displaying."""
    return re.sub(r"(?mi)^\s*ANSWER:\s*[A-Da-d].*$\n?", "", text).rstrip()


def format_question_for_display(raw: str) -> str:
    """Clean + decorate the LLM output for posting in the group.

    The LLM output is treated as plain text and HTML-escaped before being
    folded into our HTML wrapper. Without escaping, common Python answers
    (``<class 'int'>``, ``list<int>``, ``i < n``) make Telegram return
    400 "can't parse entities" and the whole quiz silently fails.
    """
    body = strip_answer_line(raw).strip()
    body = re.sub(r"^QUESTION:\s*", "", body, flags=re.IGNORECASE)
    # Blank line before each option so the question and every choice are
    # visually separated in the chat (question ↔ A ↔ B ↔ C ↔ D).
    body = re.sub(r"\s*\n?([A-D])\)", r"\n\n\1)", body).lstrip("\n")
    return (
        "✨✨✨ <b>QUIZ TIME!</b> ✨✨✨\n\n"
        f"{_html.escape(body)}\n\n"
        f"⏰ <i>Reply with A, B, C, or D — you have {QUIZ_TIMEOUT_MINUTES} minutes!</i>"
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


def _course_context_block(topic: str) -> str:
    """Retrieve course material for the quiz topic, formatted for the prompt.

    Grounding questions in the instructor's uploaded docs is the real
    anti-cheat: a question about *this* course's material can't be answered by
    an external ChatGPT that lacks the material. Best-effort — any RAG failure
    (vector unconfigured, no docs, API error) degrades to generic generation.
    """
    try:
        from bot.ta.rag import format_context, retrieve

        ctx = format_context(retrieve(topic or "core concepts from the course so far"))
    except Exception as e:
        print(f"[ta.quiz] rag retrieve for quiz failed: {e}")
        return ""
    if not ctx:
        return ""
    return (
        "Base the question STRICTLY on the following course material — ask "
        "about a specific fact, definition, or detail that appears here, so a "
        "student who didn't study it can't answer. Do NOT ask about anything "
        "outside this material:\n"
        f"{ctx}\n\n"
    )


def generate_question(topic: str, group_key: str) -> tuple[str, str] | None:
    """Ask the LLM for an MC question on ``topic``. Returns (raw_llm, letter)."""
    prompt = (
        f"You are a quiz generator for an AI & Software Engineering workshop. "
        f"Generate exactly one multiple-choice quiz question about: "
        f"{topic or 'a core concept from the course so far'}.\n"
        f"{_course_context_block(topic)}"
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
    from bot.ta.state import get_active_quiz as _get_aq

    active = _get_aq(chat_id)
    q_msg_id = active.get("questionMessageId") if active else None
    msg_id = qstash.publish(
        callback,
        body={"chatId": str(chat_id), "questionMessageId": q_msg_id},
        delay_seconds=QUIZ_TIMEOUT_SECONDS,
    )
    return bool(msg_id)


# ── Web App (Mini App) mode ───────────────────────────────────────────────
# When QUIZ_WEBAPP_ENABLED, /quiz posts only the question stem + an "Open quiz"
# button into the group. Each student opens an authenticated Mini App that
# renders the four options in a per-student order, so the correct *position*
# differs per person — a shared "the answer is B" is worthless, and nothing is
# typed in the group. Grading happens server-side; the correct option is never
# sent to a browser before the student commits.
def _user_option_order(
    chat_id: int | str, msg_id: int | str | None, user_id: int | str
) -> list[int]:
    """Deterministic permutation of [0,1,2,3] for one student on one quiz.

    ``order[displayPos] = canonicalIndex``. Seeded with the bot token (a
    server-only secret) so a student can't predict another student's order,
    and stable across reloads so re-opening the app shows the same layout.
    """
    seed = hashlib.sha256(
        f"{TELEGRAM_TOKEN}:{chat_id}:{msg_id}:{user_id}".encode()
    ).digest()
    order = [0, 1, 2, 3]
    for i in range(3, 0, -1):  # Fisher-Yates with seed bytes
        j = seed[i] % (i + 1)
        order[i], order[j] = order[j], order[i]
    return order


def is_webapp_quiz(chat_id: int | str) -> bool:
    active = get_active_quiz(chat_id)
    return bool(active and active.get("mode") == "webapp")


def _build_quiz_button(token: str):
    """Inline keyboard with a URL button that opens the direct-link Mini App.

    A ``web_app`` button type is private-chat-only, so for group messages we
    use a plain URL button to ``t.me/<bot>/<app>?startapp=<token>`` — Telegram
    recognises the direct link and launches the Mini App authenticated.
    """
    from telebot import types

    from bot.clients import BOT_INFO

    url = f"https://t.me/{BOT_INFO.username}/{MINIAPP_SHORT_NAME}?startapp={token}"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(text="🧩 Open quiz", url=url))
    return kb


def _format_webapp_teaser(topic: str) -> str:
    """Group message for a web-app quiz — deliberately question-FREE.

    The question itself never appears in the group chat: that text is the
    easiest thing to copy into an external LLM. It lives only inside the Mini
    App, where we can block selection. The group gets just the title (+ the
    broad topic, which isn't the question); the inline button does the rest.
    """
    topic_line = f"\n\n📚 Topic: <b>{_html.escape(topic)}</b>" if topic else ""
    return f"✨✨✨ <b>QUIZ TIME!</b> ✨✨✨{topic_line}"


def _format_webapp_expired(topic: str) -> str:
    """Replacement text once a web-app quiz closes (button is dropped too)."""
    topic_line = f" — <b>{_html.escape(topic)}</b>" if topic else ""
    return (
        f"⏰ <b>Quiz ended</b>{topic_line}\n\nThis quiz has expired. Results below 👇"
    )


def _start_webapp_quiz(
    p: Prepared, topic: str, chat_id: int | str, raw: str, correct: str, parts: dict
) -> None:
    token = secrets.token_urlsafe(12)
    msg_id = send_message(
        chat_id,
        _format_webapp_teaser(topic),
        parse_mode="HTML",
        reply_markup=_build_quiz_button(token),
    )
    if msg_id is None:
        send_message(p.user_id, "Telegram rejected the quiz message.")
        return

    set_active_quiz(
        chat_id,
        {
            "questionMessageId": msg_id,
            "correctAnswer": correct,  # canonical letter — keeps reveal_now happy
            "correctIndex": parts["correctIndex"],
            "question": parts["question"],
            "options": parts["options"],
            "topic": topic,
            "mode": "webapp",
            "token": token,
            "answers": {},
            "startTime": int(time.time()),
        },
    )
    # TTL the token a little past the quiz window so late opens still resolve.
    set_quiz_token(token, chat_id, QUIZ_TIMEOUT_SECONDS + 300)
    push_quiz_history(p.group_key, _first_line(raw))
    bump_total_quizzes(p.group_key)

    scheduled = _schedule_autoreveal(chat_id)
    send_message(
        p.user_id,
        f"✅ Web-app quiz posted (correct: <b>{correct}</b>). "
        f"{'Auto-reveal in 3 min.' if scheduled else 'QStash unavailable — reveal inline on next message.'}",
        parse_mode="HTML",
    )


def _load_active_for_token(token: str) -> tuple[str | None, dict | None]:
    """Resolve a launch token to its (chat_id, active web-app quiz) pair.

    Returns (None, None) when the token is unknown, the quiz ended, or a
    different quiz is now active in that chat (token mismatch).
    """
    chat_id = get_quiz_token_chat(token)
    if not chat_id:
        return None, None
    active = get_active_quiz(chat_id)
    if not active or active.get("mode") != "webapp" or active.get("token") != token:
        return None, None
    return chat_id, active


def serve_quiz(token: str, user: dict) -> dict:
    """Return this student's view of the quiz: stem + options in *their* order.

    The correct position is included ONLY if the student already answered —
    never leak it to someone who hasn't committed yet.
    """
    if not token:
        return {"ok": False, "error": "no_token"}
    chat_id, active = _load_active_for_token(token)
    if active is None:
        return {"ok": False, "error": "ended"}
    if is_expired(active):
        return {"ok": False, "error": "expired"}
    options = list(active.get("options") or [])
    if len(options) != 4:
        return {"ok": False, "error": "ended"}
    uid = str(user.get("id"))
    order = _user_option_order(chat_id, active.get("questionMessageId"), uid)
    correct_index = int(active.get("correctIndex", 0))
    now = int(time.time())
    payload = {
        "ok": True,
        "question": active.get("question") or "",
        "options": [options[order[pos]] for pos in range(4)],
        "remainingSeconds": max(
            0, QUIZ_TIMEOUT_SECONDS - (now - int(active.get("startTime") or now))
        ),
        "answered": False,
    }
    mine = get_quiz_answers(chat_id).get(uid)
    if mine:
        their_letter = (mine.get("letter") or "").upper()
        payload["answered"] = True
        payload["correct"] = their_letter == "ABCD"[correct_index]
        payload["correctPosition"] = order.index(correct_index)
        their_index = "ABCD".index(their_letter) if their_letter in "ABCD" else -1
        payload["yourPosition"] = order.index(their_index) if their_index >= 0 else None
    return payload


def submit_answer(token: str, user: dict, position) -> dict:
    """Grade a student's tapped position. One-shot: first answer is final."""
    if not token:
        return {"ok": False, "error": "no_token"}
    chat_id, active = _load_active_for_token(token)
    if active is None:
        return {"ok": False, "error": "ended"}
    if is_expired(active):
        return {"ok": False, "error": "expired"}
    try:
        position = int(position)
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad_position"}
    if not 0 <= position <= 3:
        return {"ok": False, "error": "bad_position"}

    uid = str(user.get("id"))
    order = _user_option_order(chat_id, active.get("questionMessageId"), uid)
    correct_index = int(active.get("correctIndex", 0))
    correct_position = order.index(correct_index)

    # Idempotent: if they already answered, replay the original result rather
    # than overwriting it (no fishing for a better grade).
    if has_quiz_answer(chat_id, uid):
        mine = get_quiz_answers(chat_id).get(uid) or {}
        their_letter = (mine.get("letter") or "").upper()
        their_index = "ABCD".index(their_letter) if their_letter in "ABCD" else -1
        return {
            "ok": True,
            "alreadyAnswered": True,
            "correct": their_letter == "ABCD"[correct_index],
            "yourPosition": order.index(their_index) if their_index >= 0 else None,
            "correctPosition": correct_position,
        }

    canonical = order[position]
    record_quiz_answer(
        chat_id,
        uid,
        {
            "letter": "ABCD"[canonical],
            "username": user.get("username"),
            "firstName": user.get("first_name"),
            "ts": int(time.time()),
        },
    )
    return {
        "ok": True,
        "correct": canonical == correct_index,
        "yourPosition": position,
        "correctPosition": correct_position,
    }


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

    # Web-app mode: post stem + button when configured AND the question parses
    # into 4 clean options. Anything else falls back to the legacy text quiz.
    if QUIZ_WEBAPP_ENABLED:
        parts = parse_question_parts(raw)
        if parts:
            _start_webapp_quiz(p, topic, chat_id, raw, correct, parts)
            return

    question_text = format_question_for_display(raw)
    msg_id = send_message(chat_id, question_text, parse_mode="HTML")
    if msg_id is None:
        send_message(p.user_id, "Telegram rejected the quiz message.")
        return

    set_active_quiz(
        chat_id,
        {
            "questionMessageId": msg_id,
            "correctAnswer": correct,
            "topic": topic,
            "answers": {},
            "startTime": int(time.time()),
        },
    )
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
    """Record a student's answer (overwrites any previous). React 🫡.

    Atomic: one HSET per student into the quiz answers hash. Concurrent
    answers from different students no longer race via read-modify-write
    on a shared dict — the previous flow could drop one answer when two
    students replied in the same Vercel invocation tick.
    """
    if get_active_quiz(p.chat_id) is None:
        return
    record_quiz_answer(
        p.chat_id,
        p.user_id,
        {
            "letter": letter,
            "username": p.username,
            "firstName": p.first_name,
            "ts": int(time.time()),
        },
    )
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
    # Merge: new HSET-based store + any legacy in-dict answers from quizzes
    # that were active at deploy time. The hash wins on user_id collisions.
    answers: dict = dict(active.get("answers") or {})
    answers.update(get_quiz_answers(chat_id))
    group_key = str(chat_id)

    right: list[str] = []
    wrong: list[str] = []
    for uid, data in answers.items():
        letter = (data.get("letter") or "").upper()
        raw_name = data.get("firstName") or data.get("username") or f"user:{uid}"
        name = _html.escape(raw_name)
        is_right = letter == correct.upper()
        record_quiz_score(
            group_key,
            uid,
            data.get("username"),
            data.get("firstName"),
            correct=is_right,
        )
        streak = update_streak(group_key, uid, is_right)
        label = f"{name} \U0001f525{streak}" if streak >= 2 else name
        (right if is_right else wrong).append(label)

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

    # Web-app quizzes: rewrite the original teaser to "expired" and drop the
    # inline button (edit with no reply_markup) so the dead quiz can't be
    # reopened from the group. Best-effort — never fail the reveal over this.
    q_msg_id = active.get("questionMessageId")
    if active.get("mode") == "webapp" and q_msg_id:
        from bot.ta.tg import edit_message_quiet

        edit_message_quiet(
            chat_id,
            q_msg_id,
            _format_webapp_expired(active.get("topic") or ""),
            parse_mode="HTML",
        )

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
