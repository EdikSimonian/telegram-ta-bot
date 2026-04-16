"""Redis-backed state for the TA bot.

All keys live under the ``ta:`` prefix. Every function degrades safely when
Redis is unavailable (unconfigured or unreachable at runtime) — writes
become no-ops, reads return empty/default values. Callers never need to
null-check the client themselves.
"""
from __future__ import annotations

import json
import time
from typing import Any

from bot.clients import redis
from bot.config import (
    HISTORY_TTL,
    PERMANENT_ADMIN,
    REDIS_PREFIX,
    TA_RATE_LIMIT_WINDOW,
)

# ── Keys ──────────────────────────────────────────────────────────────────
# All keys are computed from REDIS_PREFIX so one Upstash DB can back many
# bots (prod + test) without collisions. Defaults to "ta:" for single-bot
# deployments; override via the REDIS_PREFIX env var (e.g. "ta:prod:").
_P = REDIS_PREFIX

K_ADMINS           = f"{_P}admins"
K_USER_CHATS       = f"{_P}userChats"
K_GROUPS           = f"{_P}groups"
K_ACTIVE_GROUP     = f"{_P}activeGroupId"
K_GROUP_WELCOMED   = f"{_P}groupWelcomed"
K_DM_WELCOMED      = f"{_P}dmWelcomed"
K_DM_USERS         = f"{_P}dm:users"
K_KNOWN_THREADS    = f"{_P}knownThreads"
K_DOCS             = f"{_P}docs"
K_GIT_REPOS        = f"{_P}gitrepos"
K_FEEDBACK          = f"{_P}feedback"

QUIZ_HISTORY_CAP = 20
FEEDBACK_CAP = 100
DM_FOLLOWUP_TTL = 86400  # 24 hours
DM_LOG_CAP = 200           # per-user DM audit log cap (turns, not pairs)


def _k_last_group_qa(user_id: int | str) -> str:
    return f"{_P}lastGroupQA:{user_id}"


def _k_rate(user_id: int | str) -> str:
    return f"{_P}rate:{user_id}"


def _k_rate_notified(user_id: int | str) -> str:
    return f"{_P}rate-notified:{user_id}"


def _k_history(group_key: str) -> str:
    return f"{_P}history:{group_key}"


def _k_stats(group_key: str) -> str:
    return f"{_P}group:{group_key}:stats"


def _k_scores(group_key: str) -> str:
    return f"{_P}group:{group_key}:scores"


def _k_total_quizzes(group_key: str) -> str:
    return f"{_P}group:{group_key}:totalQuizzes"


def _k_quiz_history(group_key: str) -> str:
    return f"{_P}group:{group_key}:quizHistory"


def _k_streak(group_key: str, user_id: int | str) -> str:
    return f"{_P}group:{group_key}:streak:{user_id}"


def _k_dm_log(user_id: int | str) -> str:
    return f"{_P}dm:log:{user_id}"


def _k_dm_meta(user_id: int | str) -> str:
    return f"{_P}dm:meta:{user_id}"


def _k_streak_users(group_key: str) -> str:
    return f"{_P}group:{group_key}:streakUsers"


def _k_active_quiz(chat_id: int | str) -> str:
    return f"{_P}activeQuiz:{chat_id}"


def _k_pending_announcement(admin_id: int | str) -> str:
    return f"{_P}pendingAnnouncement:{admin_id}"


def _k_active_model(group_key: str) -> str:
    return f"{_P}activeModel:{group_key}"


def _safe(op, default=None):
    """Run a Redis op; log and return ``default`` on failure."""
    if redis is None:
        return default
    try:
        return op()
    except Exception as e:
        print(f"[ta.state] Redis error: {e}")
        return default


# ── Admins ────────────────────────────────────────────────────────────────
def is_admin(username: str | None) -> bool:
    if not username:
        return False
    uname = username.lstrip("@").lower()
    if uname == PERMANENT_ADMIN:
        return True
    return bool(_safe(lambda: redis.sismember(K_ADMINS, uname), default=False))


def list_admins() -> list[str]:
    members = _safe(lambda: redis.smembers(K_ADMINS), default=set()) or set()
    admins = {m.lower() for m in members if m}
    admins.add(PERMANENT_ADMIN)
    return sorted(admins)


