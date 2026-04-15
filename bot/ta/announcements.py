"""Two-step announcement flow. Stage 2 scaffolding only — Stage 8 fills in."""
from __future__ import annotations

from bot.ta.prepare import Prepared
from bot.ta.state import clear_pending_announcement, get_pending_announcement
from bot.ta.tg import send_message


def has_pending(user_id: int) -> bool:
    return get_pending_announcement(user_id) is not None


def handle_reply(p: Prepared) -> bool:
    """Consume an admin DM that might confirm or cancel a pending announcement.

    Returns True when the message was consumed (send it / cancel), False
    when it should fall through to the normal handler. Stage 2 stub: we
    recognize 'cancel' and discard, ignore 'send it' until Stage 8.
    """
    text = (p.text or "").strip().lower()
    if text == "cancel":
        clear_pending_announcement(p.user_id)
        send_message(p.user_id, "Announcement cancelled.")
        return True
    if text == "send it":
        send_message(p.user_id, "Announcement send is not yet implemented (Stage 8).")
        return True
    return False
