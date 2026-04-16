"""Main message router. Implements the precedence in spec §5.2.

Every inbound Telegram text update flows through ``route(message)``.
Actions live in sibling modules; this file is pure dispatch.
"""
from __future__ import annotations

import traceback

from bot.clients import bot
from bot.config import TA_RATE_LIMIT, TA_RATE_LIMIT_WINDOW
from bot.ta import announcements, commands, quiz, welcome
from bot.ta.prepare import Prepared, prepare
from bot.ta.state import (
    bump_message_count,
    list_groups as _list_groups,
    register_group,
    remember_user_chat,
    ta_rate_check_and_inc,
    ta_rate_should_notify,
)
from bot.ta.tg import delete_message, send_message


def _bookkeep(p: Prepared) -> None:
    """Side effects that should happen for every message, regardless of routing."""
    # Learn user → chat id mapping so /admin add can DM new TAs.
    remember_user_chat(p.username, p.user_id)
    if not p.is_dm and p.user_id:
        # Track participation.
        bump_message_count(p.group_key, p.user_id, p.username, p.first_name)
        # Fallback auto-register for groups the bot is already in when the
        # webhook was first registered: my_chat_member only fires for NEW
        # joins, so pre-existing memberships would otherwise stay invisible
        # to /group and /announce. First message in the group triggers a
        # register. register_group is idempotent on the hash key.
        chat = getattr(p.message, "chat", None)
        title = getattr(chat, "title", None) or f"chat:{p.chat_id}"
        if not any(str(g.get("chatId")) == str(p.chat_id) for g in _list_groups()):
            register_group(p.chat_id, title)


def _should_rate_limit(p: Prepared) -> bool:
    """Rate limit applies to students in groups without direct mention.

    Admins, direct mentions, DMs, and replies-to-bot are exempt.
    """
    if p.is_admin:
        return False
    if p.is_dm:
        return False
    if p.is_mention or p.is_reply_to_bot:
        return False
    return True


def route(message) -> None:
    try:
        p = prepare(message)
    except Exception:
        traceback.print_exc()
        return

    try:
        _bookkeep(p)
    except Exception:
        traceback.print_exc()

    # 3. /start always re-welcomes (not gated by the once-flag). In groups
    #    we send the group welcome and delete the command message to keep
    #    the chat clean.
    if p.is_command and p.command == "start":
        if p.is_dm:
            from bot.clients import bot as _bot
            _bot.send_message(p.chat_id, welcome.DM_WELCOME)
        else:
            from bot.clients import bot as _bot
            _bot.send_message(p.chat_id, welcome.GROUP_WELCOME)
            delete_message(p.chat_id, p.message.message_id)
        return

    # 2. DM first-time welcome (gated). After the first DM the user sees, we
    #    never send this again and normal routing takes over.
    if p.is_dm and welcome.send_dm_welcome_once(p.chat_id, p.user_id):
        return

    # 5. Admin + DM with a pending announcement confirmation.
    #    Checked BEFORE admin command dispatch so the admin can't accidentally
    #    run a command while they have a pending announcement.
    if p.is_admin and p.is_dm and announcements.has_pending(p.user_id):
        if announcements.handle_reply(p):
            return
        # Unrecognized reply → fall through to normal processing without
        # clearing the pending state (spec §5.12).

    # 4. Admin + command.
    if p.is_admin and p.is_command:
        if not p.is_dm:
            delete_message(p.chat_id, p.message.message_id)
        commands.dispatch(p)
        return

    # 6. Non-admin + command in a group → silent delete.
    if p.is_command and not p.is_admin and not p.is_dm:
        delete_message(p.chat_id, p.message.message_id)
        return

    # 7/8. Quiz answers while a quiz is active in this chat.
    if not p.is_dm and quiz.is_active_quiz_in(p.chat_id):
        # Inline fallback: QStash dropped the callback? Reveal now and let
        # the current message flow through as normal chatter.
        if quiz.maybe_inline_reveal(p.chat_id):
            pass  # fall through — quiz is over, message is just text
        else:
            letter = quiz.maybe_single_letter(p)
            if letter:
                if letter in ("A", "B", "C", "D"):
                    quiz.record_answer(p, letter)
                else:
                    quiz.react_invalid(p)
                return
            # Any non-letter text during a live quiz: shush and skip LLM.
            # Keeps the transcript clean while students are answering.
            quiz.react_quiet(p)
            return

    # 10. Mention of another user that is NOT the bot → ignore.
    if p.mentions_other_user and not p.is_mention:
        return

    # 11. Rate limit.
    if _should_rate_limit(p):
        allowed, _remaining = ta_rate_check_and_inc(
            p.user_id, TA_RATE_LIMIT, TA_RATE_LIMIT_WINDOW
        )
        if not allowed:
            if ta_rate_should_notify(p.user_id):
                send_message(
                    p.chat_id,
                    f"\u26A0\uFE0F You've hit the rate limit of {TA_RATE_LIMIT} "
                    f"questions per hour. Try again later.",
                )
            return

    # 12. Otherwise: RAG + LLM. Delegated to the Q&A handler which Stage 5
    #     will replace with the RAG-enabled version.
    _answer_question(p)


_STUDENT_GROUP_WAIT_SECONDS = 3


def _answer_question(p: Prepared) -> None:
    """Run the RAG + LLM pipeline and send the reply.

    Typing indicator only fires when we're confident a reply is coming —
    DMs, @mentions, and replies-to-bot. For plain group chatter the LLM
    will most likely return IGNORE, so a typing bubble that appears and
    disappears looks broken; better to stay silent and let the rare
    legitimate answer just pop in.
    """
    from bot.ai import answer
    from bot.helpers import keep_typing, send_reply

    addressed = p.is_dm or p.is_mention or p.is_reply_to_bot

    # 3-second wait in groups before answering plain chatter (§5.4) so a
    # human can reply first. Skip for direct addresses + admins.
    if not addressed and not p.is_admin:
        import time
        time.sleep(_STUDENT_GROUP_WAIT_SECONDS)

    try:
        if addressed:
            with keep_typing(p.chat_id):
                reply = answer(p)
        else:
            reply = answer(p)
        if reply:
            send_reply(p.message, reply)
    except Exception as e:
        print(f"[ta.admin] _answer_question error: {e}")
        traceback.print_exc()
        if addressed:
            bot.send_message(p.chat_id, "Something went wrong. Please try again.")
