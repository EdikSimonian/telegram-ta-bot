"""Quiz generation, answering, and reveal.

Stage 2 scaffolding: only the router-adjacent helpers are live. Actual
generation + reveal + QStash scheduling land in Stage 6.
"""
from __future__ import annotations

import re

from bot.ta.prepare import Prepared
from bot.ta.state import get_active_quiz


_ANSWER_RE = re.compile(r"^\s*([A-Za-z])\s*$")


def maybe_single_letter(p: Prepared) -> str | None:
    """Return the uppercase letter if the message is a single A-Z letter.

    Used by the router to short-circuit quiz answers before hitting the
    LLM. Strips whitespace; anything else returns None.
    """
    if not p.text:
        return None
    m = _ANSWER_RE.match(p.text)
    if not m:
        return None
    return m.group(1).upper()


def is_active_quiz_in(chat_id: int | str) -> bool:
    return get_active_quiz(chat_id) is not None


def record_answer(p: Prepared, letter: str) -> None:
    """Stage 2 stub — records nothing yet. Stage 6 implements persistence,
    reaction, score update, and de-dupe-by-user."""
    # Ensures the router's call site compiles and logs for visibility.
    print(f"[ta.quiz] TODO record_answer: chat={p.chat_id} user={p.user_id} ans={letter}")


def react_invalid(p: Prepared) -> None:
    """Stage 2 stub — will emit the 🤔 reaction in stage 6."""
    print(f"[ta.quiz] TODO react_invalid: chat={p.chat_id} msg={p.message.message_id}")