def add_admin(username: str) -> bool:
    uname = username.lstrip("@").lower()
    if not uname:
        return False
    if uname == PERMANENT_ADMIN:
        return True
    return bool(_safe(lambda: redis.sadd(K_ADMINS, uname), default=False))


def remove_admin(username: str) -> bool:
    """Remove an admin. Returns False when the target is the permanent admin."""
    uname = username.lstrip("@").lower()
    if not uname or uname == PERMANENT_ADMIN:
        return False
    _safe(lambda: redis.srem(K_ADMINS, uname), default=None)
    return True


# ── Username → userId map (populated as we observe users) ─────────────────
def remember_user_chat(username: str | None, user_id: int | str) -> None:
    if not username:
        return
    _safe(lambda: redis.hset(K_USER_CHATS, values={username.lstrip("@").lower(): str(user_id)}))


def get_user_chat(username: str) -> str | None:
    uname = username.lstrip("@").lower()
    return _safe(lambda: redis.hget(K_USER_CHATS, uname), default=None)


# ── Groups ────────────────────────────────────────────────────────────────
def register_group(chat_id: int | str, title: str) -> None:
    payload = json.dumps({"chatId": str(chat_id), "title": title})
    _safe(lambda: redis.hset(K_GROUPS, values={str(chat_id): payload}))
    # Set as active when there's no active group yet.
    if not get_active_group_id():
        set_active_group_id(chat_id)


def unregister_group(chat_id: int | str) -> None:
    _safe(lambda: redis.hdel(K_GROUPS, str(chat_id)))
    _safe(lambda: redis.hdel(K_GROUP_WELCOMED, str(chat_id)))
    active = get_active_group_id()
    if active == str(chat_id):
        remaining = list_groups()
        if remaining:
            set_active_group_id(remaining[0]["chatId"])
        else:
            _safe(lambda: redis.delete(K_ACTIVE_GROUP))


def list_groups() -> list[dict]:
    raw = _safe(lambda: redis.hgetall(K_GROUPS), default={}) or {}
    out: list[dict] = []
    for _, payload in raw.items() if isinstance(raw, dict) else []:
        try:
            out.append(json.loads(payload))
        except (TypeError, ValueError):
            continue
    return out


def get_active_group_id() -> str | None:
    return _safe(lambda: redis.get(K_ACTIVE_GROUP), default=None)


def set_active_group_id(chat_id: int | str) -> None:
    _safe(lambda: redis.set(K_ACTIVE_GROUP, str(chat_id)))


def mark_group_welcomed(chat_id: int | str, title: str) -> bool:
    """Record that we've sent the group welcome. Returns True on first write."""
    if redis is None:
        return True  # stateless: just send the welcome
    try:
        existing = redis.hget(K_GROUP_WELCOMED, str(chat_id))
        if existing:
            return False
        redis.hset(K_GROUP_WELCOMED, values={str(chat_id): title})
        return True
    except Exception as e:
        print(f"[ta.state] mark_group_welcomed error: {e}")
        return False


def mark_dm_welcomed(user_id: int | str) -> bool:
    """Record that we've DM'd a user. Returns True on first write."""
    if redis is None:
        return True
    try:
        added = redis.sadd(K_DM_WELCOMED, str(user_id))
        return bool(added)
    except Exception as e:
        print(f"[ta.state] mark_dm_welcomed error: {e}")
        return False


# ── Rate limiter (TA-specific, rolling window) ────────────────────────────
def ta_rate_check_and_inc(user_id: int | str, limit: int, window: int = TA_RATE_LIMIT_WINDOW) -> tuple[bool, int]:
    """Increment the user's rolling-window counter.

    Returns ``(allowed, remaining)``. If Redis is down we fail open.
    """
    if redis is None:
        return True, limit
    try:
        key = _k_rate(user_id)
        count = redis.incr(key)
        if count == 1:
            redis.expire(key, window)
        elif redis.ttl(key) == -1:
            redis.expire(key, window)
        if count > limit:
            return False, 0
        return True, max(0, limit - count)
    except Exception as e:
        print(f"[ta.state] rate_check error: {e}")
        return True, limit


