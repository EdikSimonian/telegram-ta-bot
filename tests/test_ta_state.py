import json
from unittest.mock import patch, MagicMock


def _fresh_redis():
    """Fresh MagicMock Redis whose methods don't raise."""
    r = MagicMock()
    r.sismember.return_value = False
    r.smembers.return_value = set()
    r.sadd.return_value = 1
    r.srem.return_value = 1
    r.hset.return_value = 1
    r.hget.return_value = None
    r.hdel.return_value = 1
    r.hgetall.return_value = {}
    r.get.return_value = None
    r.set.return_value = True
    r.delete.return_value = 1
    r.rpush.return_value = 1
    r.lpush.return_value = 1
    r.lrange.return_value = []
    r.ltrim.return_value = True
    r.expire.return_value = True
    r.incr.return_value = 1
    return r


# ── Admins ────────────────────────────────────────────────────────────────
def test_permanent_admin_always_recognized():
    with patch("bot.ta.state.redis", _fresh_redis()):
        from bot.ta.state import is_admin
        assert is_admin("ediksimonian") is True
        assert is_admin("@EdikSimonian") is True
        assert is_admin("EDIKSIMONIAN") is True


def test_non_admin_rejected():
    r = _fresh_redis()
    r.sismember.return_value = False
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import is_admin
        assert is_admin("randomuser") is False


def test_add_admin_stores_lowercase():
    r = _fresh_redis()
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import add_admin
        add_admin("@AliceTA")
        # Verify lowercase, leading @ stripped
        args, _ = r.sadd.call_args
        assert args[1] == "aliceta"


def test_cannot_remove_permanent_admin():
    r = _fresh_redis()
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import remove_admin
        assert remove_admin("ediksimonian") is False
        r.srem.assert_not_called()


def test_list_admins_includes_permanent():
    r = _fresh_redis()
    r.smembers.return_value = {"alice", "bob"}
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import list_admins
        out = list_admins()
        assert "ediksimonian" in out
        assert "alice" in out
        assert "bob" in out


def test_is_admin_redis_down_falls_back_to_permanent_only():
    with patch("bot.ta.state.redis", None):
        from bot.ta.state import is_admin
        assert is_admin("ediksimonian") is True
        assert is_admin("alice") is False


# ── Groups ────────────────────────────────────────────────────────────────
def test_register_group_sets_active_when_none():
    r = _fresh_redis()
    r.get.return_value = None  # no active group
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import register_group
        register_group(-100123, "Workshop 2026")
        # Group written
        assert any(c.args[0] == "ta:groups" for c in r.hset.call_args_list)
        # Active id set
        r.set.assert_any_call("ta:activeGroupId", "-100123")


def test_unregister_group_rolls_active_to_next():
    r = _fresh_redis()
    # active was the one we're removing; list_groups returns one remaining
    r.get.return_value = "-100123"
    r.hgetall.return_value = {"-100999": json.dumps({"chatId": "-100999", "title": "Other"})}
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import unregister_group
        unregister_group("-100123")
        r.set.assert_any_call("ta:activeGroupId", "-100999")


# ── Welcomed flags (idempotent) ───────────────────────────────────────────
def test_mark_group_welcomed_first_time_true_then_false():
    r = _fresh_redis()
    r.hget.side_effect = [None, "Workshop 2026"]  # first: none, second: already set
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import mark_group_welcomed
        assert mark_group_welcomed(-100123, "Workshop 2026") is True
        assert mark_group_welcomed(-100123, "Workshop 2026") is False


def test_mark_dm_welcomed_first_time_true_then_false():
    r = _fresh_redis()
    r.sadd.side_effect = [1, 0]
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import mark_dm_welcomed
        assert mark_dm_welcomed(42) is True
        assert mark_dm_welcomed(42) is False


# ── Rate limiter ──────────────────────────────────────────────────────────
def test_rate_check_allows_under_limit():
    r = _fresh_redis()
    r.incr.return_value = 3
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import ta_rate_check_and_inc
        allowed, remaining = ta_rate_check_and_inc(42, limit=10, window=3600)
        assert allowed is True
        assert remaining == 7


def test_rate_check_sets_ttl_on_first_hit():
    r = _fresh_redis()
    r.incr.return_value = 1
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import ta_rate_check_and_inc
        ta_rate_check_and_inc(42, limit=10, window=3600)
        r.expire.assert_called_with("ta:rate:42", 3600)


def test_rate_check_blocks_over_limit():
    r = _fresh_redis()
    r.incr.return_value = 11
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import ta_rate_check_and_inc
        allowed, remaining = ta_rate_check_and_inc(42, limit=10)
        assert allowed is False
        assert remaining == 0


def test_rate_check_fails_open_when_redis_down():
    with patch("bot.ta.state.redis", None):
        from bot.ta.state import ta_rate_check_and_inc
        allowed, remaining = ta_rate_check_and_inc(42, limit=10)
        assert allowed is True
        assert remaining == 10


def test_rate_should_notify_true_first_only():
    r = _fresh_redis()
    r.set.side_effect = [True, False]
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import ta_rate_should_notify
        assert ta_rate_should_notify(42) is True
        assert ta_rate_should_notify(42) is False


# ── History ───────────────────────────────────────────────────────────────
def test_append_history_trims_and_sets_ttl():
    r = _fresh_redis()
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import append_history
        append_history("g1", "user", "hello", limit=5)
        r.rpush.assert_called()
        r.ltrim.assert_called_with("ta:history:g1", -5, -1)
        r.expire.assert_called()


