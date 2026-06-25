"""Telegram Mini App (Web App) ``initData`` validation.

When a student opens the quiz Mini App, Telegram injects a signed
``initData`` query string into the page (``window.Telegram.WebApp.initData``).
The frontend POSTs that raw string to us; this module proves it really
came from Telegram for *this* bot before we trust the user id inside it.

Trust model mirrors ``bot/qstash.py``: a keyed HMAC we can recompute from
a secret we hold (the bot token). Nothing here is sent to the browser, so a
student cannot forge a session for another user without the bot token.

Algorithm (per core.telegram.org/bots/webapps#validating-data):
    secret_key       = HMAC_SHA256(key="WebAppData", msg=bot_token)
    data_check_string = "\n".join(f"{k}={v}" for k,v in sorted(fields))   # minus hash/signature
    expected          = hex(HMAC_SHA256(key=secret_key, msg=data_check_string))
    valid             = expected == provided_hash

``signature`` (the Bot API 8.0 third-party Ed25519 field) is excluded from
the data-check-string along with ``hash`` — it is not part of the HMAC.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from bot.config import TELEGRAM_TOKEN, WEBAPP_INIT_DATA_MAX_AGE


# Telegram clients disagree on whether the Bot API 8.0 ``signature`` field is
# part of the HMAC data-check-string. The canonical algorithm (and aiogram)
# excludes only ``hash`` — i.e. ``signature`` IS included. But some references
# exclude both. We accept a match on EITHER convention: a forgery still can't
# match without the bot token, so trying both costs nothing and is robust.
_EXCLUDE_SETS = (frozenset({"hash"}), frozenset({"hash", "signature"}))


def _hmac_matches(
    pairs: list[tuple[str, str]], provided_hash: str, exclude: frozenset[str]
) -> bool:
    items = sorted((k, v) for k, v in pairs if k not in exclude)
    data_check_string = "\n".join(f"{k}={v}" for k, v in items)
    secret_key = hmac.new(
        b"WebAppData", TELEGRAM_TOKEN.encode(), hashlib.sha256
    ).digest()
    expected = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, provided_hash)


def validate_init_data(
    init_data: str,
    *,
    max_age: int = WEBAPP_INIT_DATA_MAX_AGE,
    now: int | None = None,
) -> dict | None:
    """Validate a raw Mini App ``initData`` string.

    Returns a dict ``{"user": {...}, "start_param": str|None, "auth_date": int}``
    on success, or ``None`` on any failure (bad hash, missing/expired
    auth_date, unparseable user). Callers should treat ``None`` as 401.
    """
    if not init_data or not TELEGRAM_TOKEN:
        return None

    # parse_qsl URL-decodes values; Telegram signs the *decoded* values.
    # keep_blank_values so an empty start_param round-trips intact.
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    except Exception:
        return None

    fields = dict(pairs)
    provided_hash = fields.get("hash")
    if not provided_hash:
        return None

    if not any(_hmac_matches(pairs, provided_hash, excl) for excl in _EXCLUDE_SETS):
        return None

    # Freshness: reject stale initData to limit replay. auth_date is unix sec.
    try:
        auth_date = int(fields.get("auth_date", "0"))
    except (TypeError, ValueError):
        return None
    ts = int(now if now is not None else time.time())
    if auth_date <= 0 or (max_age > 0 and ts - auth_date > max_age):
        return None

    # user is a JSON blob; absent for some launch surfaces — required here
    # since we key the per-user shuffle + scoring on the id.
    try:
        user = json.loads(fields.get("user", ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(user, dict) or not user.get("id"):
        return None

    return {
        "user": user,
        "start_param": fields.get("start_param"),
        "auth_date": auth_date,
    }
