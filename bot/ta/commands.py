"""Admin command dispatcher.

Stage 2 scaffolding: the dispatcher exists and is wired into the router,
but most commands return a "not yet implemented" notice. Stage 3 fills
in /help, /info, /admins, /addadmin, /removeadmin, /reset, /model,
/setgroup. Later stages add /quiz, /stats, /grade, /doc, /announce,
/purge, /reveal.

Each command handler is called with the ``Prepared`` dataclass so it has
the pre-parsed message context.
"""
from __future__ import annotations

from bot.ta.prepare import Prepared
from bot.ta.tg import send_message


IMPLEMENTED: dict[str, str] = {}  # populated by @register decorator in stage 3


def dispatch(p: Prepared) -> None:
    """Route an admin command to its handler.

    The message is always delivered in DM to the admin (replies in DM per
    spec). If this was sent in a group the router has already deleted the
    original command message.
    """
    cmd = p.command or ""
    handler = IMPLEMENTED.get(cmd)
    if handler is None:
        send_message(
            p.user_id,
            f"Command /{cmd} is not yet implemented.\n"
            "See CLAUDE.md or README.md for the roadmap.",
        )
        return
    handler(p)
