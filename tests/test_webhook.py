from unittest.mock import patch, MagicMock


def test_webhook_rejects_bad_secret():
    mock_request = MagicMock()
    mock_request.headers.get.return_value = "wrong_secret"
    mock_request.get_data.return_value = "{}"
    with (
        patch("api.index.WEBHOOK_SECRET", "correct_secret"),
        patch("api.index.request", mock_request),
        patch("api.index.bot"),
    ):
        from api.index import webhook

        result = webhook()
        assert result == ("Forbidden", 403)


def test_webhook_accepts_correct_secret():
    mock_request = MagicMock()
    mock_request.headers.get.return_value = "correct_secret"
    mock_request.get_data.return_value = "{}"
    with (
        patch("api.index.WEBHOOK_SECRET", "correct_secret"),
        patch("api.index.request", mock_request),
        patch("api.index.bot"),
        patch("api.index.telebot") as mock_telebot,
    ):
        mock_telebot.types.Update.de_json.return_value = MagicMock()
        from api.index import webhook

        result = webhook()
        assert result == ("OK", 200)


def test_webhook_skips_validation_when_no_secret_in_local_env():
    """Local dev (BOT_ENV=local) is allowed to run without WEBHOOK_SECRET —
    polling-driven dev sessions don't need spoof protection."""
    mock_request = MagicMock()
    mock_request.get_data.return_value = "{}"
    with (
        patch("api.index.WEBHOOK_SECRET", ""),
        patch("api.index.BOT_ENV", "local"),
        patch("api.index.request", mock_request),
        patch("api.index.bot"),
        patch("api.index.telebot") as mock_telebot,
    ):
        mock_telebot.types.Update.de_json.return_value = MagicMock()
        from api.index import webhook

        result = webhook()
        assert result == ("OK", 200)


def test_webhook_fails_closed_when_no_secret_in_prod_env():
    """Any non-local environment (prod, test) must have WEBHOOK_SECRET set —
    otherwise the endpoint refuses to dispatch updates rather than silently
    accepting spoofed ones."""
    mock_request = MagicMock()
    mock_request.get_data.return_value = "{}"
    with (
        patch("api.index.WEBHOOK_SECRET", ""),
        patch("api.index.BOT_ENV", "production"),
        patch("api.index.request", mock_request),
        patch("api.index.bot"),
    ):
        from api.index import webhook

        result, status = webhook()
        assert status == 500


# ── /api/notify-admin ─────────────────────────────────────────────────────
def _notify_request(header_secret: str, body: dict | None):
    req = MagicMock()
    req.headers.get.return_value = header_secret
    req.get_json.return_value = body
    return req


def test_notify_admin_rejects_bad_secret():
    req = _notify_request("wrong", {"text": "hi"})
    with patch("api.index.WEBHOOK_SECRET", "correct"), patch("api.index.request", req):
        from api.index import notify_admin

        assert notify_admin() == ("Forbidden", 403)


def test_notify_admin_requires_configured_secret():
    req = _notify_request("anything", {"text": "hi"})
    with patch("api.index.WEBHOOK_SECRET", ""), patch("api.index.request", req):
        from api.index import notify_admin

        result, status = notify_admin()
        assert status == 500


def test_notify_admin_rejects_empty_text():
    req = _notify_request("correct", {"text": "   "})
    with patch("api.index.WEBHOOK_SECRET", "correct"), patch("api.index.request", req):
        from api.index import notify_admin

        result, status = notify_admin()
        assert status == 400


def test_notify_admin_404_when_admin_chat_unknown():
    req = _notify_request("correct", {"text": "hi"})
    with (
        patch("api.index.WEBHOOK_SECRET", "correct"),
        patch("api.index.request", req),
        patch("api.index.get_user_chat", return_value=None),
    ):
        from api.index import notify_admin

        result, status = notify_admin()
        assert status == 404


def test_notify_admin_sends_message_and_returns_ok():
    req = _notify_request("correct", {"text": "hello admin", "parse_mode": "HTML"})
    mock_bot = MagicMock()
    with (
        patch("api.index.WEBHOOK_SECRET", "correct"),
        patch("api.index.request", req),
        patch("api.index.get_user_chat", return_value=42),
        patch("api.index.bot", mock_bot),
    ):
        from api.index import notify_admin

        result, status = notify_admin()
        assert status == 200
        mock_bot.send_message.assert_called_once_with(
            42, "hello admin", parse_mode="HTML"
        )


def test_notify_admin_surfaces_send_error():
    req = _notify_request("correct", {"text": "hello"})
    mock_bot = MagicMock()
    mock_bot.send_message.side_effect = RuntimeError("telegram 429")
    with (
        patch("api.index.WEBHOOK_SECRET", "correct"),
        patch("api.index.request", req),
        patch("api.index.get_user_chat", return_value=42),
        patch("api.index.bot", mock_bot),
    ):
        from api.index import notify_admin

        result, status = notify_admin()
        assert status == 502
