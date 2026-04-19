"""Tests for bot/ta/joke.py and the /joke router wiring in bot/ta/admin.py."""
from unittest.mock import MagicMock, patch


# ── joke.generate() ────────────────────────────────────────────────────────
def _ai_returning(text: str) -> MagicMock:
    """Fake OpenAI client with .chat.completions.create returning ``text``."""
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=text))]
    client = MagicMock()
    client.chat.completions.create.return_value = resp
    return client


def test_generate_calls_llm_with_cleaned_theme():
    client = _ai_returning("Why did the dev cross the road? To git pull.")
    with patch("bot.ta.joke.ai", client):
        from bot.ta.joke import generate
        out = generate("about python", model="gpt-5.4-nano")
    assert out == "Why did the dev cross the road? To git pull."
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-5.4-nano"
    messages = kwargs["messages"]
    assert messages[0]["role"] == "system"
    # The "about" prefix must be stripped before being handed to the LLM so
    # the prompt always reads as a clean theme.
    assert messages[1]["content"] == "Theme: python"


def test_generate_strips_on_prefix_too():
    client = _ai_returning("joke")
    with patch("bot.ta.joke.ai", client):
        from bot.ta.joke import generate
        generate("on git merges")
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["messages"][1]["content"] == "Theme: git merges"


def test_generate_keeps_theme_without_prefix():
    client = _ai_returning("joke")
    with patch("bot.ta.joke.ai", client):
        from bot.ta.joke import generate
        generate("someone coming late")
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["messages"][1]["content"] == "Theme: someone coming late"


def test_generate_returns_none_on_empty_theme():
    from bot.ta.joke import generate
    assert generate("") is None
    assert generate("   ") is None


def test_generate_returns_none_when_llm_raises():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("boom")
    with patch("bot.ta.joke.ai", client):
        from bot.ta.joke import generate
        assert generate("python") is None


def test_generate_returns_none_on_blank_llm_reply():
    client = _ai_returning("   ")
    with patch("bot.ta.joke.ai", client):
        from bot.ta.joke import generate
        assert generate("python") is None


def test_generate_returns_none_on_empty_choices():
    # Malformed provider response: choices list is empty.
    resp = MagicMock()
    resp.choices = []
    client = MagicMock()
    client.chat.completions.create.return_value = resp
    with patch("bot.ta.joke.ai", client):
        from bot.ta.joke import generate
        assert generate("python") is None


def test_generate_returns_none_when_message_is_none():
    # Malformed provider response: first choice has message=None.
    resp = MagicMock()
    resp.choices = [MagicMock(message=None)]
    client = MagicMock()
    client.chat.completions.create.return_value = resp
    with patch("bot.ta.joke.ai", client):
        from bot.ta.joke import generate
        assert generate("python") is None


def test_generate_returns_none_when_content_is_none():
    # Malformed provider response: message.content is None.
    client = _ai_returning(None)
    with patch("bot.ta.joke.ai", client):
        from bot.ta.joke import generate
        assert generate("python") is None


def test_generate_returns_none_when_choices_attr_missing():
    # Provider object doesn't expose .choices at all.
    resp = object()
    client = MagicMock()
    client.chat.completions.create.return_value = resp
    with patch("bot.ta.joke.ai", client):
        from bot.ta.joke import generate
        assert generate("python") is None


def test_generate_defaults_to_default_model_when_unset():
    client = _ai_returning("joke")
    with patch("bot.ta.joke.ai", client), \
         patch("bot.ta.joke.DEFAULT_MODEL", "fallback-model"):
        from bot.ta.joke import generate
        generate("python")
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "fallback-model"


# ── Router wiring (_handle_joke via route) ─────────────────────────────────
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


def _router_patches(is_admin=False, rate_allowed=True):
    return [
        patch("bot.ta.state.is_admin", return_value=is_admin),
        patch("bot.ta.admin.announcements.has_pending", return_value=False),
        patch("bot.ta.welcome.mark_dm_welcomed", return_value=False),
        patch("bot.ta.admin.quiz.is_active_quiz_in", return_value=False),
        patch("bot.ta.admin.ta_rate_check_and_inc", return_value=(rate_allowed, 5)),
        patch("bot.ta.admin.ta_rate_should_notify", return_value=True),
        patch("bot.ta.admin.bump_message_count"),
        patch("bot.ta.admin.remember_user_chat"),
    ]


def _enter(stack):
    return [cm.__enter__() for cm in stack]


def _exit(stack):
    for cm in reversed(stack):
        cm.__exit__(None, None, None)


def test_joke_command_in_group_generates_and_posts_reply():
    stack = _router_patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.joke.generate", return_value="ha ha") as gen, \
             patch("bot.ta.admin.delete_message") as d, \
             patch("bot.ta.admin.send_message") as sm, \
             patch("bot.ta.admin.send_reply") as sr:
            from bot.ta.admin import route
            route(_msg(username="student", text="/joke about python"))
            gen.assert_called_once()
            # The theme argument must be passed through verbatim — joke.generate
            # does its own "about " stripping.
            assert gen.call_args.args[0] == "about python"
            sr.assert_called_once()
            assert sr.call_args.args[1] == "ha ha"
            # In groups the joke is public: never delete the command, never
            # DM via send_message — reply in source chat via send_reply.
            d.assert_not_called()
            sm.assert_not_called()
    finally:
        _exit(stack)


