"""Ingest a whole GitHub repo into Upstash Vector.

Each file becomes its own Vector "document" via bot.ta.rag.upsert_doc.
Slug format: ``gh-{owner}-{repo}-{path-slug}`` so different repos never
collide. Removing a repo walks the saved slug list and deletes all
vectors in a single pass.

Two ingest paths:

    sync_repo()        — synchronous, fine for small repos and the webhook
                         delta path (handful of changed files per push).
    sync_repo_async()  — fans the file list out across QStash so each
                         file lands in its own ~2s function call. Required
                         for repos big enough to bust Vercel's 60s cap.
"""
from __future__ import annotations

import time
from typing import Iterable

from bot import github, qstash
from bot.config import PUBLIC_URL
from bot.ta import rag
from bot.ta.state import (
    add_doc,
    add_git_repo,
    get_git_repo,
    list_docs,
    list_git_repos,
    remove_doc,
    remove_git_repo,
)


def _slug(owner: str, repo: str, path: str) -> str:
    base = f"gh-{owner}-{repo}-{rag.slugify(path)}"
    return base[:120]


def _doc_title(owner: str, repo: str, path: str) -> str:
    return f"{owner}/{repo}: {path}"


def _file_url(owner: str, repo: str, ref: str, path: str) -> str:
    return f"https://github.com/{owner}/{repo}/blob/{ref}/{path}"


def sync_repo(
    owner: str,
    repo: str,
    ref: str | None,
    *,
    added_by: str | None = None,
    paths: Iterable[str] | None = None,
) -> dict:
    """Ingest ``paths`` from ``owner/repo@ref``. If ``paths`` is None, ingest
    everything the tree walk returns. Returns a result summary dict.
    """
    branch = ref or github.default_branch(owner, repo)
    if not branch:
        return {"ok": False, "reason": "could not resolve default branch",
                "files_added": 0, "files_skipped": 0}

    if paths is None:
        tree = github.list_tree(owner, repo, branch)
    else:
        # Turn the explicit path list into tree-entry-shaped records. We
        # still need the SHA to fetch via git/blobs, so fall back to
        # walking the full tree and filtering.
        full = github.list_tree(owner, repo, branch)
        target = {p for p in paths}
        tree = [t for t in full if t["path"] in target]

    added = 0
    skipped = 0
    for entry in tree:
        path = entry["path"]
        sha  = entry["sha"]
        text = github.fetch_blob(owner, repo, sha)
        if not text or not text.strip():
            skipped += 1
            continue
        slug = _slug(owner, repo, path)
        title = _doc_title(owner, repo, path)
        blob_url = _file_url(owner, repo, branch, path)

        # Remove stale vectors for this path (idempotent upsert).
        existing = next((d for d in list_docs() if d.get("slug") == slug), None)
        if existing:
            rag.delete_doc(slug, int(existing.get("chunkCount", 0)))
            remove_doc(slug)

        chunk_count = rag.upsert_doc(
            slug, title, text, blob_url=blob_url, added_by=added_by or "github-ingest",
        )
        if chunk_count == 0:
            skipped += 1
            continue
        add_doc({
            "slug":       slug,
            "title":      title,
            "blobUrl":    blob_url,
            "chunkCount": chunk_count,
            "addedAt":    int(time.time()),
            "addedBy":    added_by or "github-ingest",
            "source":     "github",
            "ghOwner":    owner,
            "ghRepo":     repo,
            "ghPath":     path,
        })
        added += 1

    register_meta = get_git_repo(owner, repo) or {}
    register_meta.update({
        "url":       github.canonical_url(owner, repo),
        "owner":     owner,
        "repo":      repo,
        "branch":    branch,
        "lastSync":  int(time.time()),
        "addedBy":   register_meta.get("addedBy") or (added_by or ""),
    })
    register_meta.setdefault("addedAt", int(time.time()))
    add_git_repo(register_meta)

    return {
        "ok": True,
        "branch": branch,
        "files_added": added,
        "files_skipped": skipped,
    }


def ingest_one_file(
    owner: str,
    repo: str,
    branch: str,
    path: str,
    sha: str,
    *,
    added_by: str | None = None,
) -> bool:
    """Ingest a single file. Used by the QStash callback handler.

    Idempotent: existing chunks for this slug are deleted first, so a
    QStash retry replays cleanly. Returns True when something landed.
    """
    text = github.fetch_blob(owner, repo, sha)
    if not text or not text.strip():
        return False

    slug = _slug(owner, repo, path)
    title = _doc_title(owner, repo, path)
    blob_url = _file_url(owner, repo, branch, path)

    existing = next((d for d in list_docs() if d.get("slug") == slug), None)
    if existing:
        rag.delete_doc(slug, int(existing.get("chunkCount", 0)))
        remove_doc(slug)

    chunk_count = rag.upsert_doc(
        slug, title, text, blob_url=blob_url, added_by=added_by or "github-ingest",
    )
    if chunk_count == 0:
        return False

    add_doc({
        "slug":       slug,
        "title":      title,
        "blobUrl":    blob_url,
        "chunkCount": chunk_count,
        "addedAt":    int(time.time()),
        "addedBy":    added_by or "github-ingest",
        "source":     "github",
        "ghOwner":    owner,
        "ghRepo":     repo,
        "ghPath":     path,
    })
    return True


BATCH_SIZE = 20  # files per QStash callback — ~40s on average, well under 60s cap


