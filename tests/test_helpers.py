from unittest.mock import patch, MagicMock


def make_message(chat_type="private", reply_from_id=None, text="hello", message_id=7):
    message = MagicMock()
    message.chat.type = chat_type
    message.message_id = message_id
    message.text = text
    message.reply_to_message = None
    if reply_from_id:
        message.reply_to_message = MagicMock()
        message.reply_to_message.from_user.id = reply_from_id
    return message


# ── send_reply ─────────────────────────────────────────────────────────────────


def test_send_reply_dm_no_reply_to():
    with patch("bot.helpers.bot") as mock_bot:
        from bot.helpers import send_reply

        msg = make_message(chat_type="private")
        send_reply(msg, "Hello!")
        call = mock_bot.send_message.call_args
        assert "reply_to_message_id" not in call.kwargs


def test_send_reply_group_first_chunk_replies():
    with patch("bot.helpers.bot") as mock_bot:
        from bot.helpers import send_reply

        msg = make_message(chat_type="supergroup", message_id=77)
        send_reply(msg, "Hello!")
        call = mock_bot.send_message.call_args
        assert call.kwargs.get("reply_to_message_id") == 77


def test_send_reply_group_subsequent_chunks_dont_reply():
    with patch("bot.helpers.bot") as mock_bot, patch("bot.helpers.MAX_MSG_LEN", 10):
        from bot.helpers import send_reply

        msg = make_message(chat_type="supergroup", message_id=77)
        send_reply(msg, "A" * 25)
        calls = mock_bot.send_message.call_args_list
        assert len(calls) == 3
        # First chunk → replies
        assert calls[0].kwargs.get("reply_to_message_id") == 77
        # Subsequent chunks → no reply_to
        assert "reply_to_message_id" not in calls[1].kwargs
        assert "reply_to_message_id" not in calls[2].kwargs


def test_send_reply_splits_long_text():
    with patch("bot.helpers.bot") as mock_bot, patch("bot.helpers.MAX_MSG_LEN", 10):
        from bot.helpers import send_reply

        msg = make_message()
        send_reply(msg, "A" * 25)
        assert mock_bot.send_message.call_count == 3


# ── should_respond ─────────────────────────────────────────────────────────────


def test_should_respond_private_chat():
    from bot.helpers import should_respond

    assert should_respond(make_message(chat_type="private")) is True


def test_should_respond_group_always_true():
    """should_respond now returns True unconditionally — bot replies to every message."""
    from bot.helpers import should_respond

    assert should_respond(make_message(chat_type="group", text="just chatting")) is True
    assert should_respond(make_message(chat_type="group", text="hey @testbot")) is True
    assert should_respond(make_message(chat_type="group", reply_from_id=99)) is True


# ── keep_typing ────────────────────────────────────────────────────────────────


def test_keep_typing_sends_typing_action():
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.helpers.TYPING_REFRESH_SECONDS", 0.05),
    ):
        from bot.helpers import keep_typing

        with keep_typing(123):
            pass  # exits immediately
        # At least one typing action was sent before the context exited
        typing_calls = [
            c
            for c in mock_bot.send_chat_action.call_args_list
            if c[0] == (123, "typing")
        ]
        assert len(typing_calls) >= 1


def test_keep_typing_refreshes_while_block_runs():
    import time

    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.helpers.TYPING_REFRESH_SECONDS", 0.05),
    ):
        from bot.helpers import keep_typing

        with keep_typing(123):
            time.sleep(0.2)  # wait long enough for multiple refreshes
        typing_calls = [
            c
            for c in mock_bot.send_chat_action.call_args_list
            if c[0] == (123, "typing")
        ]
        assert len(typing_calls) >= 2


def test_keep_typing_stops_thread_on_exit():
    import time

    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.helpers.TYPING_REFRESH_SECONDS", 0.05),
    ):
        from bot.helpers import keep_typing

        with keep_typing(123):
            pass
        count_at_exit = mock_bot.send_chat_action.call_count
        time.sleep(0.15)
        # No further calls after the context exits
        assert mock_bot.send_chat_action.call_count == count_at_exit


def test_keep_typing_swallows_errors():
    """A failing typing call should not crash the generation path."""
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.helpers.TYPING_REFRESH_SECONDS", 0.05),
    ):
        mock_bot.send_chat_action.side_effect = Exception("Telegram down")
        from bot.helpers import keep_typing

        # Should not raise
        with keep_typing(123):
            pass


# ── stream_reply ───────────────────────────────────────────────────────────


def _stream(mock_bot, chunks, sent_message_id=99, chat_type="supergroup"):
    """Drive stream_reply with a factory that emits ``chunks`` in order."""
    from bot.helpers import stream_reply

    sent = MagicMock()
    sent.message_id = sent_message_id
    mock_bot.send_message.return_value = sent

    def factory(on_chunk):
        result = None
        for c in chunks:
            result = c
            on_chunk(c)
        return result

    return stream_reply(make_message(chat_type=chat_type), factory)


# Groups use the edit-based transport (drafts are DM-only).