def test_joke_command_in_dm_generates_and_posts_reply():
    stack = _router_patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.joke.generate", return_value="lol") as gen, \
             patch("bot.ta.admin.send_reply") as sr, \
             patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            route(_msg(chat_type="private", chat_id=42, username="student",
                       text="/joke someone coming late"))
            gen.assert_called_once()
            assert gen.call_args.args[0] == "someone coming late"
            sr.assert_called_once()
            ans.assert_not_called()
    finally:
        _exit(stack)


def test_joke_command_without_theme_shows_usage():
    stack = _router_patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.joke.generate") as gen, \
             patch("bot.ta.admin.send_message") as sm, \
             patch("bot.ta.admin.send_reply") as sr:
            from bot.ta.admin import route
            route(_msg(username="student", text="/joke"))
            gen.assert_not_called()
            sr.assert_not_called()
            sm.assert_called_once()
            assert "Usage" in sm.call_args.args[1]
    finally:
        _exit(stack)


def test_joke_command_works_for_admins_too():
    """Admins are normally routed through commands.dispatch — /joke short-circuits
    that so admin + non-admin both land in the same joke handler."""
    stack = _router_patches(is_admin=True)
    _enter(stack)
    try:
        with patch("bot.ta.admin.joke.generate", return_value="ha") as gen, \
             patch("bot.ta.admin.commands.dispatch") as disp, \
             patch("bot.ta.admin.send_reply"):
            from bot.ta.admin import route
            route(_msg(username="alice", text="/joke about git"))
            gen.assert_called_once()
            disp.assert_not_called()
    finally:
        _exit(stack)


def test_joke_command_rate_limited_student_in_group_is_blocked():
    stack = _router_patches(rate_allowed=False)
    _enter(stack)
    try:
        with patch("bot.ta.admin.joke.generate") as gen, \
             patch("bot.ta.admin.send_message") as sm, \
             patch("bot.ta.admin.send_reply") as sr:
            from bot.ta.admin import route
            route(_msg(username="student", text="/joke about python"))
            gen.assert_not_called()
            sr.assert_not_called()
            # Rate-limit notice is sent instead of a joke.
            sm.assert_called_once()
            assert "rate limit" in sm.call_args.args[1].lower()
    finally:
        _exit(stack)


def test_joke_command_rate_limit_skipped_for_admins():
    stack = _router_patches(is_admin=True, rate_allowed=False)
    _enter(stack)
    try:
        with patch("bot.ta.admin.joke.generate", return_value="ha") as gen, \
             patch("bot.ta.admin.ta_rate_check_and_inc") as rc, \
             patch("bot.ta.admin.send_reply") as sr:
            from bot.ta.admin import route
            route(_msg(username="alice", text="/joke about git"))
            # Admins bypass the rate limit entirely — the check must not run
            # and the joke must be sent.
            rc.assert_not_called()
            gen.assert_called_once()
            sr.assert_called_once()
    finally:
        _exit(stack)


def test_joke_command_rate_limit_skipped_in_dm():
    stack = _router_patches(rate_allowed=False)
    _enter(stack)
    try:
        with patch("bot.ta.admin.joke.generate", return_value="ha") as gen, \
             patch("bot.ta.admin.ta_rate_check_and_inc") as rc, \
             patch("bot.ta.admin.send_reply") as sr:
            from bot.ta.admin import route
            route(_msg(chat_type="private", chat_id=42, username="student",
                       text="/joke about python"))
            rc.assert_not_called()
            gen.assert_called_once()
            sr.assert_called_once()
    finally:
        _exit(stack)


def test_joke_command_addressed_to_other_bot_does_not_fire_in_group():
    """/joke@OtherBot must NOT run the joke handler in a group — prepare.py
    already filters off-target commands by returning is_command=False, so the
    short-circuit never fires and generate() is never called."""
    stack = _router_patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.joke.generate") as gen, \
             patch("bot.ta.admin.send_message") as sm, \
             patch("bot.ta.admin.send_reply") as sr, \
             patch("bot.ta.admin._answer_question") as ans:
            from bot.ta.admin import route
            # BOT_INFO.username is "testbot" (set in conftest); target "OtherBot"
            # doesn't match, so _parse_command returns is_command=False.
            route(_msg(username="student", text="/joke@OtherBot about python"))
            gen.assert_not_called()
            sr.assert_not_called()
            # Usage help must not be sent either — the message was not a
            # /joke command as far as this bot is concerned.
            for call in sm.call_args_list:
                assert "Usage" not in call.args[1]
    finally:
        _exit(stack)