def sync_repo_async(
    owner: str,
    repo: str,
    ref: str | None,
    *,
    added_by: str | None = None,
    notify_chat_id: int | str | None = None,
) -> dict:
    """Schedule batched ingest via QStash.

    Publishes a SINGLE QStash message with the full path list. The
    /api/git-sync-batch handler processes BATCH_SIZE files inline, then
    publishes a follow-up message with the remainder (if any). When the
    last batch completes, ``notify_chat_id`` (if provided) gets a
    completion DM.

    Result keys:
        ok, branch, files_total, batches, queued (True if QStash accepted)
    """
    if not PUBLIC_URL:
        return {"ok": False, "reason": "PUBLIC_URL unset; cannot build QStash callback"}

    branch = ref or github.default_branch(owner, repo)
    if not branch:
        return {"ok": False, "reason": "could not resolve default branch"}

    tree = github.list_tree(owner, repo, branch)
    if not tree:
        return {"ok": False, "reason": "repo tree was empty or not readable"}

    # Register up-front so webhook deltas + /git list both work even if
    # individual file ingests fail later.
    existing_meta = get_git_repo(owner, repo) or {}
    existing_meta.update({
        "url":      github.canonical_url(owner, repo),
        "owner":    owner,
        "repo":     repo,
        "branch":   branch,
        "addedBy":  existing_meta.get("addedBy") or (added_by or ""),
        "lastSync": int(time.time()),
    })
    existing_meta.setdefault("addedAt", int(time.time()))
    add_git_repo(existing_meta)

    paths = [{"path": e["path"], "sha": e["sha"]} for e in tree]
    body = {
        "owner":        owner,
        "repo":         repo,
        "branch":       branch,
        "paths":        paths,
        "addedBy":      added_by or "",
        "notifyChatId": str(notify_chat_id) if notify_chat_id else "",
        "added":        0,
        "skipped":      0,
    }
    msg_id = qstash.publish(
        f"{PUBLIC_URL}/api/git-sync-batch",
        body=body,
        delay_seconds=0,
    )
    if not msg_id:
        return {
            "ok": False,
            "reason": "QStash publish failed (check token + signing keys)",
            "branch": branch, "files_total": len(tree),
        }

    batches = (len(tree) + BATCH_SIZE - 1) // BATCH_SIZE
    return {
        "ok": True,
        "branch": branch,
        "files_total": len(tree),
        "batches": batches,
        "queued": True,
    }


def process_batch(payload: dict) -> dict:
    """Run one QStash-delivered batch. Called by api/git_sync_batch.py.

    Processes BATCH_SIZE files inline, then either publishes a follow-up
    QStash message with the remainder, or DMs the notify chat that the
    repo is complete. Returns a summary so the endpoint can log it.
    """
    owner   = payload["owner"]
    repo    = payload["repo"]
    branch  = payload["branch"]
    paths   = payload.get("paths") or []
    added   = int(payload.get("added", 0))
    skipped = int(payload.get("skipped", 0))
    notify  = payload.get("notifyChatId") or ""
    addedBy = payload.get("addedBy") or "github-fanout"

    head, tail = paths[:BATCH_SIZE], paths[BATCH_SIZE:]
    for entry in head:
        ok = ingest_one_file(
            owner, repo, branch, entry["path"], entry["sha"], added_by=addedBy,
        )
        if ok:
            added += 1
        else:
            skipped += 1

    if tail:
        # More work — publish follow-up. Failure here means the run is
        # truncated; the partial state is still indexed.
        qstash.publish(
            f"{PUBLIC_URL}/api/git-sync-batch",
            body={
                "owner": owner, "repo": repo, "branch": branch,
                "paths": tail, "addedBy": addedBy, "notifyChatId": notify,
                "added": added, "skipped": skipped,
            },
            delay_seconds=0,
        )
        return {"phase": "continued", "added": added, "skipped": skipped, "remaining": len(tail)}

    # Final batch — stamp lastSync + notify if asked.
    meta = get_git_repo(owner, repo) or {"owner": owner, "repo": repo, "branch": branch}
    meta["lastSync"] = int(time.time())
    add_git_repo(meta)

    if notify:
        try:
            from bot.clients import bot
            bot.send_message(
                int(notify) if notify.lstrip("-").isdigit() else notify,
                f"✅ <b>{owner}/{repo}</b> sync complete — "
                f"added {added}, skipped {skipped}",
                parse_mode="HTML",
            )
        except Exception as e:
            print(f"[git_ingest] notify error: {e}")

    return {"phase": "done", "added": added, "skipped": skipped, "remaining": 0}


def remove_synced_paths(owner: str, repo: str, paths: Iterable[str]) -> int:
    """Called by webhook when commits remove files. Returns count purged."""
    purged = 0
    for path in paths:
        slug = _slug(owner, repo, path)
        existing = next((d for d in list_docs() if d.get("slug") == slug), None)
        if not existing:
            continue
        rag.delete_doc(slug, int(existing.get("chunkCount", 0)))
        remove_doc(slug)
        purged += 1
    return purged


def remove_all(owner: str, repo: str) -> int:
    """Purge every vector + doc entry for this repo. Returns count removed."""
    purged = 0
    for d in list(list_docs()):
        if d.get("source") == "github" and \
                d.get("ghOwner", "").lower() == owner.lower() and \
                d.get("ghRepo", "").lower() == repo.lower():
            rag.delete_doc(d.get("slug", ""), int(d.get("chunkCount", 0)))
            remove_doc(d.get("slug", ""))
            purged += 1
    remove_git_repo(owner, repo)
    return purged
