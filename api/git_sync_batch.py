"""QStash callback that processes a batch of files for one repo.

Per-repo queue: each /git sync (or /git add) publishes ONE message with
the entire path list. This handler ingests up to BATCH_SIZE files
inline (~40s under the 60s cap), then either publishes a follow-up
message with the remainder or DMs the originating admin that the repo
is complete.

Idempotent: ``ingest_one_file`` deletes stale chunks before upserting,
so QStash retries replay cleanly.
"""
from __future__ import annotations

from flask import Flask, request

from bot import qstash
from bot.config import PUBLIC_URL
from bot.ta.git_ingest import process_batch


app = Flask(__name__)


@app.route("/api/git-sync-batch", methods=["POST"])
def git_sync_batch():
    body = request.get_data() or b""
    expected_url = f"{PUBLIC_URL}/api/git-sync-batch" if PUBLIC_URL else None
    payload = qstash.verify_and_parse(dict(request.headers), body, url=expected_url)
    if payload is None:
        return ("unauthorized", 401)

    if not all(k in payload for k in ("owner", "repo", "branch", "paths")):
        return ("bad request", 400)

    summary = process_batch(payload)
    return (f"{summary.get('phase', '?')} added={summary.get('added')} "
            f"skipped={summary.get('skipped')} remaining={summary.get('remaining')}", 200)