def ta_rate_should_notify(user_id: int | str, window: int = TA_RATE_LIMIT_WINDOW) -> bool:
    """True the first time in a window — used to notify once then stay silent."""
    if redis is None:
        return True
    try:
        key = _k_rate_notified(user_id)
        added = redis.set(key, "1", nx=True, ex=window)
        return bool(added)
    except Exception as e:
        print(f"[ta.state] rate_notified error: {e}")
        return True


# ── History ───────────────────────────────────────────────────────────────
def get_history(group_key: str, limit: int = 20) -> list[dict]:
    raw = _safe(lambda: redis.lrange(_k_history(group_key), -limit, -1), default=[]) or []
    out: list[dict] = []
    for item in raw:
        try:
            out.append(json.loads(item))
        except (TypeError, ValueError):
            continue
    return out


def append_history(group_key: str, role: str, content: str, limit: int = 20) -> None:
    payload = json.dumps({"role": role, "content": content, "ts": int(time.time())})
    if redis is None:
        return
    try:
        key = _k_history(group_key)
        redis.rpush(key, payload)
        redis.ltrim(key, -limit, -1)
        redis.expire(key, HISTORY_TTL)
    except Exception as e:
        print(f"[ta.state] append_history error: {e}")


def clear_history(group_key: str) -> None:
    _safe(lambda: redis.delete(_k_history(group_key)))


# ── DM audit log ──────────────────────────────────────────────────────────
# Per-user log of every turn that happens in a direct message with the bot.
# This is intentionally separate from ``history``: the main history bucket
# is keyed by the active group_key (so DMs share it with whichever group is
# active), which is fine for LLM context but useless for instructor audit.
def append_dm_log(
    user_id: int | str,
    role: str,
    content: str,
    *,
    username: str | None = None,
    first_name: str | None = None,
) -> None:
    if redis is None:
        return
    try:
        payload = json.dumps({
            "role":    role,
            "content": content,
            "ts":      int(time.time()),
        })
        log_key  = _k_dm_log(user_id)
        meta_key = _k_dm_meta(user_id)
        redis.rpush(log_key, payload)
        redis.ltrim(log_key, -DM_LOG_CAP, -1)
        # Meta: upsert username/firstName/lastActive/totalTurns.
        raw = redis.hget(meta_key, "data")
        base = {}
        if raw:
            try:
                base = json.loads(raw)
            except (TypeError, ValueError):
                base = {}
        base["userId"]     = str(user_id)
        base["username"]   = username or base.get("username")
        base["firstName"]  = first_name or base.get("firstName")
        base["lastActive"] = int(time.time())
        base["turns"]      = int(base.get("turns", 0)) + 1
        redis.hset(meta_key, values={"data": json.dumps(base)})
        redis.sadd(K_DM_USERS, str(user_id))
    except Exception as e:
        print(f"[ta.state] append_dm_log error: {e}")


def get_dm_log(user_id: int | str, limit: int = DM_LOG_CAP) -> list[dict]:
    raw = _safe(
        lambda: redis.lrange(_k_dm_log(user_id), -limit, -1),
        default=[],
    ) or []
    out: list[dict] = []
    for item in raw:
        try:
            out.append(json.loads(item))
        except (TypeError, ValueError):
            continue
    return out


