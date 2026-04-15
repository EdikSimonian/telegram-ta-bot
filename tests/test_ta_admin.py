"""Router precedence tests — one test per §5.2 rule.

We call ``route(message)`` with a synthetic telebot Message, then assert
which side effects fired using patched sentinels. The goal is behavior,
not internals: each test names the rule it exercises.
"""
from unittest.mock import MagicMock, patch


def _msg(
    *,
    chat_id=-100123,
    chat_type="supergroup",
    user_id=42,
    username=None,
    first_name="Alice",
    text="",
    entities=None,
    reply_to=None,
    message_id=7,
):
    chat = MagicMock()
    chat.id = chat_id
    chat.type = chat_type
    chat.title = "Workshop"

    user = MagicMock()
    user.id = user_id
    user.username = username
    user.first_name = first_name

    m = MagicMock()
    m.chat = chat
    m.from_user = user
    m.text = text
    m.entities = entities or []
    m.reply_to_message = reply_to
    m.message_id = message_id
    return m


def _entity(offset, length, etype="mention"):
    ent = MagicMock()
    ent.type = etype
    ent.offset = offset
    ent.length = length
    return ent


def _patches(**overrides):
    """Patch the network-adjacent bits of bot.ta.admin; return the stack."""
    defaults = {
        "is_admin":               False,
        "is_pending_announcement": False,
        "welcomed_already":        True,   # DM welcome already sent unless told otherwise
        "quiz_active":             False,
        "rate_allowed":            True,
    }
    defaults.update(overrides)

    stack = []

    # prepare.py looks up is_admin via the state module at call time, so
    # patching one location is sufficient.
    stack.append(patch("bot.ta.state.is_admin", return_value=defaults["is_admin"]))

    stack.append(patch("bot.ta.admin.announcements.has_pending",
                       return_value=defaults["is_pending_announcement"]))
    stack.append(patch("bot.ta.welcome.mark_dm_welcomed",
                       return_value=not defaults["welcomed_already"]))
    stack.append(patch("bot.ta.admin.quiz.is_active_quiz_in",
                       return_value=defaults["quiz_active"]))
    stack.append(patch("bot.ta.admin.ta_rate_check_and_inc",
                       return_value=(defaults["rate_allowed"], 5)))
    stack.append(patch("bot.ta.admin.ta_rate_should_notify", return_value=True))
    stack.append(patch("bot.ta.admin.bump_message_count"))
    stack.append(patch("bot.ta.admin.remember_user_chat"))
    return stack


def _enter(stack):
    mocks = [cm.__enter__() for cm in stack]
    return mocks


def _exit(stack):
    for cm in reversed(stack):
        cm.__exit__(None, None, None)


# ── Rule 3: /start is a no-op (or re-welcome in DM) ───────────────────────
def test_start_in_dm_sends_welcome_once():
    stack = _patches(welcomed_already=False)
    mocks = _enter(stack)
    try:
        with patch("bot.ta.admin.welcome.send_dm_welcome_once") as w, \
             patch("bot.ta.admin.commands.dispatch") as disp, \
             patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(chat_type="private", chat_id=42, text="/start"))
            w.assert_called_once()
            disp.assert_not_called()
            ans.assert_not_called()
    finally:
        _exit(stack)


def test_start_from_student_in_group_gets_deleted():
    stack = _patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.delete_message") as d, \
             patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(username="student", text="/start"))
            d.assert_called_once()
            ans.assert_not_called()
    finally:
        _exit(stack)


# ── Rule 2: first DM gets a welcome, subsequent messages don't ────────────
def test_first_dm_sends_welcome_and_stops():
    stack = _patches(welcomed_already=False)
    _enter(stack)
    try:
        with patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(chat_type="private", chat_id=42, text="hi"))
            ans.assert_not_called()
    finally:
        _exit(stack)


def test_subsequent_dm_falls_through_to_llm():
    stack = _patches(welcomed_already=True)
    _enter(stack)
    try:
        with patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(chat_type="private", chat_id=42, text="hi again"))
            ans.assert_called_once()
    finally:
        _exit(stack)


# ── Rule 4: admin command in group → delete + dispatch ────────────────────
def test_admin_command_in_group_deletes_and_dispatches():
    stack = _patches(is_admin=True)
    _enter(stack)
    try:
        with patch("bot.ta.admin.delete_message") as d, \
             patch("bot.ta.admin.commands.dispatch") as disp:
            from bot.ta.admin import route
            route(_msg(username="alice", text="/help"))
            d.assert_called_once()
            disp.assert_called_once()
    finally:
        _exit(stack)


def test_admin_command_in_dm_dispatches_without_delete():
    stack = _patches(is_admin=True)
    _enter(stack)
    try:
        with patch("bot.ta.admin.delete_message") as d, \
             patch("bot.ta.admin.commands.dispatch") as disp:
            from bot.ta.admin import route
            route(_msg(chat_type="private", chat_id=42, username="alice", text="/help"))
            d.assert_not_called()
            disp.assert_called_once()
    finally:
        _exit(stack)


