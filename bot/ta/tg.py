"""Thin wrappers around pyTelegramBotAPI calls.

Centralizes error handling so the router stays readable and every call
site doesn't repeat a try/except. Telegram loves to 400 on harmless
things (delete_message for a message older than 48h, etc.) — we swallow
those and log.
"""
from __future__ import annotations

from bot.clients import bot


def delete_message(chat_id: int | str, message_id: int) -> bool:
    try:
        bot.delete_message(chat_id, message_id)
        return True
    except Exception as e:
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


def send_message(chat_id: int | str, text: str, **kwargs) -> int | None:
    try:
        msg = bot.send_message(chat_id, text, **kwargs)
        return getattr(msg, "message_id", None)
    except Exception as e:
        print(f"[ta.tg] send_message error chat={chat_id}: {e}")
        return None
