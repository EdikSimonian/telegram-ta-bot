"""Vercel Blob wrapper (bot/blob.py)."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch


def _fresh_blob_module(vercel_blob_mock):
    """Re-import bot.blob with a patched vercel_blob dependency."""
    sys.modules.pop("bot.blob", None)
    sys.modules["vercel_blob"] = vercel_blob_mock
    import bot.blob as mod
    return mod


# ── _qualify ──────────────────────────────────────────────────────────────
def test_qualify_prepends_prefix_once():
    import bot.blob as mod
    # Default prefix in tests is "docs/".
    assert mod._qualify("guide.md").startswith("docs/")
    # Already-prefixed path is not double-prefixed.
    assert mod._qualify("docs/guide.md") == "docs/guide.md"
    # Leading slash is stripped before prefixing.
    assert mod._qualify("/guide.md") == "docs/guide.md"


# ── put ───────────────────────────────────────────────────────────────────
def test_put_returns_url_and_encodes_string():
    fake = MagicMock()
    fake.put.return_value = {"url": "https://blob.vercel.app/docs/x.md"}
    with patch("bot.blob.vercel_blob", fake):
        import bot.blob as mod
        url = mod.put("x.md", "hello", content_type="text/markdown")
        assert url == "https://blob.vercel.app/docs/x.md"
        # String data is utf-8 encoded before upload.
        args, kwargs = fake.put.call_args
        assert args[0] == "docs/x.md"
        assert args[1] == b"hello"
        assert kwargs["options"] == {"contentType": "text/markdown"}


def test_put_returns_none_when_dependency_missing():
    with patch("bot.blob.vercel_blob", None):
        import bot.blob as mod
        assert mod.put("x.md", b"data") is None


def test_put_swallows_upload_errors():
    fake = MagicMock()
    fake.put.side_effect = RuntimeError("boom")
    with patch("bot.blob.vercel_blob", fake):
        import bot.blob as mod
        assert mod.put("x.md", b"data") is None


# ── delete ────────────────────────────────────────────────────────────────
def test_delete_happy_path():
    fake = MagicMock()
    with patch("bot.blob.vercel_blob", fake):
        import bot.blob as mod
        assert mod.delete("https://blob.vercel.app/docs/x.md") is True
        fake.delete.assert_called_once_with("https://blob.vercel.app/docs/x.md")


def test_delete_returns_false_on_exception():
    fake = MagicMock()
    fake.delete.side_effect = RuntimeError("boom")
    with patch("bot.blob.vercel_blob", fake):
        import bot.blob as mod
        assert mod.delete("https://blob.vercel.app/docs/x.md") is False


def test_delete_no_dependency():
    with patch("bot.blob.vercel_blob", None):
        import bot.blob as mod
        assert mod.delete("url") is False


# ── list ──────────────────────────────────────────────────────────────────
def test_list_scopes_to_prefix_and_returns_blobs():
    fake = MagicMock()
    fake.list.return_value = {"blobs": [{"url": "u1"}, {"url": "u2"}]}
    with patch("bot.blob.vercel_blob", fake):
        import bot.blob as mod
        blobs = mod.list_blobs()
        assert len(blobs) == 2
        # Called with the env-scoped prefix.
        _, kwargs = fake.list.call_args
        assert kwargs["options"]["prefix"].startswith("docs/")


def test_list_returns_empty_on_failure():
    fake = MagicMock()
    fake.list.side_effect = RuntimeError("boom")
    with patch("bot.blob.vercel_blob", fake):
        import bot.blob as mod
        assert mod.list_blobs() == []
