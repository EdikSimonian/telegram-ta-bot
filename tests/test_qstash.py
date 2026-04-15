"""QStash publish + signature verification."""
import base64
import hashlib
import hmac
import json
import time
from unittest.mock import patch, MagicMock


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_token(
    key: str, body: bytes,
    *,
    sub: str = "https://example.com/api/autoreveal",
    iat: int | None = None,
    exp: int | None = None,
    nbf: int | None = None,
    alg: str = "HS256",
) -> str:
    header = {"alg": alg, "typ": "JWT"}
    now = int(time.time())
    payload = {
        "iss":  "Upstash",
        "sub":  sub,
        "iat":  iat if iat is not None else now,
        "nbf":  nbf if nbf is not None else now,
        "exp":  exp if exp is not None else now + 600,
        "body": _b64url(hashlib.sha256(body).digest()),
    }
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode()
    sig = _b64url(hmac.new(key.encode(), signing_input, hashlib.sha256).digest())
    return f"{h}.{p}.{sig}"


SIGNING_KEY = "fake_qstash_current_key"
NEXT_KEY    = "fake_qstash_next_key"


# ── verify_signature ──────────────────────────────────────────────────────
def test_verify_signature_current_key_ok():
    body = b'{"chatId": "-100123"}'
    token = _make_token(SIGNING_KEY, body)
    from bot.qstash import verify_signature
    assert verify_signature(token, body) is True


def test_verify_signature_next_key_ok():
    """Either signing key should validate — supports rotation."""
    body = b'{"chatId": "-100123"}'
    token = _make_token(NEXT_KEY, body)
    from bot.qstash import verify_signature
    assert verify_signature(token, body) is True


def test_verify_signature_wrong_key_rejected():
    body = b'{"chatId": "-100123"}'
    token = _make_token("some_other_key_not_configured", body)
    from bot.qstash import verify_signature
    assert verify_signature(token, body) is False


def test_verify_signature_tampered_body_rejected():
    body = b'{"chatId": "-100123"}'
    token = _make_token(SIGNING_KEY, body)
    tampered = b'{"chatId": "-999999"}'
    from bot.qstash import verify_signature
    assert verify_signature(token, tampered) is False


def test_verify_signature_expired_rejected():
    body = b'{"chatId": "x"}'
    token = _make_token(SIGNING_KEY, body, exp=1)
    from bot.qstash import verify_signature
    assert verify_signature(token, body, now=int(time.time())) is False


def test_verify_signature_not_yet_valid_rejected():
    body = b'{"chatId": "x"}'
    future = int(time.time()) + 3600
    token = _make_token(SIGNING_KEY, body, nbf=future)
    from bot.qstash import verify_signature
    assert verify_signature(token, body, now=int(time.time())) is False


def test_verify_signature_url_mismatch_rejected():
    body = b'{"chatId": "x"}'
    token = _make_token(SIGNING_KEY, body, sub="https://evil.com/cb")
    from bot.qstash import verify_signature
    assert verify_signature(token, body, url="https://good.com/cb") is False


def test_verify_signature_url_match_accepted():
    body = b'{"chatId": "x"}'
    token = _make_token(SIGNING_KEY, body, sub="https://good.com/cb")
    from bot.qstash import verify_signature
    assert verify_signature(token, body, url="https://good.com/cb") is True


def test_verify_signature_malformed_token_rejected():
    from bot.qstash import verify_signature
    assert verify_signature("not.a.valid.jwt.at.all", b"body") is False
    assert verify_signature("", b"body") is False
    assert verify_signature("only.two", b"body") is False


def test_verify_signature_wrong_alg_rejected():
    body = b'{"chatId": "x"}'
    token = _make_token(SIGNING_KEY, body, alg="HS512")
    from bot.qstash import verify_signature
    assert verify_signature(token, body) is False


# ── verify_and_parse ──────────────────────────────────────────────────────
def test_verify_and_parse_returns_dict_on_valid():
    body = b'{"chatId": "-100123"}'
    token = _make_token(SIGNING_KEY, body)
    from bot.qstash import verify_and_parse
    out = verify_and_parse({"Upstash-Signature": token}, body)
    assert out == {"chatId": "-100123"}


def test_verify_and_parse_returns_none_without_header():
    from bot.qstash import verify_and_parse
    assert verify_and_parse({}, b'{"x": 1}') is None


def test_verify_and_parse_returns_none_on_bad_signature():
    body = b'{"chatId": "-100123"}'
    token = _make_token("bad_key", body)
    from bot.qstash import verify_and_parse
    assert verify_and_parse({"Upstash-Signature": token}, body) is None


# ── publish ───────────────────────────────────────────────────────────────
def test_publish_posts_with_auth_and_delay():
    with patch("bot.qstash.requests.post") as post, \
         patch("bot.qstash.QSTASH_URL", "https://qstash.up.io"), \
         patch("bot.qstash.QSTASH_TOKEN", "fake_token"):
        post.return_value = MagicMock(status_code=200, json=lambda: {"messageId": "m1"})
        from bot.qstash import publish
        out = publish("https://host/api/autoreveal", body={"chatId": "x"}, delay_seconds=180)
        assert out == "m1"
        call = post.call_args
        assert call.args[0] == "https://qstash.up.io/v2/publish/https://host/api/autoreveal"
        assert call.kwargs["headers"]["Authorization"] == "Bearer fake_token"
        assert call.kwargs["headers"]["Upstash-Delay"] == "180s"
        assert call.kwargs["json"] == {"chatId": "x"}


def test_publish_returns_none_without_token():
    with patch("bot.qstash.QSTASH_TOKEN", ""), \
         patch("bot.qstash.requests.post") as post:
        from bot.qstash import publish
        assert publish("https://x", body={}, delay_seconds=1) is None
        post.assert_not_called()


def test_publish_returns_none_on_http_error():
    with patch("bot.qstash.requests.post") as post, \
         patch("bot.qstash.QSTASH_TOKEN", "fake"):
        post.return_value = MagicMock(status_code=500, text="boom")
        from bot.qstash import publish
        assert publish("https://x", body={}, delay_seconds=1) is None


def test_publish_returns_none_on_network_error():
    with patch("bot.qstash.requests.post", side_effect=Exception("timeout")), \
         patch("bot.qstash.QSTASH_TOKEN", "fake"):
        from bot.qstash import publish
        assert publish("https://x", body={}, delay_seconds=1) is None
