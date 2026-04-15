"""Upstash QStash — delayed callback publisher + signature verifier.

We use QStash to schedule the 3-minute quiz auto-reveal without keeping
a long-running process alive. On quiz start:

    publish(callback_url, delay_seconds=180, body={...})

QStash holds the message and eventually POSTs the body back to
``callback_url`` with an ``Upstash-Signature`` JWT header. The callback
must verify the signature before acting (any unsigned request could
have been spoofed).

Signatures use HS256 with the current + next signing keys (rotation
support); we accept a match on either. No external JWT library — the
format is simple enough to decode with base64 + hmac.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import requests

from bot.config import (
    QSTASH_CURRENT_SIGNING_KEY,
    QSTASH_NEXT_SIGNING_KEY,
    QSTASH_TOKEN,
    QSTASH_URL,
)


class QStashError(Exception):
    pass


# ── Publish ───────────────────────────────────────────────────────────────
def publish(callback_url: str, body: dict, delay_seconds: int) -> str | None:
    """Schedule ``body`` to be POSTed to ``callback_url`` after ``delay_seconds``.

    Returns the message id on success, or None on error. Caller should
    log its return and fall through to the inline expiry fallback if
    publish failed — the quiz will still reveal, just on the next
    student interaction in that chat.
    """
    if not QSTASH_TOKEN:
        print("[qstash] QSTASH_TOKEN unset — skipping publish()")
        return None
    if not callback_url:
        print("[qstash] callback_url empty — skipping publish()")
        return None

    # QStash convention: the destination URL is appended to the publish path
    # rather than passed in a body field. This keeps routing stateless.
    publish_path = f"{QSTASH_URL}/v2/publish/{callback_url}"
    try:
        resp = requests.post(
            publish_path,
            json=body,
            headers={
                "Authorization": f"Bearer {QSTASH_TOKEN}",
                "Upstash-Delay":  f"{int(delay_seconds)}s",
                "Content-Type":   "application/json",
            },
            timeout=10,
        )
    except Exception as e:
        print(f"[qstash] publish network error: {e}")
        return None

    if resp.status_code >= 400:
        print(f"[qstash] publish HTTP {resp.status_code}: {resp.text[:200]}")
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    return data.get("messageId")


# ── Signature verification ────────────────────────────────────────────────
def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _hs256(key: str, data: bytes) -> bytes:
    return hmac.new(key.encode("utf-8"), data, hashlib.sha256).digest()


def verify_signature(
    token: str,
    body: bytes,
    url: str | None = None,
    *,
    leeway: int = 60,
    now: int | None = None,
) -> bool:
    """Validate an ``Upstash-Signature`` JWT.

    Accepts a match on CURRENT or NEXT signing key (rotation).
    Returns False on any validation failure — unknown alg, bad HMAC,
    expired/not-yet-valid, or wrong body hash. ``url`` is optional but
    strongly recommended: when set, we also check the JWT's ``sub``
    matches the request URL.
    """
    if not token:
        return False
    keys = [k for k in (QSTASH_CURRENT_SIGNING_KEY, QSTASH_NEXT_SIGNING_KEY) if k]
    if not keys:
        print("[qstash] no signing keys configured — rejecting")
        return False

    parts = token.split(".")
    if len(parts) != 3:
        return False
    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    try:
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
        given_sig = _b64url_decode(sig_b64)
    except Exception as e:
        print(f"[qstash] token decode error: {e}")
        return False

    if header.get("alg") != "HS256":
        return False

    # Any key match wins (current + next for rotation).
    if not any(hmac.compare_digest(_hs256(k, signing_input), given_sig) for k in keys):
        return False

    ts = int(now if now is not None else time.time())
    iat = int(payload.get("iat", 0))
    nbf = int(payload.get("nbf", iat))
    exp = int(payload.get("exp", 0))
    if exp and ts > exp + leeway:
        return False
    if nbf and ts + leeway < nbf:
        return False

    # Body hash (sub-optional: older tokens may omit `body`).
    expected_body_hash = payload.get("body")
    if expected_body_hash:
        h = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode()
        if h != expected_body_hash:
            return False

    # URL binding: defense against replays to a different endpoint.
    if url:
        sub = payload.get("sub") or ""
        if sub and sub.rstrip("/") != url.rstrip("/"):
            return False

    return True


# ── Helper used by quiz + autoreveal ──────────────────────────────────────
def verify_and_parse(
    request_headers: dict, request_body: bytes, *, url: str | None = None,
) -> Any | None:
    """Verify the Upstash-Signature header and return the JSON body.

    Returns None when the signature is missing/invalid or the body isn't
    valid JSON. Callers should 401 on None.
    """
    sig = request_headers.get("Upstash-Signature") or request_headers.get("upstash-signature")
    if not verify_signature(sig or "", request_body, url=url):
        return None
    try:
        return json.loads(request_body.decode("utf-8"))
    except Exception:
        return None
