"""Thin wrappers around pyTelegramBotAPI calls.

Centralizes error handling so the router stays readable and every call
site doesn't repeat a try/except. Telegram loves to 400 on harmless
things (delete_message for a message older than 48h, etc.) — we swallow
those and log.
"""

from __future__ import annotations

import sys

from bot.clients import bot


# ── Telegram-rejection tracking ───────────────────────────────────────────
# Telegram 400s (bad HTML entities, "message too long", flood control, etc.)
# were previously swallowed here and the webhook still returned 200 — so a
# broken/missing reply looked like a healthy invocation in Vercel. We now
# record every rejection in a request-scoped list and log it to stderr with a
# grep-friendly marker. api/index.py resets this at the start of each webhook
# and returns 500 if anything was recorded, so rejections show up as errors.
_TG_ERRORS: list[dict] = []


def reset_errors() -> None:
    """Clear the per-request rejection list (call at webhook entry)."""
    _TG_ERRORS.clear()


def errors() -> list[dict]:
    """Return rejections recorded since the last reset_errors()."""
    return list(_TG_ERRORS)


def note_error(op: str, chat_id, exc: Exception, message_id=None) -> None:
    """Record + loudly log a Telegram API failure.

    Extracts Telegram's error_code/description when present (telebot raises
    ApiTelegramException with these) so the Vercel log shows exactly why the
    response was rejected, not just a Python repr.
    """
    code = getattr(exc, "error_code", None)
    desc = getattr(exc, "description", None) or str(exc)
    detail = {
        "op": op,
        "chat_id": chat_id,
        "message_id": message_id,
        "error_code": code,
        "description": desc,
    }
    _TG_ERRORS.append(detail)
    print(
        f"[TELEGRAM-REJECT] op={op} chat={chat_id} msg={message_id} "
        f"code={code} description={desc!r}",
        file=sys.stderr,
        flush=True,
    )


def delete_message(chat_id: int | str, message_id: int) -> bool:
    try:
        bot.delete_message(chat_id, message_id)
        return True
    except Exception as e:
        # delete_message 400s are routinely harmless (message >48h old, already
        # gone). Log but DON'T record as a rejection — it's not a failed reply.
        print(f"[ta.tg] delete_message error chat={chat_id} msg={message_id}: {e}")
        return False


def set_reaction(chat_id: int | str, message_id: int, emoji: str) -> bool:
    """React to a message with a single unicode emoji.

    The telebot ReactionTypeEmoji class is the supported path; fall back
    to a raw Bot API POST if the telebot runtime doesn't expose it.
    """
    try:
        from telebot import types

        reaction = [types.ReactionTypeEmoji(emoji=emoji)]
        bot.set_message_reaction(chat_id, message_id, reaction)
        return True
    except Exception as e:
        print(f"[ta.tg] set_reaction error: {e}")
        return False


def _send_one(chat_id: int | str, text: str, **kwargs) -> int | None:
    try:
        msg = bot.send_message(chat_id, text, **kwargs)
        return getattr(msg, "message_id", None)
    except Exception as e:
        note_error("send_message", chat_id, e)
        return None


def send_message(chat_id: int | str, text: str, **kwargs) -> int | None:
    """Send ``text`` to ``chat_id``, auto-splitting overlong output.

    List commands (/doc list, /git list, /stats, …) build one message from
    ``"\\n".join(lines)``; once enough docs/repos are indexed that busts
    Telegram's 4096-char hard limit and the whole send is rejected with 400
    "message is too long". Split on line boundaries into <=MAX_MSG_LEN chunks —
    each list row is one balanced-HTML line, so a line-boundary split keeps
    every chunk parseable. Returns the message_id of the LAST chunk (callers
    that need the id, e.g. quiz, send short single-message text).
    """
    from bot.config import MAX_MSG_LEN

    if text and len(text) > MAX_MSG_LEN:
        from bot.helpers import _split_for_telegram

        last = None
        for chunk in _split_for_telegram(text, MAX_MSG_LEN):
            last = _send_one(chat_id, chunk, **kwargs)
        return last
    return _send_one(chat_id, text, **kwargs)


def edit_message(chat_id: int | str, message_id: int, text: str, **kwargs) -> bool:
    try:
        bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, **kwargs
        )
        return True
    except Exception as e:
        note_error("edit_message", chat_id, e, message_id=message_id)
        return False


def edit_message_quiet(
    chat_id: int | str, message_id: int, text: str, **kwargs
) -> bool:
    """Best-effort edit that never records a rejection.

    For cosmetic updates (e.g. marking a quiz message expired): a failure
    here — message >48h old, already edited, identical content — must not turn
    the whole webhook into a 500. Editing without a ``reply_markup`` kwarg also
    drops any inline keyboard, which is how we remove a dead quiz's button.
    """
    try:
        bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, **kwargs
        )
        return True
    except Exception as e:
        print(f"[ta.tg] edit_message_quiet error chat={chat_id} msg={message_id}: {e}")
        return False
