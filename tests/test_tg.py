"""tg.send_message auto-splits overlong output.

Regression: list commands (/doc list, /git list, /stats) send one
"\n".join(lines) message; once many docs/repos are indexed it exceeds
Telegram's 4096-char limit and is rejected with 400 "message is too long".
"""

from unittest.mock import MagicMock, patch

from bot.config import MAX_MSG_LEN


def _recording_bot():
    sent = []

    def fake_send(cid, txt, **k):
        sent.append(txt)
        return MagicMock(message_id=len(sent))

    fake = MagicMock()
    fake.send_message.side_effect = fake_send
    return fake, sent


def test_send_message_single_for_short_text():
    import bot.ta.tg as tg

    fake, sent = _recording_bot()
    with patch.object(tg, "bot", fake):
        tg.reset_errors()
        mid = tg.send_message(123, "short message", parse_mode="HTML")
    assert sent == ["short message"]
    assert mid == 1
    assert tg.errors() == []


def test_send_message_splits_overlong_text_on_line_boundaries():
    import bot.ta.tg as tg

    long = "\n".join(f"• line {i} " + "x" * 80 for i in range(120))
    assert len(long) > MAX_MSG_LEN  # would 400 unsplit

    fake, sent = _recording_bot()
    with patch.object(tg, "bot", fake):
        tg.reset_errors()
        mid = tg.send_message(123, long, parse_mode="HTML")

    assert len(sent) >= 2  # actually split
    assert all(len(chunk) <= MAX_MSG_LEN for chunk in sent)  # every chunk fits
    assert mid == len(sent)  # returns the LAST chunk's id
    assert tg.errors() == []  # nothing rejected
    # no content lost across the split (line-boundary join)
    assert sum(c.count("• line ") for c in sent) == 120
