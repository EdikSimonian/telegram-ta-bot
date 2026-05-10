"""Tests for bot.voice (Cloudflare Whisper-turbo) and the voice handler.

Conftest mocks telebot/openai/upstash at sys.modules level. ``requests`` is
not auto-mocked so we patch ``bot.voice.requests.post`` per-test, mirroring
the pattern in tests/test_search.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ── bot.voice.transcribe ──────────────────────────────────────────────────


def _ok_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {
        "result": {"text": text},
        "success": True,
        "errors": [],
    }
    resp.raise_for_status = MagicMock()
    return resp


def test_transcribe_returns_text():
    with (
        patch("bot.voice.CLOUDFLARE_ACCOUNT_ID", "acct123"),
        patch("bot.voice.CLOUDFLARE_API_TOKEN", "tok456"),
        patch("bot.voice.requests.post", return_value=_ok_response("hello world")),
    ):
        from bot.voice import transcribe

        assert transcribe(b"raw-ogg-bytes") == "hello world"


def test_transcribe_strips_whitespace():
    with (
        patch("bot.voice.CLOUDFLARE_ACCOUNT_ID", "acct"),
        patch("bot.voice.CLOUDFLARE_API_TOKEN", "tok"),
        patch("bot.voice.requests.post", return_value=_ok_response("  hi  ")),
    ):
        from bot.voice import transcribe

        assert transcribe(b"x") == "hi"


def test_transcribe_sends_base64_payload():
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _ok_response("ok")

    with (
        patch("bot.voice.CLOUDFLARE_ACCOUNT_ID", "acct789"),
        patch("bot.voice.CLOUDFLARE_API_TOKEN", "tokABC"),
        patch("bot.voice.requests.post", side_effect=fake_post),
    ):
        from bot.voice import transcribe

        transcribe(b"hello")

    assert "acct789" in captured["url"]
    assert captured["url"].endswith("@cf/openai/whisper-large-v3-turbo")
    # base64 of "hello" is "aGVsbG8="
    assert captured["json"] == {"audio": "aGVsbG8="}
    assert captured["headers"]["Authorization"] == "Bearer tokABC"
    assert captured["headers"]["Content-Type"] == "application/json"


def test_transcribe_raises_when_disabled():
    with (
        patch("bot.voice.CLOUDFLARE_ACCOUNT_ID", ""),
        patch("bot.voice.CLOUDFLARE_API_TOKEN", ""),
    ):
        from bot.voice import transcribe
        import pytest

        with pytest.raises(RuntimeError, match="not configured"):
            transcribe(b"x")


def test_transcribe_raises_on_api_error_envelope():
    fail_resp = MagicMock()
    fail_resp.json.return_value = {
        "result": {},
        "success": False,
        "errors": [{"message": "AiError", "code": 8001}],
    }
    fail_resp.raise_for_status = MagicMock()
    with (
        patch("bot.voice.CLOUDFLARE_ACCOUNT_ID", "acct"),
        patch("bot.voice.CLOUDFLARE_API_TOKEN", "tok"),
        patch("bot.voice.requests.post", return_value=fail_resp),
    ):
        from bot.voice import transcribe
        import pytest

        with pytest.raises(RuntimeError, match="failed"):
            transcribe(b"x")


def test_is_enabled_requires_both_creds():
    import bot.voice as voice

    with (
        patch.object(voice, "CLOUDFLARE_ACCOUNT_ID", ""),
        patch.object(voice, "CLOUDFLARE_API_TOKEN", ""),
    ):
        assert voice.is_enabled() is False
    with (
        patch.object(voice, "CLOUDFLARE_ACCOUNT_ID", "acct"),
        patch.object(voice, "CLOUDFLARE_API_TOKEN", ""),
    ):
        assert voice.is_enabled() is False
    with (
        patch.object(voice, "CLOUDFLARE_ACCOUNT_ID", ""),
        patch.object(voice, "CLOUDFLARE_API_TOKEN", "tok"),
    ):
        assert voice.is_enabled() is False
    with (
        patch.object(voice, "CLOUDFLARE_ACCOUNT_ID", "acct"),
        patch.object(voice, "CLOUDFLARE_API_TOKEN", "tok"),
    ):
        assert voice.is_enabled() is True


# ── bot.handlers._route_voice ─────────────────────────────────────────────


def _make_voice_message(duration: int = 5, file_id: str = "voice-file-id"):
    msg = MagicMock()
    msg.voice = MagicMock(duration=duration, file_id=file_id)
    msg.text = None
    return msg


def test_route_voice_skips_when_disabled():
    msg = _make_voice_message()
    with (
        patch("bot.handlers.voice_module.is_enabled", return_value=False),
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.ta_admin.route") as mock_route,
    ):
        from bot.handlers import _route_voice

        _route_voice(msg)

        mock_bot.reply_to.assert_called_once()
        reply_text = mock_bot.reply_to.call_args[0][1]
        assert (
            "aren't enabled" in reply_text.lower()
            or "not enabled" in reply_text.lower()
        )
        mock_route.assert_not_called()


def test_route_voice_rejects_too_long():
    msg = _make_voice_message(duration=999)
    with (
        patch("bot.handlers.voice_module.is_enabled", return_value=True),
        patch("bot.handlers.MAX_VOICE_SECONDS", 30),
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.ta_admin.route") as mock_route,
    ):
        from bot.handlers import _route_voice

        _route_voice(msg)

        mock_bot.reply_to.assert_called_once()
        reply_text = mock_bot.reply_to.call_args[0][1]
        assert "too long" in reply_text.lower()
        mock_route.assert_not_called()


def test_route_voice_transcribes_and_routes():
    msg = _make_voice_message(duration=10)
    with (
        patch("bot.handlers.voice_module.is_enabled", return_value=True),
        patch("bot.handlers.voice_module.transcribe", return_value="what is RAG"),
        patch("bot.handlers.MAX_VOICE_SECONDS", 30),
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.ta_admin.route") as mock_route,
    ):
        mock_bot.get_file.return_value = MagicMock(file_path="voices/abc.ogg")
        mock_bot.download_file.return_value = b"raw-ogg-bytes"

        from bot.handlers import _route_voice

        _route_voice(msg)

        mock_bot.get_file.assert_called_once_with("voice-file-id")
        mock_bot.download_file.assert_called_once_with("voices/abc.ogg")
        # message.text was set to the transcript
        assert msg.text == "what is RAG"
        mock_route.assert_called_once_with(msg)
        # No error reply
        mock_bot.reply_to.assert_not_called()


def test_route_voice_handles_transcribe_error():
    msg = _make_voice_message(duration=10)
    with (
        patch("bot.handlers.voice_module.is_enabled", return_value=True),
        patch(
            "bot.handlers.voice_module.transcribe",
            side_effect=RuntimeError("Cloudflare 500"),
        ),
        patch("bot.handlers.MAX_VOICE_SECONDS", 30),
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.ta_admin.route") as mock_route,
    ):
        mock_bot.get_file.return_value = MagicMock(file_path="x.ogg")
        mock_bot.download_file.return_value = b"x"

        from bot.handlers import _route_voice

        _route_voice(msg)

        mock_bot.reply_to.assert_called_once()
        reply_text = mock_bot.reply_to.call_args[0][1]
        assert "couldn't transcribe" in reply_text.lower()
        mock_route.assert_not_called()


def test_route_voice_handles_empty_transcript():
    msg = _make_voice_message(duration=10)
    with (
        patch("bot.handlers.voice_module.is_enabled", return_value=True),
        patch("bot.handlers.voice_module.transcribe", return_value=""),
        patch("bot.handlers.MAX_VOICE_SECONDS", 30),
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.ta_admin.route") as mock_route,
    ):
        mock_bot.get_file.return_value = MagicMock(file_path="x.ogg")
        mock_bot.download_file.return_value = b"x"

        from bot.handlers import _route_voice

        _route_voice(msg)

        mock_bot.reply_to.assert_called_once()
        reply_text = mock_bot.reply_to.call_args[0][1]
        assert (
            "couldn't hear" in reply_text.lower() or "no speech" in reply_text.lower()
        )
        mock_route.assert_not_called()


def test_route_voice_no_voice_attr_silently_returns():
    msg = MagicMock()
    msg.voice = None
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.ta_admin.route") as mock_route,
    ):
        from bot.handlers import _route_voice

        _route_voice(msg)

        mock_bot.reply_to.assert_not_called()
        mock_route.assert_not_called()


def test_route_voice_marks_message_for_voice_reply():
    msg = _make_voice_message(duration=10)
    with (
        patch("bot.handlers.voice_module.is_enabled", return_value=True),
        patch("bot.handlers.voice_module.transcribe", return_value="explain RAG"),
        patch("bot.handlers.MAX_VOICE_SECONDS", 30),
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.ta_admin.route") as mock_route,
    ):
        mock_bot.get_file.return_value = MagicMock(file_path="x.ogg")
        mock_bot.download_file.return_value = b"x"

        from bot.handlers import _route_voice

        _route_voice(msg)

        # The flag is what bot.helpers.send_reply checks to route through TTS
        assert msg._reply_as_voice is True
        mock_route.assert_called_once_with(msg)


# ── bot.voice.synthesize (TTS via Cloudflare Aura-1) ──────────────────────


def _ok_mp3_response(payload: bytes = b"\xff\xf3\x60\xc4mp3body") -> MagicMock:
    resp = MagicMock()
    resp.content = payload
    resp.headers = {"content-type": "audio/mpeg"}
    resp.raise_for_status = MagicMock()
    return resp


def test_synthesize_returns_mp3_bytes():
    with (
        patch("bot.voice.CLOUDFLARE_ACCOUNT_ID", "acct"),
        patch("bot.voice.CLOUDFLARE_API_TOKEN", "tok"),
        patch("bot.voice.requests.post", return_value=_ok_mp3_response()),
    ):
        from bot.voice import synthesize

        out = synthesize("hello world")
        assert out.startswith(b"\xff\xf3")  # MPEG ADTS frame sync


def test_synthesize_sends_text_and_speaker():
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _ok_mp3_response()

    with (
        patch("bot.voice.CLOUDFLARE_ACCOUNT_ID", "acct123"),
        patch("bot.voice.CLOUDFLARE_API_TOKEN", "tokABC"),
        patch("bot.voice.VOICE_REPLY_SPEAKER", "asteria"),
        patch("bot.voice.requests.post", side_effect=fake_post),
    ):
        from bot.voice import synthesize

        synthesize("the quick brown fox")

    assert "acct123" in captured["url"]
    assert captured["url"].endswith("@cf/deepgram/aura-1")
    assert captured["json"] == {"text": "the quick brown fox", "speaker": "asteria"}
    assert captured["headers"]["Authorization"] == "Bearer tokABC"


def test_synthesize_speaker_override():
    with (
        patch("bot.voice.CLOUDFLARE_ACCOUNT_ID", "acct"),
        patch("bot.voice.CLOUDFLARE_API_TOKEN", "tok"),
        patch("bot.voice.requests.post", return_value=_ok_mp3_response()) as mock_post,
    ):
        from bot.voice import synthesize

        synthesize("hi", speaker="luna")
        assert mock_post.call_args[1]["json"]["speaker"] == "luna"


def test_synthesize_raises_when_disabled():
    with (
        patch("bot.voice.CLOUDFLARE_ACCOUNT_ID", ""),
        patch("bot.voice.CLOUDFLARE_API_TOKEN", ""),
    ):
        from bot.voice import synthesize
        import pytest

        with pytest.raises(RuntimeError, match="not configured"):
            synthesize("hello")


def test_synthesize_raises_on_unexpected_json_response():
    """Aura returns binary on success; a 200 with JSON is a contract surprise."""
    json_resp = MagicMock()
    json_resp.headers = {"content-type": "application/json"}
    json_resp.json.return_value = {"errors": [{"message": "weird"}]}
    json_resp.raise_for_status = MagicMock()
    with (
        patch("bot.voice.CLOUDFLARE_ACCOUNT_ID", "acct"),
        patch("bot.voice.CLOUDFLARE_API_TOKEN", "tok"),
        patch("bot.voice.requests.post", return_value=json_resp),
    ):
        from bot.voice import synthesize
        import pytest

        with pytest.raises(RuntimeError, match="unexpected JSON"):
            synthesize("hi")


# ── bot.helpers send_reply voice path ─────────────────────────────────────


def _make_chat_message(chat_type="private", message_id=42):
    msg = MagicMock()
    msg.chat.type = chat_type
    msg.chat.id = -100123
    msg.message_id = message_id
    msg._reply_as_voice = True  # explicit True triggers the voice path
    return msg


def test_send_reply_voice_path_synthesizes_and_sends_voice_and_text():
    """Voice mode delivers both: the audio bubble + the text bubble so
    students can hear the answer and read along (and see the sources
    footer)."""
    msg = _make_chat_message(chat_type="private")
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.voice.synthesize", return_value=b"\xff\xf3audio") as mock_synth,
    ):
        from bot.helpers import send_reply

        send_reply(msg, "Hello! This is a short answer.")

        mock_synth.assert_called_once()
        assert mock_synth.call_args[0][0] == "Hello! This is a short answer."
        mock_bot.send_voice.assert_called_once()
        # Text version sent alongside
        mock_bot.send_message.assert_called_once()
        assert mock_bot.send_message.call_args[0][1] == "Hello! This is a short answer."


def test_send_reply_voice_strips_html_and_sources_footer():
    msg = _make_chat_message(chat_type="private")
    reply = (
        "<b>RAG</b> stands for retrieval-augmented generation.\n\n"
        '**Sources:** <a href="https://x">[1] x</a>'
    )
    captured_text = {}

    def fake_synth(t, speaker=None):
        captured_text["t"] = t
        return b"\xff\xf3audio"

    with (
        patch("bot.helpers.bot"),
        patch("bot.voice.synthesize", side_effect=fake_synth),
    ):
        from bot.helpers import send_reply

        send_reply(msg, reply)

    assert "<b>" not in captured_text["t"]
    assert "Sources:" not in captured_text["t"]
    assert "RAG stands for retrieval-augmented generation." in captured_text["t"]


def test_send_reply_voice_falls_back_to_text_when_too_long():
    msg = _make_chat_message(chat_type="private")
    long_reply = "x " * 600  # 1200 chars, over default 1000 cap
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.helpers.VOICE_REPLY_MAX_CHARS", 1000),
        patch("bot.voice.synthesize") as mock_synth,
    ):
        from bot.helpers import send_reply

        send_reply(msg, long_reply)

        mock_synth.assert_not_called()
        mock_bot.send_voice.assert_not_called()
        mock_bot.send_message.assert_called()


def test_send_reply_voice_falls_back_to_text_on_synthesis_failure():
    msg = _make_chat_message(chat_type="private")
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.voice.synthesize", side_effect=RuntimeError("CF 500")),
    ):
        from bot.helpers import send_reply

        send_reply(msg, "Hello!")

        mock_bot.send_voice.assert_not_called()
        mock_bot.send_message.assert_called()


def test_send_reply_voice_falls_back_to_text_on_send_voice_failure():
    msg = _make_chat_message(chat_type="private")
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.voice.synthesize", return_value=b"audio"),
    ):
        mock_bot.send_voice.side_effect = Exception("Telegram rejected")

        from bot.helpers import send_reply

        send_reply(msg, "Hello!")

        mock_bot.send_voice.assert_called_once()
        mock_bot.send_message.assert_called()


def test_send_reply_voice_in_group_replies_to_message():
    msg = _make_chat_message(chat_type="supergroup", message_id=7)
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.voice.synthesize", return_value=b"audio"),
    ):
        from bot.helpers import send_reply

        send_reply(msg, "Hi")

        kwargs = mock_bot.send_voice.call_args[1]
        assert kwargs.get("reply_to_message_id") == 7


def test_send_reply_text_path_unaffected_when_flag_not_set():
    """Sanity: MagicMock auto-attrs are truthy, but only literal True triggers voice."""
    msg = MagicMock()
    msg.chat.type = "private"
    msg.message_id = 1
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.voice.synthesize") as mock_synth,
    ):
        from bot.helpers import send_reply

        send_reply(msg, "plain text")

        mock_synth.assert_not_called()
        mock_bot.send_message.assert_called_once()


# ── _strip_for_speech ─────────────────────────────────────────────────────


def test_strip_for_speech_drops_sources_footer():
    from bot.helpers import _strip_for_speech

    text = "Answer.\n\n**Sources:** [1] foo [2] bar"
    assert _strip_for_speech(text) == "Answer."


def test_strip_for_speech_drops_html_tags():
    from bot.helpers import _strip_for_speech

    text = "<b>Bold</b> and <i>italic</i>"
    assert _strip_for_speech(text) == "Bold and italic"


def test_strip_for_speech_unescapes_html_entities():
    from bot.helpers import _strip_for_speech

    text = "Tom &amp; Jerry &lt;3"
    assert _strip_for_speech(text) == "Tom & Jerry <3"


def test_strip_for_speech_drops_emoji():
    from bot.helpers import _strip_for_speech

    cases = [
        ("✅ Done.", "Done."),
        ("Hello 👋 world", "Hello world"),
        ("🎉🎉 Party 🎊", "Party"),
        ("Result: ⚡ fast", "Result: fast"),
        ("Star ⭐ rating", "Star rating"),
        ("Plain text", "Plain text"),  # no emoji unchanged
    ]
    for raw, expected in cases:
        assert _strip_for_speech(raw) == expected, f"input={raw!r}"


def test_strip_for_speech_drops_zwj_sequences():
    """Multi-codepoint emoji (e.g. family, flags, skin-tone) — no fragments survive."""
    from bot.helpers import _strip_for_speech

    # Family ZWJ sequence
    family = "Hello \U0001f468‍\U0001f469‍\U0001f466 friends"
    assert _strip_for_speech(family) == "Hello friends"
    # Flag (regional indicators)
    flag = "Country \U0001f1fa\U0001f1f8 hello"
    assert _strip_for_speech(flag) == "Country hello"
