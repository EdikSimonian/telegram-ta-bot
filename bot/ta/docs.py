"""/doc admin command family.

Wire format (exact spec §5.3):
    /doc list
    /doc add <title>\n<content lines...>
    /doc update <title>\n<content lines...>
    /doc delete <title>

Content spans the line(s) after the title line. Everything is stored in
Vercel Blob, embedded into Upstash Vector, and indexed in Redis under
``ta:docs`` so /doc list stays fast.
"""
from __future__ import annotations

import html
import time

from bot import blob
from bot.ta import rag
from bot.ta.prepare import Prepared
from bot.ta.state import add_doc, list_docs, remove_doc
from bot.ta.tg import send_message


def dispatch(p: Prepared) -> None:
    """Called by bot/ta/commands.py when /doc is invoked."""
    raw = (p.command_args or "").strip()
    if not raw:
        send_message(p.user_id, "Usage: /doc list | /doc add <title>\\n<content> | "
                                "/doc update <title>\\n<content> | /doc delete <title>")
        return

    # Title may be multi-word, so split at first whitespace/newline for subcommand.
    first_line, _, rest = raw.partition("\n")
    tokens = first_line.strip().split(maxsplit=1)
    sub = tokens[0].lower() if tokens else ""
    arg = tokens[1] if len(tokens) > 1 else ""

    if sub == "list":
        _cmd_list(p)
        return
    if sub in ("add", "update"):
        title = arg.strip()
        content = rest.strip()
        if not title or not content:
            send_message(p.user_id, f"Usage: /doc {sub} <title>\\n<content>")
            return
        _cmd_upsert(p, sub, title, content)
        return
    if sub == "delete":
        title = arg.strip()
        if not title:
            send_message(p.user_id, "Usage: /doc delete <title>")
            return
        _cmd_delete(p, title)
        return
    send_message(p.user_id, f"Unknown /doc subcommand: {sub}")


def _cmd_list(p: Prepared) -> None:
    docs = list_docs()
    if not docs:
        send_message(p.user_id, "No docs indexed yet. Use /doc add to upload one.")
        return
    lines = ["<b>Indexed docs</b>"]
    for d in docs:
        title = d.get("title", "(untitled)")
        slug = d.get("slug", "?")
        chunks = d.get("chunkCount", "?")
        added_by = d.get("addedBy") or "(unknown)"
        lines.append(f"• <b>{html.escape(title)}</b> — <code>{html.escape(str(slug))}</code>, {chunks} chunks, by @{html.escape(str(added_by))}")
    send_message(p.user_id, "\n".join(lines), parse_mode="HTML")


def _find_existing_by_title(title: str) -> dict | None:
    """Case-insensitive substring match — same behavior as spec §5.3."""
    needle = title.lower()
    for d in list_docs():
        if needle in d.get("title", "").lower():
            return d
    return None


def _cmd_upsert(p: Prepared, sub: str, title: str, content: str) -> None:
    """Shared add + update path. Update deletes old vectors + blob first."""
    slug = rag.slugify(title)
    existing = _find_existing_by_title(title)

    if sub == "update":
        if not existing:
            send_message(p.user_id, f"No existing doc matches <code>{html.escape(title)}</code>.",
                         parse_mode="HTML")
            return
        _purge_doc(existing)
        slug = existing.get("slug", slug)
    elif existing:
        send_message(
            p.user_id,
            f"Doc already exists: <code>{existing.get('slug')}</code>. "
            f"Use /doc update to replace.",
            parse_mode="HTML",
        )
        return

    # 1. Blob: store full original text so we can re-ingest on schema changes.
    ts = int(time.time())
    blob_path = f"{slug}-{ts}.md"
    blob_url = blob.put(blob_path, content, content_type="text/markdown")
    if not blob_url:
        send_message(p.user_id, "Blob upload failed. Check BLOB_READ_WRITE_TOKEN and logs.")
        return

    # 2. Embed + upsert vectors.
    chunk_count = rag.upsert_doc(
        slug, title, content, blob_url=blob_url, added_by=p.username,
    )
    if chunk_count == 0:
        send_message(p.user_id, "Vector upsert failed — see logs. Blob was saved but is orphaned.")
        return

    # 3. Redis index — used by /doc list and /doc delete.
    add_doc({
        "slug":        slug,
        "title":       title,
        "blobUrl":     blob_url,
        "chunkCount":  chunk_count,
        "addedAt":     ts,
        "addedBy":     p.username or "",
    })

    verb = "updated" if sub == "update" else "added"
    send_message(
        p.user_id,
        f"✅ Doc {verb}: <b>{html.escape(title)}</b>\n"
        f"slug: <code>{html.escape(slug)}</code>\n"
        f"chunks: {chunk_count}\n"
        f"blob: {html.escape(blob_url or '')}",
        parse_mode="HTML",
    )


def _cmd_delete(p: Prepared, title: str) -> None:
    existing = _find_existing_by_title(title)
    if not existing:
        send_message(p.user_id, f"No doc matches <code>{html.escape(title)}</code>.", parse_mode="HTML")
        return
    _purge_doc(existing)
    send_message(
        p.user_id,
        f"✅ Deleted: <b>{html.escape(existing.get('title', ''))}</b> "
        f"(<code>{html.escape(existing.get('slug', ''))}</code>)",
        parse_mode="HTML",
    )


def _purge_doc(doc: dict) -> None:
    """Best-effort removal from all three stores."""
    slug = doc.get("slug", "")
    chunk_count = int(doc.get("chunkCount", 0))
    blob_url = doc.get("blobUrl", "")
    if slug and chunk_count:
        rag.delete_doc(slug, chunk_count)
    if blob_url:
        blob.delete(blob_url)
    if slug:
        remove_doc(slug)