def test_stream_reply_group_partials_carry_cursor_final_strips_it():
    """In-progress partials end with the streaming cursor (Hermes-style);
    the forced final edit delivers the clean text without it."""
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.ta.tg.edit_message") as mock_edit,
        patch("bot.helpers.time") as mock_time,
    ):
        # Monotonic clock far apart so every edit passes the throttle.
        mock_time.monotonic.side_effect = [10.0, 20.0, 30.0]
        result = _stream(mock_bot, ["Hello", "Hello world", "Hello world!"])

        # Initial send is the first partial + cursor.
        first_text = mock_bot.send_message.call_args_list[0].args[1]
        assert first_text == "Hello …"

        # Mid-stream edits carry the cursor.
        mid_texts = [c.args[2] for c in mock_edit.call_args_list[:-1]]
        assert all(t.endswith(" …") for t in mid_texts)

        # The last edit is the forced final — clean text, no cursor.
        final_text = mock_edit.call_args_list[-1].args[2]
        assert final_text == "Hello world!"
        assert result == "Hello world!"


def test_stream_reply_group_final_edit_fires_even_without_new_text():
    """Even if the last throttled edit already showed the full text, the
    final edit must still fire to strip the cursor."""
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.ta.tg.edit_message") as mock_edit,
        patch("bot.helpers.time") as mock_time,
    ):
        mock_time.monotonic.side_effect = [10.0, 20.0]
        _stream(mock_bot, ["Answer", "Answer"])

        final_text = mock_edit.call_args_list[-1].args[2]
        assert final_text == "Answer"


def test_stream_reply_group_cursored_partial_respects_telegram_limit():
    """Neither the cursor nor a part marker may push a chunk past
    Telegram's hard limit."""
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.ta.tg.edit_message"),
        patch("bot.helpers.MAX_MSG_LEN", 40),
    ):
        _stream(mock_bot, ["x" * 100])

        first_text = mock_bot.send_message.call_args_list[0].args[1]
        assert first_text.endswith(" …")
        assert len(first_text) <= 40


def test_stream_reply_group_suppression_deletes_temp_message():
    """on_chunk(None) (guardrail suppression) deletes the temp message and
    stream_reply returns None."""
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.ta.tg.edit_message"),
        patch("bot.ta.tg.delete_message") as mock_delete,
    ):
        result = _stream(mock_bot, ["partial", None])
        assert result is None
        mock_delete.assert_called_once()


def test_stream_reply_group_never_uses_drafts():
    """sendMessageDraft is private-chat-only — groups must not call it."""
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.ta.tg.edit_message"),
    ):
        _stream(mock_bot, ["Hello"])
        mock_bot.send_message_draft.assert_not_called()


# DMs use Telegram's native draft streaming (animated client-side).


def test_stream_reply_dm_streams_via_drafts_then_sends_final():
    """DM partials go out as sendMessageDraft frames with a stable draft_id
    (same id across frames = client animates); the final text is a regular
    sendMessage with no cursor."""
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.ta.tg.edit_message") as mock_edit,
        patch("bot.helpers.time") as mock_time,
    ):
        mock_time.monotonic.side_effect = [10.0, 20.0, 30.0]
        mock_bot.send_message_draft.return_value = True
        result = _stream(mock_bot, ["Hello", "Hello world!"], chat_type="private")

        # All partials went out as draft frames, same draft_id throughout.
        draft_calls = mock_bot.send_message_draft.call_args_list
        assert [c.args[2] for c in draft_calls] == ["Hello", "Hello world!"]
        assert len({c.args[1] for c in draft_calls}) == 1
        assert all(not c.args[2].endswith("…") for c in draft_calls)

        # Exactly one real message: the clean final text. No edits.
        mock_bot.send_message.assert_called_once()
        assert mock_bot.send_message.call_args.args[1] == "Hello world!"
        mock_edit.assert_not_called()
        assert result == "Hello world!"


def test_stream_reply_dm_draft_failure_falls_back_to_edit_transport():
    """First draft failure permanently disables drafts for the response;
    the remaining chunks flow through the edit-based path with cursor."""
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.ta.tg.edit_message") as mock_edit,
        patch("bot.helpers.time") as mock_time,
    ):
        mock_time.monotonic.side_effect = [10.0, 20.0, 30.0]
        mock_bot.send_message_draft.side_effect = Exception("drafts down")
        result = _stream(mock_bot, ["Hello", "Hello world!"], chat_type="private")

        # Draft attempted once, then abandoned for the whole response.
        mock_bot.send_message_draft.assert_called_once()

        # Fallback: cursored initial send, forced clean final edit.
        first_text = mock_bot.send_message.call_args_list[0].args[1]
        assert first_text == "Hello world! …"
        final_text = mock_edit.call_args_list[-1].args[2]
        assert final_text == "Hello world!"
        assert result == "Hello world!"


