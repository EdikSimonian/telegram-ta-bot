"""Joke generation via the configured LLM.

The router in ``bot/ta/admin.py`` calls ``generate`` when a user runs
``/joke <theme>``. Kept in its own module so the system prompt and any
future tuning (model override, format) live away from the dispatcher.
"""
from __future__ import annotations

from bot.clients import ai
from bot.config import DEFAULT_MODEL


_SYSTEM_PROMPT = (
    "You are a witty joke generator for a classroom chat. "
    "Produce ONE short, clean, family-friendly joke on the theme the user gives you. "
    "Keep it to 1-3 lines. No preamble, no disclaimers, no apologies — just the joke. "
    "Match the language the theme is written in (English, Armenian, or Russian)."
)

# Themes can arrive as "about python" or "someone coming late" — strip a
# leading "about" so both shapes produce a clean prompt.
_LEADING_ABOUT = ("about ", "on ")


def _clean_theme(theme: str) -> str:
    t = (theme or "").strip()
    lower = t.lower()
    for prefix in _LEADING_ABOUT:
        if lower.startswith(prefix):
            return t[len(prefix):].strip()
    return t


def generate(theme: str, model: str | None = None) -> str | None:
    """Generate a joke for ``theme``. Returns None on LLM failure."""
    cleaned = _clean_theme(theme)
    if not cleaned:
        return None
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"Theme: {cleaned}"},
    ]
    try:
        resp = ai.chat.completions.create(
            model=model or DEFAULT_MODEL,
            messages=messages,
        )
        reply = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[ta.joke] LLM error: {e}")
        return None
    return reply or None
