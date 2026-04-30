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
    mark_dm_welcomed,
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
            # Consume the once-gate so the next non-command DM doesn't
            # re-send the welcome. /start always sends; the gate only
            # matters for regular messages.
            mark_dm_welcomed(p.user_id)
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

    # 3b. /feedback is open to ALL users (students included).
    #     Handle it before the admin gate so non-admins aren't blocked.
    if p.is_command and p.command == "feedback":
        if not p.is_dm:
            # In groups: delete for privacy, reply via DM.
            delete_message(p.chat_id, p.message.message_id)
        if p.is_admin:
            # Admins get the full sub-commands (list, clear, submit).
            commands.dispatch(p)
        else:
            # Students: store the feedback text.
            from bot.ta.state import add_feedback

            text = (p.command_args or "").strip()
            if not text:
                send_message(p.user_id, "Usage: /feedback <text>")
            else:
                add_feedback(text, p.username)
                send_message(p.user_id, "\u2705 Feedback received. Thank you!")
        return

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
                    f"\u26a0\ufe0f You've hit the rate limit of {TA_RATE_LIMIT} "
                    f"questions per hour. Try again later.",
                )
            return

    # 11b. Pre-gate: plain group chatter that doesn't look like a question
    #      shouldn't pay for an embedding + chat completion just for the
    #      model to return IGNORE. Addressed messages (DM, mention,
    #      reply-to-bot) and admin messages always pass through.
    addressed = p.is_dm or p.is_mention or p.is_reply_to_bot
    if not addressed and not p.is_admin:
        if not _looks_like_question(p.stripped_text or p.text or ""):
            return

    # 12. Otherwise: RAG + LLM. Delegated to the Q&A handler which Stage 5
    #     will replace with the RAG-enabled version.
    _answer_question(p)


# Question-mark glyphs across the languages the workshop uses (English /
# Russian / Armenian). Matched anywhere in the message.
_QUESTION_MARKS = ("?", "\u055e", "\u061f")

# Words that, when they're the first token of a message, strongly suggest
# the user is asking a question even when no "?" is present. Conservative
# (no "do/does/has/have/was/were") to keep statement false-positives low.
_INTERROGATIVE_STARTERS = {
    # English
    "what",
    "who",
    "why",
    "when",
    "where",
    "how",
    "which",
    "can",
    "could",
    "should",
    "would",
    "will",
    "is",
    "are",
    # Russian
    "\u0447\u0442\u043e",
    "\u043a\u0442\u043e",
    "\u043f\u043e\u0447\u0435\u043c\u0443",
    "\u0437\u0430\u0447\u0435\u043c",
    "\u043a\u043e\u0433\u0434\u0430",
    "\u0433\u0434\u0435",
    "\u043a\u0430\u043a",
    "\u043a\u0430\u043a\u043e\u0439",
    "\u043a\u0430\u043a\u0430\u044f",
    "\u043a\u0430\u043a\u043e\u0435",
    "\u043a\u0430\u043a\u0438\u0435",
    "\u043c\u043e\u0436\u043d\u043e",
    # Armenian
    "\u056b\u0576\u0579",
    "\u0578\u057e",
    "\u056b\u0576\u0579\u0578\u0582",
    "\u0565\u0580\u0562",
    "\u0578\u0580\u057f\u0565\u0572",
    "\u056b\u0576\u0579\u057a\u0565\u057d",
    "\u0578\u0580",
}

# Below this length a non-question is almost always chatter ("lol", "thanks",
# emoji-only). Above it the message has enough substance to be worth
# spending an LLM call on even without an explicit "?".
_QUESTION_MIN_LEN = 50

_TRIM_CHARS = ".,!:;()[]{}'\"\u055e\u061f"


def _looks_like_question(text: str) -> bool:
    """Cheap heuristic for "is this likely a question worth answering?"

    Three signals, any one is enough: a "?" anywhere, a first token in
    ``_INTERROGATIVE_STARTERS``, or length \u2265 50 chars. Mistakes here are
    recoverable: students can re-ask with a "?" or @-mention the bot.
    """
    s = (text or "").strip()
    if not s:
        return False
    if any(q in s for q in _QUESTION_MARKS):
        return True
    first = s.split(maxsplit=1)[0].lower().strip(_TRIM_CHARS)
    if first in _INTERROGATIVE_STARTERS:
        return True
    return len(s) >= _QUESTION_MIN_LEN


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
