from unittest.mock import patch, MagicMock


# ── _call_openai retry logic ──────────────────────────────────────────────────

def test_call_openai_retries_on_failure():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello"
    with patch("bot.providers.ai") as mock_ai, \
         patch("bot.providers.time.sleep") as mock_sleep:
        mock_ai.chat.completions.create.side_effect = [
            Exception("network error"),
            mock_response,
        ]
        from bot.providers import _call_openai
        result = _call_openai([{"role": "user", "content": "hi"}])
        assert result == "hello"
        assert mock_ai.chat.completions.create.call_count == 2
        mock_sleep.assert_called_once_with(1)


def test_call_openai_raises_after_max_retries():
    with patch("bot.providers.ai") as mock_ai, \
         patch("bot.providers.time.sleep"):
        mock_ai.chat.completions.create.side_effect = Exception("persistent")
        from bot.providers import _call_openai
        try:
            _call_openai([{"role": "user", "content": "hi"}], retries=3)
            assert False, "Should have raised"
        except Exception as e:
            assert str(e) == "persistent"
        assert mock_ai.chat.completions.create.call_count == 3


def test_call_openai_succeeds_first_try():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "ok"
    with patch("bot.providers.ai") as mock_ai, \
         patch("bot.providers.time.sleep") as mock_sleep:
        mock_ai.chat.completions.create.return_value = mock_response
        from bot.providers import _call_openai
        assert _call_openai([{"role": "user", "content": "hi"}]) == "ok"
        mock_sleep.assert_not_called()


# ── _flatten_messages ─────────────────────────────────────────────────────────

def test_flatten_messages_skips_system():
    from bot.providers import _flatten_messages
    result = _flatten_messages([
        {"role": "system", "content": "you are a bot"},
        {"role": "user", "content": "hi"},
    ])
    assert "system" not in result.lower() or "bot" not in result
    assert "User: hi" in result
    assert result.endswith("Assistant:")


def test_flatten_messages_keeps_last_n_turns():
    from bot.providers import _flatten_messages
    messages = []
    for i in range(10):
        messages.append({"role": "user", "content": f"u{i}"})
        messages.append({"role": "assistant", "content": f"a{i}"})
    result = _flatten_messages(messages, turns=2)
    # last 2 turns = last 4 messages: u8, a8, u9, a9
    assert "u8" in result and "a8" in result and "u9" in result and "a9" in result
    assert "u7" not in result


# ── _strip_html ───────────────────────────────────────────────────────────────

def test_strip_html_removes_tags():
    from bot.providers import _strip_html
    assert _strip_html("<div>hello <b>world</b></div>") == "hello world"


def test_strip_html_preserves_text_without_tags():
    from bot.providers import _strip_html
    assert _strip_html("plain text") == "plain text"


# ── _call_hf ──────────────────────────────────────────────────────────────────

def test_call_hf_calls_gradio_client():
    mock_client = MagicMock()
    mock_client.predict.return_value = ("<p>Armenian response</p>", "done")
    with patch("bot.providers.HF_SPACE_ID", "edisimon/armgpt-demo"):
        import gradio_client
        with patch.object(gradio_client, "Client", return_value=mock_client) as mock_cls:
            from bot.providers import _call_hf
            result = _call_hf([{"role": "user", "content": "Բարև"}])
            mock_cls.assert_called_once_with("edisimon/armgpt-demo")
            mock_client.predict.assert_called_once()
            assert "Armenian response" in result


def test_call_hf_handles_plain_string_result():
    mock_client = MagicMock()
    mock_client.predict.return_value = "just text"
    with patch("bot.providers.HF_SPACE_ID", "fake/space"):
        import gradio_client
        with patch.object(gradio_client, "Client", return_value=mock_client):
            from bot.providers import _call_hf
            assert _call_hf([{"role": "user", "content": "hi"}]) == "just text"


def test_call_hf_no_retry_on_failure():
    mock_client = MagicMock()
    mock_client.predict.side_effect = Exception("HF down")
    with patch("bot.providers.HF_SPACE_ID", "fake/space"):
        import gradio_client
        with patch.object(gradio_client, "Client", return_value=mock_client):
            from bot.providers import _call_hf
            try:
                _call_hf([{"role": "user", "content": "hi"}])
                assert False, "Should have raised"
            except Exception as e:
                assert "HF down" in str(e)
            # Only one call — no retry
            assert mock_client.predict.call_count == 1


# ── generate dispatch ─────────────────────────────────────────────────────────

def test_generate_dispatches_to_openai():
    with patch("bot.providers.get_provider", return_value="openai"), \
         patch("bot.providers._call_openai", return_value="openai reply") as mock_openai, \
         patch("bot.providers._call_hf") as mock_hf:
        from bot.providers import generate
        assert generate(123, [{"role": "user", "content": "hi"}]) == "openai reply"
        mock_openai.assert_called_once()
        mock_hf.assert_not_called()


def test_generate_dispatches_to_hf():
    with patch("bot.providers.get_provider", return_value="hf"), \
         patch("bot.providers._call_openai") as mock_openai, \
         patch("bot.providers._call_hf", return_value="hf reply") as mock_hf:
        from bot.providers import generate
        assert generate(123, [{"role": "user", "content": "hi"}]) == "hf reply"
        mock_hf.assert_called_once()
        mock_openai.assert_not_called()
