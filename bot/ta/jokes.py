"""LLM-backed joke generation for the /joke command.

Open to all users (not admin-gated). Routed in ``bot/ta/admin.py`` before
the admin gate, same as ``/feedback``.
"""
from __future__ import annotations

from bot.clients import ai
from bot.config import DEFAULT_MODEL
from bot.ta.state import get_active_model


# Cap the theme so a student can't smuggle a novel into the prompt.
MAX_THEME_LEN = 300


_SYSTEM_PROMPT = (
    "You are a witty comedian writing jokes for a classroom of students. "
    "Reply with ONLY the joke itself — no preamble, no 'Here's a joke:', "
    "no explanation. Keep it to 3 sentences or fewer. Keep it clean, kind, "
    "and appropriate for a school setting — no insults aimed at a specific "
    "real person, no profanity, no stereotypes."
)


def generate_joke(theme: str, group_key: str | None = None) -> str | None:
    """Ask the LLM for a short, clean joke on ``theme``.

    Returns the joke text, or ``None`` if the LLM call failed or returned
    an empty string. ``group_key`` is used to honor the per-group active
    model so ``/model <name>`` switches apply here too.
    """
    theme = (theme or "").strip()[:MAX_THEME_LEN]
    if theme:
        user_prompt = f"Tell me one short, clean, family-friendly joke about: {theme}"
    else:
        user_prompt = "Tell me one short, clean, family-friendly joke."

    model = (get_active_model(group_key) if group_key else None) or DEFAULT_MODEL
    try:
        resp = ai.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        reply = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[ta.jokes] generate error: {e}")
        return None

    return reply or None
