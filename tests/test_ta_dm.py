"""DM audit trail: state.py helpers + /dm admin command."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from tests.test_ta_grade_scenario import FakeRedis


def _prepared(*, command_args="", user_id=42, username="alice"):
    p = MagicMock()
    p.user_id = user_id
    p.username = username
    p.chat_id = user_id
    p.command = "dm"
    p.command_args = command_args
    p.group_key = "-100123"
    p.is_dm = True
    msg = MagicMock()
    msg.message_id = 1
    p.message = msg
    return p


# ── state.py: append_dm_log / get_dm_log / list_dm_users / clear_dm_log ───
def test_append_dm_log_stores_turns_and_upserts_meta():
    fake = FakeRedis()
    # Extend the grade-scenario fake with the set + list ops bot/ta/state
    # uses for DM logging. Kept inline so test_ta_grade_scenario stays minimal.
    fake.sets: dict[str, set] = {}
    fake.lists: dict[str, list] = {}

    def sadd(key, *members):
        s = fake.sets.setdefault(key, set())
        added = sum(1 for m in members if m not in s)
        s.update(members)
        return added
    def sismember(key, member):
        return int(member in fake.sets.get(key, set()))
    def srem(key, *members):
        s = fake.sets.get(key, set())
        removed = sum(1 for m in members if m in s)
        for m in members:
            s.discard(m)
        return removed
    def smembers(key):
        return set(fake.sets.get(key, set()))
    def rpush(key, *values):
        lst = fake.lists.setdefault(key, [])
        lst.extend(values)
        return len(lst)
    def _slice(lst, start, stop):
        n = len(lst)
        s = start if start >= 0 else max(0, n + start)
        e = (stop if stop >= 0 else n + stop) + 1
        return s, e
    def ltrim(key, start, stop):
        lst = fake.lists.setdefault(key, [])
        s, e = _slice(lst, start, stop)
        fake.lists[key] = lst[s:e]
    def lrange(key, start, stop):
        lst = fake.lists.get(key, [])
        s, e = _slice(lst, start, stop)
        return list(lst[s:e])
    # Extend delete so it also wipes list + set buckets for the same key.
    orig_delete = fake.delete
    def delete(*keys):
        for k in keys:
            fake.lists.pop(k, None)
            fake.sets.pop(k, None)
        return orig_delete(*keys) + len(keys)
    fake.sadd = sadd
    fake.sismember = sismember
    fake.srem = srem
    fake.smembers = smembers
    fake.rpush = rpush
    fake.ltrim = ltrim
    fake.lrange = lrange
    fake.delete = delete

    clock = {"now": 1_800_000_000}
    def _now():
        clock["now"] += 1
        return clock["now"]

    with patch("bot.ta.state.redis", fake), \
         patch("bot.ta.state.time.time", _now):
        from bot.ta.state import (
            append_dm_log,
            clear_dm_log,
            get_dm_log,
            get_dm_meta,
            list_dm_users,
        )

        append_dm_log(42, "user", "hi there", username="alice", first_name="Alice")
        append_dm_log(42, "assistant", "hello!", username="alice", first_name="Alice")
        append_dm_log(99, "user", "sup?", username="bob", first_name="Bob")
        append_dm_log(99, "assistant", "hey bob", username="bob", first_name="Bob")

        log42 = get_dm_log(42)
        assert len(log42) == 2
        assert log42[0]["role"] == "user"
        assert log42[0]["content"] == "hi there"
        assert log42[1]["role"] == "assistant"

        meta = get_dm_meta(42)
        assert meta["username"] == "alice"
        assert meta["firstName"] == "Alice"
        assert meta["turns"] == 2

        users = list_dm_users()
        # Both users appear, sorted by lastActive desc — Bob logged most recently.
        usernames = [u["username"] for u in users]
        assert set(usernames) == {"alice", "bob"}
        assert usernames[0] == "bob"

        # Clear Alice, Bob still present.
        assert clear_dm_log(42) is True
        assert get_dm_log(42) == []
        assert get_dm_meta(42) is None
        assert [u["username"] for u in list_dm_users()] == ["bob"]

        # Clear someone we've never logged.
        assert clear_dm_log(555) is False


# ── /dm (no args and list subcommand both list) ────────────────────────────
def test_dm_list_empty_state():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.list_dm_users", return_value=[]):
        from bot.ta.commands import _cmd_dm
        _cmd_dm(_prepared())
        assert "No DM" in sm.call_args.args[1]


def test_dm_list_renders_users_sorted_by_last_active():
    now = int(time.time())
    users = [
        {"userId": "42", "username": "alice", "firstName": "Alice",
         "turns": 6, "lastActive": now - 30},
        {"userId": "99", "username": "bob", "firstName": "Bob",
         "turns": 12, "lastActive": now - 3600},
    ]
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.list_dm_users", return_value=users):
        from bot.ta.commands import _cmd_dm
        _cmd_dm(_prepared(command_args="list"))
        text = sm.call_args.args[1]
        assert "Alice" in text and "Bob" in text
        assert "@alice" in text and "@bob" in text
        # Turn count + userId are present
        assert "6 turns" in text and "12 turns" in text
        # Alice is more recent → appears first.
        assert text.index("Alice") < text.index("Bob")


# ── /dm view ───────────────────────────────────────────────────────────────
def test_dm_view_renders_both_sides_and_escapes_html():
    turns = [
        {"role": "user", "content": "What's <script>?", "ts": 1_800_000_000},
        {"role": "assistant", "content": "It's an HTML tag.", "ts": 1_800_000_005},
    ]
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_user_chat", return_value="42"), \
         patch("bot.ta.commands.get_dm_log", return_value=turns), \
         patch("bot.ta.commands.get_dm_meta",
               return_value={"username": "alice", "firstName": "Alice", "turns": 2}):
        from bot.ta.commands import _cmd_dm
        _cmd_dm(_prepared(command_args="view @alice"))
        # At least one send call; header + body may be split.
        combined = "\n".join(c.args[1] for c in sm.call_args_list)
        assert "user" in combined and "bot" in combined
        # HTML was escaped — raw <script> must not leak through.
        assert "<script>" not in combined
        assert "&lt;script&gt;" in combined
        assert "Alice" in combined


def test_dm_view_accepts_numeric_user_id():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_user_chat") as guc, \
         patch("bot.ta.commands.get_dm_log", return_value=[
             {"role": "user", "content": "hi", "ts": 1_800_000_000}
         ]), \
         patch("bot.ta.commands.get_dm_meta", return_value={"turns": 1}):
        from bot.ta.commands import _cmd_dm
        _cmd_dm(_prepared(command_args="view 98765"))
        # Numeric id short-circuits the username lookup.
        guc.assert_not_called()
        assert sm.call_count >= 1


def test_dm_view_requires_arg():
    with patch("bot.ta.commands.send_message") as sm:
        from bot.ta.commands import _cmd_dm
        _cmd_dm(_prepared(command_args="view"))
        assert "Usage" in sm.call_args.args[1]


def test_dm_view_unknown_user():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_user_chat", return_value=None):
        from bot.ta.commands import _cmd_dm
        _cmd_dm(_prepared(command_args="view @ghost"))
        assert "No user found" in sm.call_args.args[1]


def test_dm_view_empty_transcript():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_user_chat", return_value="42"), \
         patch("bot.ta.commands.get_dm_log", return_value=[]):
        from bot.ta.commands import _cmd_dm
        _cmd_dm(_prepared(command_args="view @alice"))
        assert "No DM transcript" in sm.call_args.args[1]


# ── /dm clear ──────────────────────────────────────────────────────────────
def test_dm_clear_happy_path():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_user_chat", return_value="42"), \
         patch("bot.ta.commands.clear_dm_log", return_value=True) as clr:
        from bot.ta.commands import _cmd_dm
        _cmd_dm(_prepared(command_args="clear @alice"))
        clr.assert_called_once_with("42")
        assert "Cleared" in sm.call_args.args[1]


def test_dm_clear_unknown_user():
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.get_user_chat", return_value="42"), \
         patch("bot.ta.commands.clear_dm_log", return_value=False):
        from bot.ta.commands import _cmd_dm
        _cmd_dm(_prepared(command_args="clear @ghost"))
        assert "No DM transcript to clear" in sm.call_args.args[1]


# ── Unknown sub ────────────────────────────────────────────────────────────
def test_dm_unknown_sub_prints_usage():
    with patch("bot.ta.commands.send_message") as sm:
        from bot.ta.commands import _cmd_dm
        _cmd_dm(_prepared(command_args="bogus"))
        assert "Usage" in sm.call_args.args[1]


# ── ai.py wiring: DM turns get logged ─────────────────────────────────────
def test_ai_answer_logs_dm_turns():
    """Full-path smoke test that bot.ai.answer writes to the DM log when
    the incoming message is a direct message."""
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="reply"))]

    p = MagicMock()
    p.user_id = 42
    p.username = "alice"
    p.first_name = "Alice"
    p.is_dm = True
    p.group_key = "default"
    p.stripped_text = "What is Python?"
    p.is_instructor = False
    p.is_mention = False
    p.reply_to_username = None
    p.is_reply_to_bot = False

    with patch("bot.ai.rag.retrieve", return_value=[]), \
         patch("bot.ai.rag.format_context", return_value=None), \
         patch("bot.ai.get_history", return_value=[]), \
         patch("bot.ai.get_last_group_qa", return_value=None), \
         patch("bot.ai.get_active_model", return_value="gpt-5.4-nano"), \
         patch("bot.ai.append_history"), \
         patch("bot.ai.save_last_group_qa"), \
         patch("bot.ai.guardrail.clean", return_value="reply"), \
         patch("bot.ai.ai.chat.completions.create", return_value=fake_resp), \
         patch("bot.ai.append_dm_log") as adl:
        from bot.ai import answer
        reply = answer(p)
        assert reply == "reply"
        # Two calls: one for user turn, one for assistant.
        assert adl.call_count == 2
        roles = [c.args[1] for c in adl.call_args_list]
        assert roles == ["user", "assistant"]
        # User turn stores the raw text, not the prefixed payload.
        assert adl.call_args_list[0].args[2] == "What is Python?"
