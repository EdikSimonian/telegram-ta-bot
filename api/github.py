"""GitHub webhook receiver.

Each configured repo POSTs ``push`` events here. We verify the
``X-Hub-Signature-256`` HMAC using ``GITHUB_WEBHOOK_SECRET`` (a shared
secret we put in the Vercel env and on every registered hook). A valid
push triggers a targeted re-ingest of the changed paths only — full-repo
sync is only on /git add and /git sync.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from flask import Flask, request

from bot.config import GITHUB_WEBHOOK_SECRET
from bot import github as gh
from bot.ta import git_ingest
from bot.ta.state import get_git_repo


app = Flask(__name__)


def _verify(sig_header: str, body: bytes) -> bool:
    if not GITHUB_WEBHOOK_SECRET:
        return False
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(sig_header, expected)


@app.route("/api/github", methods=["POST"])
def github_webhook():
    body = request.get_data() or b""
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not _verify(sig, body):
        return ("unauthorized", 401)

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return ("pong", 200)
    if event != "push":
        return ("ignored", 200)

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return ("bad json", 400)

    repo_full = (payload.get("repository") or {}).get("full_name") or ""
    if "/" not in repo_full:
        return ("no repo", 400)
    owner, repo = repo_full.split("/", 1)

    # Only act on repos we've explicitly indexed — random webhook spam
    # from leftover hooks should no-op.
    tracked = get_git_repo(owner, repo)
    if not tracked:
        return ("not tracked", 200)

    # Only sync on push to the tracked branch.
    tracked_branch = tracked.get("branch") or ""
    ref = (payload.get("ref") or "").replace("refs/heads/", "")
    if tracked_branch and ref and ref != tracked_branch:
        return ("branch ignored", 200)

    added_mod = gh.changed_paths_from_push(payload)
    removed   = gh.removed_paths_from_push(payload)

    n_added = 0
    n_removed = 0
    if added_mod:
        result = git_ingest.sync_repo(
            owner, repo, tracked_branch or None,
            added_by="github-webhook", paths=added_mod,
        )
        n_added = result.get("files_added", 0)
    if removed:
        n_removed = git_ingest.remove_synced_paths(owner, repo, removed)

    return (json.dumps({"added": n_added, "removed": n_removed}), 200,
            {"Content-Type": "application/json"})
