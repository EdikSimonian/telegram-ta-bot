"""Extract normalized fields from a Telegram message.

The router in ``bot/ta/admin.py`` and handlers consume the dataclass here
rather than poking at the raw telebot message. Keeps downstream code
testable and stops subtle bugs where a field exists only sometimes
(``reply_to_message``, ``entities``, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bot.clients import BOT_INFO
from bot.config import PERMANENT_ADMIN
from bot.ta.state import (
    is_admin,
    resolve_group_key,
    thread_slug,
)


@dataclass
class Prepared:
    message: Any
    chat_id: int | str
    chat_type: str            # "private" | "group" | "supergroup" | "channel"
    user_id: int
    username: str | None      # lowercase, no "@"
    first_name: str | None
    text: str                 # original text, untouched
    stripped_text: str        # text with bot mention removed, trimmed
    is_dm: bool
    is_mention: bool          # bot was @-mentioned in this message
    is_command: bool
    command: str | None       # lowercased, no leading slash
    command_args: str         # everything after the command word
    is_reply_to_bot: bool
    reply_to_username: str | None
    mentions_other_user: bool  # any @-mention that isn't the bot
    is_admin: bool
    is_instructor: bool       # sender == PERMANENT_ADMIN
    group_key: str
    thread_slug: str


def _strip_mention(text: str, bot_username: str | None) -> str:
    if not text:
        return ""
    if not bot_username:
        return text.strip()
    return text.replace(f"@{bot_username}", "").replace(f"@{bot_username.lower()}", "").strip()


def _parse_command(text: str, bot_username: str | None) -> tuple[bool, str | None, str]:
    if not text or not text.startswith("/"):
        return False, None, ""
    head, _, rest = text.strip().partition(" ")
    cmd = head[1:]
    # Handle "/cmd@botname"
    if "@" in cmd:
        cmd, _, target = cmd.partition("@")
        if bot_username and target.lower() != bot_username.lower():
            # Command explicitly aimed at another bot — ignore as command.
            return False, None, ""
    return True, cmd.lower(), rest.strip()


def _entity_mentions(message) -> list[str]:
    """Return the set of @-usernames mentioned via entities, lowercase, no @."""
    out: list[str] = []
    entities = getattr(message, "entities", None) or []
    text = getattr(message, "text", "") or ""
    for ent in entities:
        etype = getattr(ent, "type", None)
        if etype != "mention":
            continue
        offset = getattr(ent, "offset", 0)
        length = getattr(ent, "length", 0)
        frag = text[offset : offset + length]
        if frag.startswith("@"):
            out.append(frag[1:].lower())
    return out


def prepare(message) -> Prepared:
    chat = message.chat
    chat_type = getattr(chat, "type", "private")
    chat_id = chat.id
    is_dm = chat_type == "private"

    user = message.from_user
    user_id = getattr(user, "id", 0)
    raw_username = getattr(user, "username", None)
    username = raw_username.lower() if raw_username else None
    first_name = getattr(user, "first_name", None)

    text = getattr(message, "text", "") or ""
    bot_username = getattr(BOT_INFO, "username", None)

    mentions = _entity_mentions(message)
    is_mention = bool(bot_username and bot_username.lower() in mentions)
    mentions_other_user = any(m != (bot_username or "").lower() for m in mentions)

    reply_to = getattr(message, "reply_to_message", None)
    is_reply_to_bot = False
    reply_to_username: str | None = None
    if reply_to is not None:
        reply_user = getattr(reply_to, "from_user", None)
        if reply_user is not None:
            reply_uname = getattr(reply_user, "username", None)
            if reply_uname:
                reply_to_username = reply_uname.lower()
            if bot_username and reply_uname and reply_uname.lower() == bot_username.lower():
                is_reply_to_bot = True

    is_command, command, command_args = _parse_command(text, bot_username)
    stripped = _strip_mention(text, bot_username)

    is_admin_flag    = is_admin(username)
    is_instructor    = (username or "") == PERMANENT_ADMIN

    return Prepared(
        message=message,
        chat_id=chat_id,
        chat_type=chat_type,
        user_id=user_id,
        username=username,
        first_name=first_name,
        text=text,
        stripped_text=stripped,
        is_dm=is_dm,
        is_mention=is_mention,
        is_command=is_command,
        command=command,
        command_args=command_args,
        is_reply_to_bot=is_reply_to_bot,
        reply_to_username=reply_to_username,
        mentions_other_user=mentions_other_user and not is_mention,
        is_admin=is_admin_flag,
        is_instructor=is_instructor,
        group_key=resolve_group_key(chat_type, chat_id),
        thread_slug=thread_slug(chat_type, chat_id, user_id),
    )


def prompt_prefix(p: Prepared) -> str:
    """Build the prefix inserted ahead of the user's text before the LLM.

    Order matches §5.9 of the spec: instructor > direct > reply-to > DM.
    """
    parts: list[str] = []
    if p.is_instructor:
        parts.append(f"[INSTRUCTOR @{PERMANENT_ADMIN}]:")
    if p.is_mention or p.is_dm:
        parts.append("[DIRECT]:")
    if (
        p.reply_to_username
        and not p.is_reply_to_bot
        and not p.is_mention
    ):
        parts.append(f"[REPLY_TO @{p.reply_to_username}]:")
    if p.is_dm:
        parts.append("[DM]:")
    return " ".join(parts)
