"""Vercel Blob wrapper.

Thin adapter over the ``vercel_blob`` package so the rest of the
codebase talks in simple primitives and sees consistent ``None``
returns on failure. Also enforces the ``BLOB_PATH_PREFIX`` so a shared
Blob store can host prod and test docs without collisions.
"""
from __future__ import annotations

import os

from bot.config import BLOB_PATH_PREFIX, BLOB_READ_WRITE_TOKEN

try:
    import vercel_blob  # type: ignore
except ImportError:
    vercel_blob = None  # type: ignore


def _ensure_token_env() -> None:
    """vercel_blob reads BLOB_READ_WRITE_TOKEN from os.environ — make sure it's there.

    On Vercel it's auto-injected. Locally, some loaders leave it out.
    """
    if BLOB_READ_WRITE_TOKEN and not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        os.environ["BLOB_READ_WRITE_TOKEN"] = BLOB_READ_WRITE_TOKEN


def _qualify(path: str) -> str:
    """Return the blob pathname with the env-scoped prefix applied."""
    clean = path.lstrip("/")
    if clean.startswith(BLOB_PATH_PREFIX):
        return clean
    return BLOB_PATH_PREFIX + clean


def put(path: str, data: bytes | str, *, content_type: str | None = None) -> str | None:
    """Upload ``data`` under ``path``. Returns the public URL, or None on error."""
    if vercel_blob is None:
        print("[blob] vercel_blob not installed — skipping put()")
        return None
    if not BLOB_READ_WRITE_TOKEN and not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        print("[blob] BLOB_READ_WRITE_TOKEN unset — skipping put()")
        return None
    _ensure_token_env()
    if isinstance(data, str):
        data = data.encode("utf-8")
    opts: dict = {}
    if content_type:
        opts["contentType"] = content_type
    try:
        result = vercel_blob.put(_qualify(path), data, options=opts or None)
        return result.get("url") if isinstance(result, dict) else None
    except Exception as e:
        print(f"[blob] put error: {e}")
        return None


def delete(url_or_urls) -> bool:
    """Delete one or more blobs by URL. Returns True when no errors."""
    if vercel_blob is None:
        return False
    _ensure_token_env()
    try:
        vercel_blob.delete(url_or_urls)
        return True
    except Exception as e:
        print(f"[blob] delete error: {e}")
        return False


def list_blobs(prefix: str | None = None) -> list[dict]:
    """List blobs, scoped to the env prefix by default."""
    if vercel_blob is None:
        return []
    _ensure_token_env()
    effective = _qualify(prefix) if prefix else BLOB_PATH_PREFIX
    try:
        resp = vercel_blob.list(options={"prefix": effective})
        return resp.get("blobs", []) if isinstance(resp, dict) else []
    except Exception as e:
        print(f"[blob] list error: {e}")
        return []
