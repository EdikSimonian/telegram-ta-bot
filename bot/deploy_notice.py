"""One-shot deploy notification.

When a new build goes live on Vercel, Vercel injects VERCEL_GIT_COMMIT_SHA.
The first webhook/autoreveal request to hit the new function instance
calls ``notify_once()``; we check Redis for a per-SHA marker and DM the
permanent admin if it's missing. Subsequent requests (on this SHA, and
across cold starts) early-return because the key is now set.
"""
from __future__ import annotations

import os

from bot.clients import bot, redis
from bot.config import BOT_ENV, PERMANENT_ADMIN, REDIS_PREFIX
from bot.ta.state import get_user_chat


_DONE_THIS_PROCESS = False


def _key(sha: str) -> str:
    return f"{REDIS_PREFIX}deployed:{sha}"


def notify_once() -> None:
    """Idempotent: safe to call on every request."""
    global _DONE_THIS_PROCESS
    if _DONE_THIS_PROCESS:
        return

    sha = os.environ.get("VERCEL_GIT_COMMIT_SHA", "").strip()
    if not sha:
        _DONE_THIS_PROCESS = True  # no Vercel build info — nothing to do
        return
    short = sha[:7]

    # Redis-level dedup so the notice only fires once per SHA, even across
    # cold starts or multiple function instances.
    if redis is not None:
        try:
            claimed = redis.set(_key(sha), "1", nx=True, ex=86400)
            if not claimed:
                _DONE_THIS_PROCESS = True
                return
        except Exception as e:
            print(f"[deploy_notice] redis claim error: {e}")
            # Fail closed (don't spam): mark done locally and skip
            _DONE_THIS_PROCESS = True
            return

    # Look up the permanent admin's Telegram chat id. They must have DM'd
    # the bot at least once — remember_user_chat populates ta:userChats.
    admin_chat = get_user_chat(PERMANENT_ADMIN)
    if not admin_chat:
        _DONE_THIS_PROCESS = True
        return

    try:
        bot.send_message(admin_chat, f"🚀 {BOT_ENV} deploy live — {short}")
    except Exception as e:
        print(f"[deploy_notice] DM error: {e}")
    _DONE_THIS_PROCESS = True
