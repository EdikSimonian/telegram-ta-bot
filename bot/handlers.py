"""Telegram handler wiring.

Every message and command flows through a single router in
``bot.ta.admin``. Handlers registered here are thin: they exist only to
satisfy pyTelegramBotAPI's decorator-based dispatch so that commands and
free-form text both end up in the same place.

``my_chat_member`` events (group join/leave) are handled separately —
they are not ``Message`` updates, so telebot dispatches them via a
different decorator.
"""
from __future__ import annotations

import os
from datetime import datetime

from bot.clients import bot, BOT_INFO
from bot.ta import admin as ta_admin
from bot.ta.state import register_group, unregister_group
from bot.ta.welcome import send_group_welcome_once


VERBOSE_LOG = os.environ.get("BOT_VERBOSE_LOG", "").strip().lower() in ("1", "true", "yes", "on")


def _log(message, direction: str, text: str) -> None:
    """One-line trace for local dev. No-op in production."""
    if not VERBOSE_LOG:
        return
    user = getattr(message, "from_user", None)
    user_name = (
        f"@{user.username}"
        if user and user.username
        else (getattr(user, "first_name", None) or f"user:{getattr(user, 'id', '?')}")
    )
    bot_name = f"@{BOT_INFO.username}"
    snippet = (text or "").replace("\n", " ").replace("\r", " ")
    if len(snippet) > 500:
        snippet = snippet[:500] + "..."
    sender, receiver = (user_name, bot_name) if direction == "in" else (bot_name, user_name)
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {sender} → {receiver}: {snippet}", flush=True)


# ── Single catch-all: both commands and plain text go to the router ───────
@bot.message_handler(content_types=["text"])
def _route_text(message) -> None:
    _log(message, "in", getattr(message, "text", "") or "")
    ta_admin.route(message)


# ── Group membership changes ──────────────────────────────────────────────
@bot.my_chat_member_handler()
def _on_my_chat_member(update) -> None:
    """Fired when the bot is added to or removed from a chat."""
    try:
        chat = update.chat
        new_status = getattr(update.new_chat_member, "status", "")
        title = getattr(chat, "title", None) or f"chat:{chat.id}"

        if new_status in ("member", "administrator"):
            # Bot was added (or promoted to admin) — register + welcome.
            send_group_welcome_once(chat.id, title)
        elif new_status in ("left", "kicked"):
            unregister_group(chat.id)
        # "restricted" and other intermediate states are ignored.
    except Exception as e:
        print(f"[handlers] my_chat_member error: {e}")