def test_joke_command_addressed_to_this_bot_still_fires():
    """/joke@testbot about python — the explicit target matches our bot, so
    the joke handler must still run."""
    stack = _router_patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.joke.generate", return_value="ha") as gen, \
             patch("bot.ta.admin.send_reply") as sr:
            from bot.ta.admin import route
            route(_msg(username="student", text="/joke@testbot about python"))
            gen.assert_called_once()
            assert gen.call_args.args[0] == "about python"
            sr.assert_called_once()
    finally:
        _exit(stack)


def test_joke_command_in_group_bumps_message_count():
    """Successful /joke in a group must count toward shared TA state. The
    bump happens on the success path inside _handle_joke (after the reply
    is sent), NOT in the generic _bookkeep, so failed or invalid attempts
    don't inflate analytics."""
    stack = _router_patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.bump_message_count") as bmc, \
             patch("bot.ta.admin.joke.generate", return_value="ha ha"), \
             patch("bot.ta.admin.send_reply"):
            from bot.ta.admin import route
            route(_msg(username="student", text="/joke about python"))
            bmc.assert_called_once()
            args = bmc.call_args.args
            # signature: (group_key, user_id, username, first_name)
            assert args[1] == 42
            assert args[2] == "student"
            assert args[3] == "Alice"
    finally:
        _exit(stack)


def test_joke_command_in_dm_does_not_bump_message_count():
    """DMs are not part of group analytics, so /joke in a DM must not bump
    any group's message count."""
    stack = _router_patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.bump_message_count") as bmc, \
             patch("bot.ta.admin.joke.generate", return_value="ha"), \
             patch("bot.ta.admin.send_reply"):
            from bot.ta.admin import route
            route(_msg(chat_type="private", chat_id=42, username="student",
                       text="/joke about python"))
            bmc.assert_not_called()
    finally:
        _exit(stack)


def test_joke_command_without_theme_does_not_bump_message_count():
    """Invalid usage (no theme) must NOT count toward participation —
    only successfully handled /joke interactions credit the user."""
    stack = _router_patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.bump_message_count") as bmc, \
             patch("bot.ta.admin.joke.generate") as gen, \
             patch("bot.ta.admin.send_message"), \
             patch("bot.ta.admin.send_reply"):
            from bot.ta.admin import route
            route(_msg(username="student", text="/joke"))
            gen.assert_not_called()
            bmc.assert_not_called()
    finally:
        _exit(stack)


def test_joke_command_rate_limited_does_not_bump_message_count():
    """Rate-limited /joke attempts must NOT bump the shared message count —
    the user never got a successful interaction."""
    stack = _router_patches(rate_allowed=False)
    _enter(stack)
    try:
        with patch("bot.ta.admin.bump_message_count") as bmc, \
             patch("bot.ta.admin.joke.generate") as gen, \
             patch("bot.ta.admin.send_message"), \
             patch("bot.ta.admin.send_reply"):
            from bot.ta.admin import route
            route(_msg(username="student", text="/joke about python"))
            gen.assert_not_called()
            bmc.assert_not_called()
    finally:
        _exit(stack)


def test_joke_command_llm_failure_does_not_bump_message_count():
    """If the LLM fails to produce a joke, the user sees a friendly error
    but the message count must NOT be incremented."""
    stack = _router_patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.bump_message_count") as bmc, \
             patch("bot.ta.admin.joke.generate", return_value=None), \
             patch("bot.ta.admin.send_message"), \
             patch("bot.ta.admin.send_reply") as sr:
            from bot.ta.admin import route
            route(_msg(username="student", text="/joke about python"))
            sr.assert_not_called()
            bmc.assert_not_called()
    finally:
        _exit(stack)


def test_joke_command_llm_exception_does_not_bump_message_count():
    """If joke.generate() raises, the error is caught and a friendly
    message sent — but the message count must NOT be incremented."""
    stack = _router_patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.bump_message_count") as bmc, \
             patch("bot.ta.admin.joke.generate", side_effect=RuntimeError("boom")), \
             patch("bot.ta.admin.send_message"), \
             patch("bot.ta.admin.send_reply") as sr:
            from bot.ta.admin import route
            route(_msg(username="student", text="/joke about python"))
            sr.assert_not_called()
            bmc.assert_not_called()
    finally:
        _exit(stack)


def test_joke_command_handles_llm_failure_gracefully():
    stack = _router_patches()
    _enter(stack)
    try:
        with patch("bot.ta.admin.joke.generate", return_value=None) as gen, \
             patch("bot.ta.admin.send_message") as sm, \
             patch("bot.ta.admin.send_reply") as sr:
            from bot.ta.admin import route
            route(_msg(username="student", text="/joke about python"))
            gen.assert_called_once()
            sr.assert_not_called()
            # User sees a friendly error rather than silence.
            sm.assert_called_once()
            assert "joke" in sm.call_args.args[1].lower()
    finally:
        _exit(stack)


# ── /help listing ──────────────────────────────────────────────────────────
def test_help_mentions_joke_command():
    p = MagicMock()
    p.user_id = 42
    p.username = "alice"
    with patch("bot.ta.commands.send_message") as sm:
        from bot.ta.commands import _cmd_help
        _cmd_help(p)
        text = sm.call_args.args[1]
        assert "/joke" in text
