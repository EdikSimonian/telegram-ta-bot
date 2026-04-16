"""One-shot deploy notification with changelog.

When a new build goes live on Vercel, the first request calls
``notify_once()`` which DMs the permanent admin with the short SHA
and a list of commit subjects since the previous deploy. Uses the
GitHub compare API to compute the diff — no local git needed.
"""
from __future__ import annotations

import os

from bot.clients import bot, redis
from bot.config import BOT_ENV, GITHUB_TOKEN, PERMANENT_ADMIN, REDIS_PREFIX
from bot.ta.state import get_user_chat


_DONE_THIS_PROCESS = False
_LAST_SHA_KEY = f"{REDIS_PREFIX}lastDeploySHA"


def _key(sha: str) -> str:
    return f"{REDIS_PREFIX}deployed:{sha}"


def _changelog(prev_sha: str, new_sha: str) -> list[str]:
    """Fetch commit subjects between two SHAs via GitHub compare API."""
    owner = os.environ.get("VERCEL_GIT_REPO_OWNER", "").strip()
    slug = os.environ.get("VERCEL_GIT_REPO_SLUG", "").strip()
    if not owner or not slug or not prev_sha:
        return []
    try:
        import requests
        headers = {"Accept": "application/vnd.github+json"}
        if GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        resp = requests.get(
            f"https://api.github.com/repos/{owner}/{slug}/compare/{prev_sha[:7]}...{new_sha[:7]}",
            headers=headers, timeout=5,
        )
        if resp.status_code >= 400:
            return []
        commits = resp.json().get("commits") or []
        return [
            c.get("commit", {}).get("message", "").split("\n")[0]
            for c in commits if c.get("commit", {}).get("message")
        ]
    except Exception as e:
        print(f"[deploy_notice] changelog error: {e}")
        return []


def notify_once() -> None:
    """Idempotent: safe to call on every request."""
    global _DONE_THIS_PROCESS
    if _DONE_THIS_PROCESS:
        return

    sha = os.environ.get("VERCEL_GIT_COMMIT_SHA", "").strip()
    if not sha:
        _DONE_THIS_PROCESS = True
        return
    short = sha[:7]

    if redis is not None:
        try:
            claimed = redis.set(_key(sha), "1", nx=True, ex=86400)
            if not claimed:
                _DONE_THIS_PROCESS = True
                return
        except Exception as e:
            print(f"[deploy_notice] redis claim error: {e}")
            _DONE_THIS_PROCESS = True
            return

    admin_chat = get_user_chat(PERMANENT_ADMIN)
    if not admin_chat:
        _DONE_THIS_PROCESS = True
        return

    # Build the changelog from the previous deploy's SHA.
    prev_sha = None
    if redis is not None:
        try:
            prev_sha = redis.get(_LAST_SHA_KEY)
        except Exception:
            pass

    changes = _changelog(prev_sha or "", sha) if prev_sha else []

    # Update the stored SHA for next time.
    if redis is not None:
        try:
            redis.set(_LAST_SHA_KEY, sha)
        except Exception:
            pass

    lines = [f"🚀 {BOT_ENV} deploy live — {short}"]
    if changes:
        for subj in changes[-10:]:
            lines.append(f"• {subj}")
    else:
        msg = os.environ.get("VERCEL_GIT_COMMIT_MESSAGE", "").strip()
        if msg:
            lines.append(f"• {msg.split(chr(10))[0]}")

    try:
        bot.send_message(admin_chat, "\n".join(lines))
    except Exception as e:
        print(f"[deploy_notice] DM error: {e}")
    _DONE_THIS_PROCESS = True