def get_dm_meta(user_id: int | str) -> dict | None:
    raw = _safe(lambda: redis.hget(_k_dm_meta(user_id), "data"), default=None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def list_dm_users() -> list[dict]:
    """Return all users with a DM log, hydrated with meta. Sorted by
    ``lastActive`` desc so the most recent conversations surface first."""
    members = _safe(lambda: redis.smembers(K_DM_USERS), default=set()) or set()
    out: list[dict] = []
    for uid in members:
        meta = get_dm_meta(uid) or {"userId": uid}
        out.append(meta)
    out.sort(key=lambda m: int(m.get("lastActive", 0)), reverse=True)
    return out


def clear_dm_log(user_id: int | str) -> bool:
    """Wipe a single user's DM log + meta. Returns True when the user existed."""
    if redis is None:
        return False
    try:
        uid = str(user_id)
        existed = bool(redis.sismember(K_DM_USERS, uid))
        redis.delete(_k_dm_log(uid))
        redis.delete(_k_dm_meta(uid))
        redis.srem(K_DM_USERS, uid)
        return existed
    except Exception as e:
        print(f"[ta.state] clear_dm_log error: {e}")
        return False


# ── Stats + scores ────────────────────────────────────────────────────────
def bump_message_count(group_key: str, user_id: int | str, username: str | None, first_name: str | None) -> None:
    if redis is None:
        return
    try:
        key = _k_stats(group_key)
        existing_raw = redis.hget(key, str(user_id))
        base = {}
        if existing_raw:
            try:
                base = json.loads(existing_raw)
            except (TypeError, ValueError):
                base = {}
        base["username"]     = username or base.get("username")
        base["firstName"]    = first_name or base.get("firstName")
        base["messageCount"] = int(base.get("messageCount", 0)) + 1
        base["lastActive"]   = int(time.time())
        redis.hset(key, values={str(user_id): json.dumps(base)})
    except Exception as e:
        print(f"[ta.state] bump_message_count error: {e}")


def get_group_stats(group_key: str) -> dict[str, dict]:
    raw = _safe(lambda: redis.hgetall(_k_stats(group_key)), default={}) or {}
    out: dict[str, dict] = {}
    for uid, payload in (raw.items() if isinstance(raw, dict) else []):
        try:
            out[uid] = json.loads(payload)
        except (TypeError, ValueError):
            continue
    return out


def record_quiz_score(group_key: str, user_id: int | str, username: str | None,
                      first_name: str | None, correct: bool) -> None:
    if redis is None:
        return
    try:
        key = _k_scores(group_key)
        raw = redis.hget(key, str(user_id))
        base = {}
        if raw:
            try:
                base = json.loads(raw)
            except (TypeError, ValueError):
                base = {}
        base["username"]  = username or base.get("username")
        base["firstName"] = first_name or base.get("firstName")
        base["correct"]   = int(base.get("correct", 0)) + (1 if correct else 0)
        base["total"]     = int(base.get("total", 0)) + 1
        redis.hset(key, values={str(user_id): json.dumps(base)})
    except Exception as e:
        print(f"[ta.state] record_quiz_score error: {e}")


def get_quiz_scores(group_key: str) -> dict[str, dict]:
    raw = _safe(lambda: redis.hgetall(_k_scores(group_key)), default={}) or {}
    out: dict[str, dict] = {}
    for uid, payload in (raw.items() if isinstance(raw, dict) else []):
        try:
            out[uid] = json.loads(payload)
        except (TypeError, ValueError):
            continue
    return out


def bump_total_quizzes(group_key: str) -> int:
    return int(_safe(lambda: redis.incr(_k_total_quizzes(group_key)), default=0) or 0)


def get_total_quizzes(group_key: str) -> int:
    val = _safe(lambda: redis.get(_k_total_quizzes(group_key)), default=0)
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


# ── Streaks ──────────────────────────────────────────────────────────────
def get_streak(group_key: str, user_id: int | str) -> int:
    """Return the current consecutive-correct streak for a student."""
    val = _safe(lambda: redis.get(_k_streak(group_key, user_id)), default=0)
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def update_streak(group_key: str, user_id: int | str, correct: bool) -> int:
    """Increment streak on correct, reset to 0 on wrong. Returns new value.

    Also tracks the user id in a set so ``reset_group_stats`` can clean up.
    """
    if redis is None:
        return 0
    try:
        streak_key = _k_streak(group_key, user_id)
        if correct:
            new_val = redis.incr(streak_key)
        else:
            redis.set(streak_key, "0")
            new_val = 0
        redis.sadd(_k_streak_users(group_key), str(user_id))
        return int(new_val)
    except Exception as e:
        print(f"[ta.state] update_streak error: {e}")
        return 0


def reset_group_stats(group_key: str) -> None:
    """Wipe stats/scores/history/totalQuizzes/quizHistory/streaks for a group."""
    if redis is None:
        return
    try:
        redis.delete(_k_stats(group_key))
        redis.delete(_k_scores(group_key))
        redis.delete(_k_total_quizzes(group_key))
        redis.delete(_k_quiz_history(group_key))
        redis.delete(_k_history(group_key))
        # Clear streak keys for all tracked users.
        streak_users_key = _k_streak_users(group_key)
        members = redis.smembers(streak_users_key) or set()
        for uid in members:
            redis.delete(_k_streak(group_key, uid))
        redis.delete(streak_users_key)
    except Exception as e:
        print(f"[ta.state] reset_group_stats error: {e}")


# ── Quiz history (for de-duplication in generation) ───────────────────────
def get_quiz_history(group_key: str) -> list[str]:
    raw = _safe(lambda: redis.lrange(_k_quiz_history(group_key), 0, -1), default=[]) or []
    return list(raw) if raw else []


def push_quiz_history(group_key: str, question_line: str) -> None:
    if redis is None:
        return
    try:
        key = _k_quiz_history(group_key)
        redis.rpush(key, question_line)
        redis.ltrim(key, -QUIZ_HISTORY_CAP, -1)
    except Exception as e:
        print(f"[ta.state] push_quiz_history error: {e}")


# ── Active quiz per chat ──────────────────────────────────────────────────
def set_active_quiz(chat_id: int | str, data: dict) -> None:
    _safe(lambda: redis.set(_k_active_quiz(chat_id), json.dumps(data)))


def get_active_quiz(chat_id: int | str) -> dict | None:
    raw = _safe(lambda: redis.get(_k_active_quiz(chat_id)), default=None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def clear_active_quiz(chat_id: int | str) -> None:
    _safe(lambda: redis.delete(_k_active_quiz(chat_id)))


def list_active_quizzes() -> list[dict]:
    """Scan would be ideal but Upstash REST does not expose SCAN in the
    python client uniformly. Callers use the cron path only to reveal
    quizzes they already know about via groups."""
    quizzes: list[dict] = []
    for g in list_groups():
        q = get_active_quiz(g["chatId"])
        if q:
            q.setdefault("chatId", g["chatId"])
            quizzes.append(q)
    return quizzes


# ── Active model per group ────────────────────────────────────────────────
def get_active_model(group_key: str) -> str | None:
    """Return the override model for this group, or None for the default."""
    return _safe(lambda: redis.get(_k_active_model(group_key)), default=None)


def set_active_model(group_key: str, model: str) -> None:
    _safe(lambda: redis.set(_k_active_model(group_key), model))


def clear_active_model(group_key: str) -> None:
    _safe(lambda: redis.delete(_k_active_model(group_key)))


# ── Announcements (pending two-step flow) ─────────────────────────────────
PENDING_ANNOUNCEMENT_TTL = 3600


def set_pending_announcement(admin_id: int | str, text: str, group_chat_id: int | str) -> None:
    payload = json.dumps({"text": text, "groupChatId": str(group_chat_id)})
    if redis is None:
        return
    try:
        redis.set(_k_pending_announcement(admin_id), payload, ex=PENDING_ANNOUNCEMENT_TTL)
    except Exception as e:
        print(f"[ta.state] set_pending_announcement error: {e}")


def get_pending_announcement(admin_id: int | str) -> dict | None:
    raw = _safe(lambda: redis.get(_k_pending_announcement(admin_id)), default=None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def clear_pending_announcement(admin_id: int | str) -> None:
    _safe(lambda: redis.delete(_k_pending_announcement(admin_id)))


# ── Docs index ────────────────────────────────────────────────────────────
def list_docs() -> list[dict]:
    raw = _safe(lambda: redis.lrange(K_DOCS, 0, -1), default=[]) or []
    out: list[dict] = []
    for item in raw:
        try:
            out.append(json.loads(item))
        except (TypeError, ValueError):
            continue
    return out


def add_doc(meta: dict) -> None:
    _safe(lambda: redis.rpush(K_DOCS, json.dumps(meta)))


def remove_doc(slug: str) -> None:
    """Remove doc entries by slug. Uses list-read-rewrite since lrem on
    JSON payloads is brittle."""
    if redis is None:
        return
    try:
        current = list_docs()
        kept = [d for d in current if d.get("slug") != slug]
        redis.delete(K_DOCS)
        for d in kept:
            redis.rpush(K_DOCS, json.dumps(d))
    except Exception as e:
        print(f"[ta.state] remove_doc error: {e}")


# ── Last group Q&A per student (for DM follow-up) ─────────────────────────
def save_last_group_qa(user_id: int | str, question: str, answer: str, group_key: str) -> None:
    """Snapshot the student's last group Q&A so DM follow-ups have context."""
    if redis is None:
        return
    try:
        payload = json.dumps({
            "question": question,
            "answer": answer,
            "groupKey": group_key,
            "ts": int(time.time()),
        })
        redis.set(_k_last_group_qa(user_id), payload, ex=DM_FOLLOWUP_TTL)
    except Exception as e:
        print(f"[ta.state] save_last_group_qa error: {e}")


def get_last_group_qa(user_id: int | str) -> dict | None:
    """Return the student's last group Q&A if it exists and hasn't expired."""
    raw = _safe(lambda: redis.get(_k_last_group_qa(user_id)), default=None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


# ── Git repos (for RAG auto-sync) ─────────────────────────────────────────
def list_git_repos() -> list[dict]:
    raw = _safe(lambda: redis.lrange(K_GIT_REPOS, 0, -1), default=[]) or []
    out: list[dict] = []
    for item in raw:
        try:
            out.append(json.loads(item))
        except (TypeError, ValueError):
            continue
    return out


def get_git_repo(owner: str, repo: str) -> dict | None:
    for r in list_git_repos():
        if r.get("owner", "").lower() == owner.lower() and r.get("repo", "").lower() == repo.lower():
            return r
    return None


def add_git_repo(meta: dict) -> None:
    """Idempotent insert keyed on owner+repo."""
    if redis is None:
        return
    try:
        existing = list_git_repos()
        owner, repo = meta.get("owner", ""), meta.get("repo", "")
        kept = [
            r for r in existing
            if not (r.get("owner", "").lower() == owner.lower()
                    and r.get("repo", "").lower() == repo.lower())
        ]
        kept.append(meta)
        redis.delete(K_GIT_REPOS)
        for r in kept:
            redis.rpush(K_GIT_REPOS, json.dumps(r))
    except Exception as e:
        print(f"[ta.state] add_git_repo error: {e}")


def remove_git_repo(owner: str, repo: str) -> dict | None:
    """Remove by owner+repo; returns the removed entry or None."""
    if redis is None:
        return None
    try:
        existing = list_git_repos()
        removed = None
        kept = []
        for r in existing:
            if (r.get("owner", "").lower() == owner.lower()
                    and r.get("repo", "").lower() == repo.lower()):
                removed = r
            else:
                kept.append(r)
        redis.delete(K_GIT_REPOS)
        for r in kept:
            redis.rpush(K_GIT_REPOS, json.dumps(r))
        return removed
    except Exception as e:
        print(f"[ta.state] remove_git_repo error: {e}")
        return None


# ── Group key resolution ──────────────────────────────────────────────────
def resolve_group_key(chat_type: str, chat_id: int | str) -> str:
    """Return the Redis bucket key for a message.

    - In a group: use that chat id.
    - In a DM: use the instructor's currently active group, or "default".
    """
    if chat_type in ("group", "supergroup", "channel"):
        return str(chat_id)
    return get_active_group_id() or "default"


def thread_slug(chat_type: str, chat_id: int | str, user_id: int | str | None = None) -> str:
    """Human-friendly slug used for history keys and backups."""
    if chat_type in ("group", "supergroup", "channel"):
        return f"tg-group-{str(chat_id).lstrip('-')}"
    return f"tg-dm-{user_id if user_id is not None else chat_id}"


# ── Feedback ─────────────────────────────────────────────────────────────
def add_feedback(text: str, username: str | None = None) -> None:
    """Append anonymous feedback. Capped at FEEDBACK_CAP entries."""
    if redis is None:
        return
    try:
        payload = json.dumps({
            "text": text,
            "username": username,
            "ts": int(time.time()),
        })
        redis.rpush(K_FEEDBACK, payload)
        redis.ltrim(K_FEEDBACK, -FEEDBACK_CAP, -1)
    except Exception as e:
        print(f"[ta.state] add_feedback error: {e}")


def list_feedback() -> list[dict]:
    """Return all stored feedback entries."""
    raw = _safe(lambda: redis.lrange(K_FEEDBACK, 0, -1), default=[]) or []
    out: list[dict] = []
    for item in raw:
        try:
            out.append(json.loads(item))
        except (TypeError, ValueError):
            continue
    return out


def clear_feedback() -> None:
    """Delete all feedback."""
    _safe(lambda: redis.delete(K_FEEDBACK))
