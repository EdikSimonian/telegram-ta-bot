from unittest.mock import patch, MagicMock


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
):
    chat = MagicMock()
    chat.id = chat_id
    chat.type = chat_type

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
    return m


def _entity(offset, length, etype="mention"):
    ent = MagicMock()
    ent.type = etype
    ent.offset = offset
    ent.length = length
    return ent


# ── Basic DM + group detection ────────────────────────────────────────────
def test_prepare_detects_dm():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare
        p = prepare(_msg(chat_type="private", chat_id=42, text="hi"))
        assert p.is_dm is True
        assert p.group_key == "default"
        assert p.thread_slug == "tg-dm-42"


def test_prepare_detects_group():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare
        p = prepare(_msg(chat_type="supergroup", chat_id=-100123, text="hi"))
        assert p.is_dm is False
        assert p.group_key == "-100123"
        assert p.thread_slug == "tg-group-100123"


# ── Instructor detection ──────────────────────────────────────────────────
def test_prepare_instructor_from_permanent_admin():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare
        p = prepare(_msg(username="ediksimonian"))
        assert p.is_instructor is True
        assert p.is_admin is True


def test_prepare_non_admin_regular_user():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare
        p = prepare(_msg(username="student1"))
        assert p.is_instructor is False
        assert p.is_admin is False


# ── Bot mention detection ─────────────────────────────────────────────────
def test_prepare_detects_bot_mention_via_entities():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare
        text = "Hey @testbot can you help?"
        ent = _entity(offset=4, length=len("@testbot"))
        p = prepare(_msg(text=text, entities=[ent]))
        assert p.is_mention is True
        assert "@testbot" not in p.stripped_text


def test_prepare_mentions_other_user_not_bot():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare
        text = "Thanks @otherstudent"
        ent = _entity(offset=7, length=len("@otherstudent"))
        p = prepare(_msg(text=text, entities=[ent]))
        assert p.is_mention is False
        assert p.mentions_other_user is True


# ── Commands ──────────────────────────────────────────────────────────────
def test_prepare_parses_slash_command():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare
        p = prepare(_msg(text="/quiz python basics"))
        assert p.is_command is True
        assert p.command == "quiz"
        assert p.command_args == "python basics"


def test_prepare_accepts_command_aimed_at_our_bot():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare
        p = prepare(_msg(text="/help@testbot"))
        assert p.is_command is True
        assert p.command == "help"


def test_prepare_rejects_command_aimed_at_other_bot():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare
        p = prepare(_msg(text="/help@otherbot"))
        assert p.is_command is False
        # command_target is preserved even when the command is rejected,
        # so _bookkeep can distinguish off-target /cmd from ordinary chatter.
        assert p.command_target == "otherbot"


def test_prepare_command_target_is_none_for_bare_command():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare
        p = prepare(_msg(text="/quiz python"))
        assert p.command_target is None


def test_prepare_command_target_set_for_our_bot():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare
        p = prepare(_msg(text="/help@testbot"))
        assert p.command_target == "testbot"


def test_prepare_plain_text_not_command():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare
        p = prepare(_msg(text="how do I learn python"))
        assert p.is_command is False
        assert p.command is None


# ── Reply-to ──────────────────────────────────────────────────────────────
def test_prepare_detects_reply_to_bot():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare
        reply = _msg(user_id=42, username="testbot")
        p = prepare(_msg(text="thanks", reply_to=reply))
        assert p.is_reply_to_bot is True
        # We should not emit REPLY_TO when replying to the bot itself.


def test_prepare_detects_reply_to_other_user():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare
        reply = _msg(user_id=99, username="student9")
        p = prepare(_msg(text="good point", reply_to=reply))
        assert p.is_reply_to_bot is False
        assert p.reply_to_username == "student9"


# ── prompt_prefix ─────────────────────────────────────────────────────────
def test_prompt_prefix_instructor_in_group():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare, prompt_prefix
        p = prepare(_msg(username="ediksimonian", text="test"))
        pref = prompt_prefix(p)
        assert "[INSTRUCTOR @ediksimonian]:" in pref


def test_prompt_prefix_direct_via_mention():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare, prompt_prefix
        text = "@testbot hi"
        ent = _entity(offset=0, length=len("@testbot"))
        p = prepare(_msg(text=text, entities=[ent]))
        pref = prompt_prefix(p)
        assert "[DIRECT]:" in pref


def test_prompt_prefix_reply_to_other_no_mention():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare, prompt_prefix
        reply = _msg(user_id=99, username="student9")
        p = prepare(_msg(text="nice", reply_to=reply))
        pref = prompt_prefix(p)
        assert "[REPLY_TO @student9]:" in pref


def test_prompt_prefix_dm_emits_dm_marker():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare, prompt_prefix
        p = prepare(_msg(chat_type="private", chat_id=42, text="hi"))
        pref = prompt_prefix(p)
        assert "[DM]:" in pref
        assert "[DIRECT]:" in pref  # DM counts as direct


def test_prompt_prefix_empty_for_plain_group_msg():
    with patch("bot.ta.state.redis", None):
        from bot.ta.prepare import prepare, prompt_prefix
        p = prepare(_msg(username="student1", text="hello"))
        pref = prompt_prefix(p)
        assert pref == ""
