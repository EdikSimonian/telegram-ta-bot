"""Two-step /announce flow.

    admin: /announce Class cancelled Monday
    bot:   📣 Announcement Preview: ... reply 'send it' or 'cancel'.
    admin: send it
    bot:   (posts to active group) + confirmation DM
"""
from __future__ import annotations

import html

from bot.ta.prepare import Prepared
from bot.ta.state import (
    clear_pending_announcement,
    get_active_group_id,
    get_pending_announcement,
    set_pending_announcement,
)
from bot.ta.tg import send_message


def has_pending(user_id: int) -> bool:
    return get_pending_announcement(user_id) is not None


def start(p: Prepared) -> None:
    """Stage the announcement and DM the admin a preview."""
    text = (p.command_args or "").strip()
    if not text:
        send_message(p.user_id, "Usage: /announce <message>")
        return
    target = get_active_group_id()
    if not target:
        send_message(p.user_id, "No active group. Set one with /group first.")
        return
    set_pending_announcement(p.user_id, text, target)
    send_message(
        p.user_id,
        "📣 <b>Announcement Preview</b>\n\n"
        f"{html.escape(text)}\n\n"
        f"Target: <code>{target}</code>\n"
        "Reply <b>send it</b> to post, or <b>cancel</b> to discard.",
        parse_mode="HTML",
    )


def handle_reply(p: Prepared) -> bool:
    """Consume a follow-up DM that confirms or cancels a staged announcement.

    Returns True when the router should stop processing (we handled it),
    False when the text was something else and should fall through to
    normal routing.
    """
    pending = get_pending_announcement(p.user_id)
    if pending is None:
        return False

    text = (p.text or "").strip().lower()
    if text == "cancel":
        clear_pending_announcement(p.user_id)
        send_message(p.user_id, "Announcement cancelled.")
        return True

    if text == "send it":
        target = pending.get("groupChatId")
        body = pending.get("text") or ""
        if not target or not body:
            clear_pending_announcement(p.user_id)
            send_message(p.user_id, "Pending announcement was malformed — discarded.")
            return True
        try:
            send_message(target, f"📣 <b>Announcement</b>\n\n{html.escape(body)}", parse_mode="HTML")
            send_message(p.user_id, f"✅ Posted to <code>{target}</code>.", parse_mode="HTML")
        except Exception as e:
            send_message(p.user_id, f"Failed to post announcement: {e}")
        clear_pending_announcement(p.user_id)
        return True

    # Anything else — let the message fall through. We do NOT clear the
    # pending state; the admin can still reply 'send it' later.
    return False