def test_stream_reply_dm_suppression_with_drafts_returns_none():
    """Suppression in draft mode has no temp message to delete and must
    not send a final message."""
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.ta.tg.delete_message") as mock_delete,
    ):
        mock_bot.send_message_draft.return_value = True
        result = _stream(mock_bot, ["partial", None], chat_type="private")
        assert result is None
        mock_delete.assert_not_called()
        mock_bot.send_message.assert_not_called()


def test_stream_reply_dm_overflow_flushes_heads_then_reconciles_markers():
    """Once the streamed text overflows one message, completed head chunks
    are posted as real messages immediately (so part 1 exists in the chat
    before part 2 animates in the draft bubble). At finalize the flushed
    heads are edited to carry (i/n) part markers and the tail is sent."""
    text = "\n".join(f"line{i:02}xxxxxxxxxxxxxxxxxxxx" for i in range(4))
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.ta.tg.edit_message") as mock_edit,
        patch("bot.helpers.MAX_MSG_LEN", 40),
    ):
        mock_bot.send_message_draft.return_value = True
        sent = MagicMock()
        sent.message_id = 99
        mock_bot.send_message.return_value = sent
        _stream(mock_bot, [text], chat_type="private")

        lines = text.split("\n")
        sends = [c.args[1] for c in mock_bot.send_message.call_args_list]
        n = len(lines)

        # Head chunks flushed mid-stream, unmarked, in order.
        assert sends[:-1] == lines[:-1]
        # Tail sent at finalize with its marker.
        assert sends[-1] == f"({n}/{n}) {lines[-1]}"
        # Flushed heads edited to carry their markers.
        edited = [c.args[2] for c in mock_edit.call_args_list]
        assert edited == [f"({i}/{n}) {line}" for i, line in enumerate(lines[:-1], 1)]
        # Nothing exceeds the Telegram cap.
        assert all(len(s) <= 40 for s in sends + edited)


def test_stream_reply_short_answer_gets_no_part_marker():
    """Single-message answers must not grow a (1/1) prefix."""
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.ta.tg.edit_message"),
    ):
        mock_bot.send_message_draft.return_value = True
        _stream(mock_bot, ["short answer"], chat_type="private")

        assert mock_bot.send_message.call_args.args[1] == "short answer"


def test_stream_reply_group_overflow_final_edit_carries_part_marker():
    """Edit-based transport: when the final answer overflows, the edited
    first message gets the (1/n) marker and follow-ups continue it."""
    text = "\n".join(f"line{i:02}xxxxxxxxxxxxxxxxxxxx" for i in range(4))
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.ta.tg.edit_message") as mock_edit,
        patch("bot.helpers.MAX_MSG_LEN", 40),
    ):
        _stream(mock_bot, [text])

        final_text = mock_edit.call_args_list[-1].args[2]
        assert final_text.startswith("(1/")
        # Follow-up sends (after the initial cursored send) carry markers.
        extras = [c.args[1] for c in mock_bot.send_message.call_args_list[1:]]
        assert extras and all(e.split("/")[0].startswith("(") for e in extras)


def test_stream_reply_dm_draft_frames_tail_chunk_past_limit():
    """Once the streamed text outgrows one message, draft frames must show
    the freshest (tail) chunk so the preview keeps animating instead of
    freezing on the head chunk."""
    short = "first line"
    long = "first line\n" + "\n".join(
        f"line{i:02}xxxxxxxxxxxxxxxxxxxx" for i in range(4)
    )
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.ta.tg.edit_message"),
        patch("bot.helpers.MAX_MSG_LEN", 40),
        patch("bot.helpers.time") as mock_time,
    ):
        mock_time.monotonic.side_effect = [10.0, 20.0, 30.0]
        mock_bot.send_message_draft.return_value = True
        _stream(mock_bot, [short, long], chat_type="private")

        calls = mock_bot.send_message_draft.call_args_list
        frames = [c.args[2] for c in calls]
        ids = [c.args[1] for c in calls]
        assert frames[0] == short
        # The live frame is the tail of the overflowing text, not the head.
        assert frames[-1] == long.split("\n")[-1]
        # Part 1's closing frame reuses part 1's draft id; every following
        # segment gets a fresh id so it animates as a new bubble instead
        # of morphing out of the previous part's text.
        assert ids[0] == ids[1]
        assert len(set(ids)) == len(ids) - 1


def test_stream_reply_dm_suppression_after_flush_deletes_flushed_heads():
    """Guardrail suppression after head chunks were flushed must delete
    those already-posted messages."""
    long = "\n".join(f"line{i:02}xxxxxxxxxxxxxxxxxxxx" for i in range(4))
    with (
        patch("bot.helpers.bot") as mock_bot,
        patch("bot.ta.tg.delete_message") as mock_delete,
    ):
        mock_bot.send_message_draft.return_value = True
        with patch("bot.helpers.MAX_MSG_LEN", 40):
            sent = MagicMock()
            sent.message_id = 99
            mock_bot.send_message.return_value = sent
            result = _stream(mock_bot, [long, None], chat_type="private")

        assert result is None
        # Three heads were flushed (4 chunks, tail stays in the draft).
        assert mock_delete.call_count == 3