# ── Rule 5: pending announcement reply ───────────────────────────────────
def test_admin_dm_with_pending_announcement_consumes_send_it():
    stack = _patches(is_admin=True, is_pending_announcement=True)
    _enter(stack)
    try:
        with patch("bot.ta.admin.announcements.handle_reply", return_value=True) as h, \
             patch("bot.ta.admin.commands.dispatch") as disp, \
             patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(chat_type="private", chat_id=42, username="alice", text="send it"))
            h.assert_called_once()
            disp.assert_not_called()
            ans.assert_not_called()
    finally:
        _exit(stack)


def test_admin_dm_with_pending_announcement_falls_through_on_other_text():
    stack = _patches(is_admin=True, is_pending_announcement=True)
    _enter(stack)
    try:
        with patch("bot.ta.admin.announcements.handle_reply", return_value=False), \
             patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(chat_type="private", chat_id=42, username="alice", text="what's up"))
            ans.assert_called_once()
    finally:
        _exit(stack)


# ── Rule 6: non-admin command in group → silent delete ────────────────────
def test_student_command_in_group_deleted_silently():
    stack = _patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.delete_message") as d, \
             patch("bot.ta.admin.commands.dispatch") as disp, \
             patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(username="student", text="/quiz"))
            d.assert_called_once()
            disp.assert_not_called()
            ans.assert_not_called()
    finally:
        _exit(stack)


# ── Rules 7/8: quiz letter answers ────────────────────────────────────────
def test_valid_quiz_letter_records_answer_and_skips_llm():
    stack = _patches(quiz_active=True)
    _enter(stack)
    try:
        with patch("bot.ta.admin.quiz.record_answer") as rec, \
             patch("bot.ta.admin.quiz.react_invalid") as inv, \
             patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(username="student", text="B"))
            rec.assert_called_once()
            inv.assert_not_called()
            ans.assert_not_called()
    finally:
        _exit(stack)


def test_invalid_quiz_letter_reacts_thinking():
    stack = _patches(quiz_active=True)
    _enter(stack)
    try:
        with patch("bot.ta.admin.quiz.record_answer") as rec, \
             patch("bot.ta.admin.quiz.react_invalid") as inv, \
             patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(username="student", text="Z"))
            rec.assert_not_called()
            inv.assert_called_once()
            ans.assert_not_called()
    finally:
        _exit(stack)


def test_single_letter_without_active_quiz_falls_through():
    stack = _patches(quiz_active=False)
    _enter(stack)
    try:
        with patch("bot.ta.admin.quiz.record_answer") as rec, \
             patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(username="student", text="A"))
            rec.assert_not_called()
            ans.assert_called_once()
    finally:
        _exit(stack)


# ── Rule 10: @mention of another user (not bot) → ignored ─────────────────
def test_mention_of_other_user_is_ignored():
    stack = _patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin._answer_question") as ans:
            text = "hey @someone look at this"
            ent = _entity(offset=4, length=len("@someone"))
            from bot.ta.admin import route
            route(_msg(username="student", text=text, entities=[ent]))
            ans.assert_not_called()
    finally:
        _exit(stack)


def test_mention_of_bot_does_reply():
    stack = _patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin._answer_question") as ans:
            text = "hey @testbot help"
            ent = _entity(offset=4, length=len("@testbot"))
            from bot.ta.admin import route
            route(_msg(username="student", text=text, entities=[ent]))
            ans.assert_called_once()
    finally:
        _exit(stack)


# ── Rule 11: rate limit ───────────────────────────────────────────────────
def test_rate_limited_student_gets_one_notice_only():
    stack = _patches(rate_allowed=False)
    _enter(stack)
    try:
        with patch("bot.ta.admin.send_message") as sm, \
             patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(username="student", text="help me"))
            sm.assert_called_once()
            ans.assert_not_called()
    finally:
        _exit(stack)


def test_rate_limit_skipped_for_admins():
    stack = _patches(is_admin=True)
    _enter(stack)
    try:
        with patch("bot.ta.admin.ta_rate_check_and_inc") as rc, \
             patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(username="alice", text="help me"))
            rc.assert_not_called()
            ans.assert_called_once()
    finally:
        _exit(stack)


def test_rate_limit_skipped_for_direct_mention():
    stack = _patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.ta_rate_check_and_inc") as rc, \
             patch("bot.ta.admin._answer_question") as ans:
            text = "@testbot help"
            ent = _entity(offset=0, length=len("@testbot"))
            from bot.ta.admin import route
            route(_msg(username="student", text=text, entities=[ent]))
            rc.assert_not_called()
            ans.assert_called_once()
    finally:
        _exit(stack)


def test_rate_limit_skipped_in_dm():
    stack = _patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.ta_rate_check_and_inc") as rc, \
             patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(chat_type="private", chat_id=42, username="student", text="help"))
            rc.assert_not_called()
            ans.assert_called_once()
    finally:
        _exit(stack)


# ── Rule 12: default path → RAG + LLM ─────────────────────────────────────
def test_plain_student_question_goes_to_llm():
    stack = _patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(username="student", text="what is python"))
            ans.assert_called_once()
    finally:
        _exit(stack)