def test_get_history_parses_json_items():
    r = _fresh_redis()
    r.lrange.return_value = [
        json.dumps({"role": "user", "content": "hi"}),
        json.dumps({"role": "assistant", "content": "hello"}),
    ]
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import get_history
        out = get_history("g1")
        assert len(out) == 2
        assert out[0]["role"] == "user"


def test_get_history_skips_bad_json():
    r = _fresh_redis()
    r.lrange.return_value = ["not-json", json.dumps({"role": "user", "content": "ok"})]
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import get_history
        out = get_history("g1")
        assert out == [{"role": "user", "content": "ok"}]


# ── Stats + scores ────────────────────────────────────────────────────────
def test_bump_message_count_increments_existing():
    r = _fresh_redis()
    r.hget.return_value = json.dumps({
        "username": "alice", "firstName": "Alice", "messageCount": 3, "lastActive": 0,
    })
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import bump_message_count
        bump_message_count("g1", 42, "alice", "Alice")
        # Capture the written JSON
        _, kwargs = r.hset.call_args
        written = json.loads(kwargs["values"]["42"])
        assert written["messageCount"] == 4


def test_record_quiz_score_correct_increments_both():
    r = _fresh_redis()
    r.hget.return_value = json.dumps({"correct": 2, "total": 3})
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import record_quiz_score
        record_quiz_score("g1", 42, "alice", "Alice", correct=True)
        _, kwargs = r.hset.call_args
        written = json.loads(kwargs["values"]["42"])
        assert written["correct"] == 3
        assert written["total"] == 4


def test_record_quiz_score_wrong_increments_only_total():
    r = _fresh_redis()
    r.hget.return_value = None
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import record_quiz_score
        record_quiz_score("g1", 42, "bob", "Bob", correct=False)
        _, kwargs = r.hset.call_args
        written = json.loads(kwargs["values"]["42"])
        assert written["correct"] == 0
        assert written["total"] == 1


def test_reset_group_stats_clears_five_keys():
    r = _fresh_redis()
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import reset_group_stats
        reset_group_stats("g1")
        deleted = {c.args[0] for c in r.delete.call_args_list}
        assert "ta:group:g1:stats" in deleted
        assert "ta:group:g1:scores" in deleted
        assert "ta:group:g1:totalQuizzes" in deleted
        assert "ta:group:g1:quizHistory" in deleted
        assert "ta:history:g1" in deleted


# ── Quiz history ──────────────────────────────────────────────────────────
def test_push_quiz_history_trims_to_cap():
    r = _fresh_redis()
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import push_quiz_history
        push_quiz_history("g1", "What is Python?")
        r.ltrim.assert_called_with("ta:group:g1:quizHistory", -20, -1)


# ── Active quiz ───────────────────────────────────────────────────────────
def test_set_and_get_active_quiz_roundtrip():
    r = _fresh_redis()
    stored = {}

    def _set(key, value, **kw):
        stored[key] = value
        return True

    def _get(key):
        return stored.get(key)

    r.set.side_effect = _set
    r.get.side_effect = _get
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import set_active_quiz, get_active_quiz
        payload = {
            "questionMessageId": 7,
            "correctAnswer": "B",
            "topic": "python basics",
            "answers": {},
            "startTime": 1700000000,
        }
        set_active_quiz("-100123", payload)
        assert get_active_quiz("-100123") == payload


# ── Announcements ─────────────────────────────────────────────────────────
def test_pending_announcement_set_with_ttl():
    r = _fresh_redis()
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import set_pending_announcement
        set_pending_announcement(42, "Class cancelled", "-100123")
        args, kwargs = r.set.call_args
        assert kwargs.get("ex") == 3600


# ── Group key + thread slug ───────────────────────────────────────────────
def test_resolve_group_key_uses_chat_id_in_group():
    with patch("bot.ta.state.redis", None):
        from bot.ta.state import resolve_group_key
        assert resolve_group_key("supergroup", -100123) == "-100123"
        assert resolve_group_key("group", -200) == "-200"


def test_resolve_group_key_defaults_in_dm_with_no_active():
    with patch("bot.ta.state.redis", None):
        from bot.ta.state import resolve_group_key
        assert resolve_group_key("private", 42) == "default"


def test_resolve_group_key_uses_active_group_in_dm():
    r = _fresh_redis()
    r.get.return_value = "-100123"
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import resolve_group_key
        assert resolve_group_key("private", 42) == "-100123"


def test_thread_slug_format():
    from bot.ta.state import thread_slug
    assert thread_slug("private", 42, 42) == "tg-dm-42"
    assert thread_slug("supergroup", -100123, 42) == "tg-group-100123"


# ── Docs ──────────────────────────────────────────────────────────────────
def test_remove_doc_rewrites_list_without_slug():
    r = _fresh_redis()
    r.lrange.return_value = [
        json.dumps({"slug": "cs101", "title": "CS101"}),
        json.dumps({"slug": "cs102", "title": "CS102"}),
    ]
    with patch("bot.ta.state.redis", r):
        from bot.ta.state import remove_doc
        remove_doc("cs101")
        r.delete.assert_any_call("ta:docs")
        # Only cs102 gets rpushed back
        pushed = [c.args[1] for c in r.rpush.call_args_list]
        assert len(pushed) == 1
        assert json.loads(pushed[0])["slug"] == "cs102"
