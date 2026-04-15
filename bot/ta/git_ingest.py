"""Ingest a whole GitHub repo into Upstash Vector.

Each file becomes its own Vector "document" via bot.ta.rag.upsert_doc.
Slug format: ``gh-{owner}-{repo}-{path-slug}`` so different repos never
collide. Removing a repo walks the saved slug list and deletes all
vectors in a single pass.
"""
from __future__ import annotations

import time
from typing import Iterable

from bot import github
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
