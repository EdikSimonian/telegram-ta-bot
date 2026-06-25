"""Telegram Mini App initData validation (bot/webapp.py)."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

# Matches the fake token set in conftest.py.
TOKEN = "1234567890:fake_token"


def _make_init_data(
    *,
    user=None,
    auth_date=None,
    start_param="tok123",
    tamper_hash=False,
    drop_user=False,
):
    """Build a faithfully-signed initData query string for the fake token."""
    if auth_date is None:
        auth_date = int(time.time())
    fields = {"auth_date": str(auth_date), "start_param": start_param}
    if not drop_user:
        user = user or {"id": 42, "first_name": "Alice", "username": "alice"}
        fields["user"] = json.dumps(user, separators=(",", ":"))

    # Hash is computed over the DECODED values (Telegram signs decoded data);
    # urlencode for transport round-trips back through parse_qsl on the server.
    data_check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    fields["hash"] = "0" * len(h) if tamper_hash else h
    return urlencode(fields)


def test_valid_init_data_passes():
    from bot.webapp import validate_init_data

    now = 1_700_000_000
    raw = _make_init_data(auth_date=now, start_param="abc")
    out = validate_init_data(raw, now=now)
    assert out is not None
    assert out["user"]["id"] == 42
    assert out["start_param"] == "abc"
    assert out["auth_date"] == now


def test_tampered_hash_rejected():
    from bot.webapp import validate_init_data

    now = 1_700_000_000
    raw = _make_init_data(auth_date=now, tamper_hash=True)
    assert validate_init_data(raw, now=now) is None


def test_modified_field_after_signing_rejected():
    from bot.webapp import validate_init_data

    now = 1_700_000_000
    raw = _make_init_data(auth_date=now, user={"id": 42, "first_name": "Alice"})
    # Swap the user id to 999 *after* signing — hash no longer matches.
    forged = raw.replace("%22id%22%3A42", "%22id%22%3A999")
    assert forged != raw
    assert validate_init_data(forged, now=now) is None


def test_expired_init_data_rejected():
    from bot.webapp import validate_init_data

    now = 1_700_000_000
    raw = _make_init_data(auth_date=now - 90_000)  # > default 86400s max age
    assert validate_init_data(raw, now=now) is None


def test_missing_user_rejected():
    from bot.webapp import validate_init_data

    now = 1_700_000_000
    raw = _make_init_data(auth_date=now, drop_user=True)
    assert validate_init_data(raw, now=now) is None


def test_validates_with_signature_field_included():
    """Real Bot API 8.0 initData carries a `signature` field that IS part of
    the HMAC check string (the canonical algorithm excludes only `hash`).
    This is the case our earlier (signature-excluding) code got wrong."""
    from bot.webapp import validate_init_data

    now = 1_700_000_000
    fields = {
        "auth_date": str(now),
        "user": json.dumps({"id": 7, "first_name": "Sig"}, separators=(",", ":")),
        "start_param": "tok",
        "signature": "ed25519_placeholder",
        "query_id": "AAEC",
    }
    # Sign with signature INCLUDED (hash isn't in the dict yet → excluded).
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    out = validate_init_data(urlencode(fields), now=now)
    assert out is not None
    assert out["user"]["id"] == 7
    assert out["start_param"] == "tok"


def test_empty_init_data_returns_none():
    from bot.webapp import validate_init_data

    assert validate_init_data("") is None
    assert validate_init_data("not-a-query-string") is None
