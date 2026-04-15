"""GitHub URL parsing, push payload parse, webhook signature verify."""
import hashlib
import hmac
from unittest.mock import patch


# ── parse_repo_url ────────────────────────────────────────────────────────
def test_parse_repo_short_form():
    from bot.github import parse_repo_url
    assert parse_repo_url("owner/repo") == ("owner", "repo", None)


def test_parse_repo_https_url():
    from bot.github import parse_repo_url
    assert parse_repo_url("https://github.com/EdikSimonian/telegram-ta-bot") \
        == ("EdikSimonian", "telegram-ta-bot", None)


def test_parse_repo_dot_git_suffix():
    from bot.github import parse_repo_url
    assert parse_repo_url("https://github.com/o/r.git") == ("o", "r", None)


def test_parse_repo_tree_branch():
    from bot.github import parse_repo_url
    assert parse_repo_url("https://github.com/o/r/tree/develop") == ("o", "r", "develop")


def test_parse_repo_rejects_junk():
    from bot.github import parse_repo_url
    assert parse_repo_url("not a url") is None
    assert parse_repo_url("") is None


# ── changed_paths_from_push ───────────────────────────────────────────────
def test_changed_paths_dedup_and_filter_to_text():
    from bot.github import changed_paths_from_push
    payload = {"commits": [
        {"added": ["a.md", "img.png"], "modified": ["b.py"]},
        {"added": ["a.md"],            "modified": ["c.ipynb", "vendor.min.js"]},
    ]}
    out = set(changed_paths_from_push(payload))
    assert out == {"a.md", "b.py", "c.ipynb", "vendor.min.js"}


def test_removed_paths_collected():
    from bot.github import removed_paths_from_push
    payload = {"commits": [
        {"removed": ["old.md"]},
        {"removed": ["also-old.py", "old.md"]},
    ]}
    assert set(removed_paths_from_push(payload)) == {"old.md", "also-old.py"}


# ── Webhook signature ─────────────────────────────────────────────────────
def _sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_verify_good_signature():
    body = b'{"x": 1}'
    with patch("api.github.GITHUB_WEBHOOK_SECRET", "s3cret"):
        from api.github import _verify
        assert _verify(_sig("s3cret", body), body) is True


def test_webhook_verify_rejects_wrong_secret():
    body = b'{"x": 1}'
    with patch("api.github.GITHUB_WEBHOOK_SECRET", "s3cret"):
        from api.github import _verify
        assert _verify(_sig("other", body), body) is False


def test_webhook_verify_rejects_missing_secret():
    body = b'{}'
    with patch("api.github.GITHUB_WEBHOOK_SECRET", ""):
        from api.github import _verify
        assert _verify(_sig("anything", body), body) is False


def test_webhook_verify_rejects_bad_format():
    body = b'{}'
    with patch("api.github.GITHUB_WEBHOOK_SECRET", "s"):
        from api.github import _verify
        assert _verify("bogus", body) is False
        assert _verify("", body) is False
