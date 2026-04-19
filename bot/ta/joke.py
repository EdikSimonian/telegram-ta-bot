"""Joke generation for the /joke admin command.

Flow:
    /joke [theme]   → generate a short joke via LLM → post to current chat
                      (or active group if invoked from DM)

The theme is free-form. Examples from the help text:
    /joke
    /joke about python
    /joke about someone coming late

When ``theme`` is empty, the LLM is asked to pick a fun subject on its own.
"""
from __future__ import annotations

from bot.clients import ai
from bot.config import DEFAULT_MODEL
from bot.ta.state import get_active_model
from bot.ta.tg import send_message


def _build_prompt(theme: str) -> str:
    cleaned = (theme or "").strip()
    if cleaned:
        topic = f"the topic: {cleaned}"
    else:
        topic = "any fun subject (programming, AI, daily life — pick one)"
    return (
        "You are a comedian for a classroom of teenagers. Tell exactly ONE "
        "short, family-friendly, tasteful joke. "
        f"Make it about {topic}.\n\n"
        "Rules:\n"
        "- 1-3 sentences MAX. Punchy delivery.\n"
        "- No preamble like 'Sure!' or 'Here's a joke:'. Just the joke.\n"
        "- No offensive, political, religious, or NSFW content.\n"
        "- Plain text only — no Markdown, no HTML."
    )


def generate_joke(theme: str, group_key: str) -> str | None:
    """Return a joke about ``theme`` from the LLM, or None on failure."""
    prompt = _build_prompt(theme)
    model = get_active_model(group_key) or DEFAULT_MODEL
    try:
        resp = ai.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        choices = getattr(resp, "choices", None) or []
        if not choices:
            return None
        message = getattr(choices[0], "message", None)
        raw = getattr(message, "content", "") or ""
        if not isinstance(raw, str):
            return None
        raw = raw.strip()
    except Exception as e:
        print(f"[ta.joke] generate error: {e}")
        return None
    return raw or None


def format_joke_for_display(theme: str, joke: str) -> str:
    cleaned = (theme or "").strip()
    header = f"😂 Joke — {cleaned}" if cleaned else "😂 Joke"
    return f"{header}\n\n{joke}"


def tell_joke(theme: str, group_key: str, target_chat: int | str) -> bool:
    """Generate and post a joke. Returns True if a joke was sent."""
    joke = generate_joke(theme, group_key)
    if not joke:
        return False
    text = format_joke_for_display(theme, joke)
    msg_id = send_message(target_chat, text)
    return msg_id is not None
