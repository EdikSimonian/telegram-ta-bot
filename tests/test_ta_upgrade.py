"""Self-upgrade routine client + /upgrade command.

`bot.ta.upgrade.fire()` is the thin HTTP client; `_cmd_upgrade` is the
Telegram gate (instructor-only) on top of it.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests


# ── fire() ────────────────────────────────────────────────────────────────
def test_fire_requires_config():
    from bot.ta import upgrade
    with patch("bot.ta.upgrade.CLAUDE_ROUTINE_ID", ""), \
         patch("bot.ta.upgrade.CLAUDE_ROUTINE_TOKEN", ""):
        with pytest.raises(upgrade.UpgradeError, match="not set"):
            upgrade.fire("do a thing")


def test_fire_rejects_empty_instructions():
    from bot.ta import upgrade
    with patch("bot.ta.upgrade.CLAUDE_ROUTINE_ID", "rt_abc"), \
         patch("bot.ta.upgrade.CLAUDE_ROUTINE_TOKEN", "sk-ant-oat01-xyz"):
        with pytest.raises(upgrade.UpgradeError, match="empty"):
            upgrade.fire("   ")


def test_fire_rejects_too_long_instructions():
    from bot.ta import upgrade
    with patch("bot.ta.upgrade.CLAUDE_ROUTINE_ID", "rt_abc"), \
         patch("bot.ta.upgrade.CLAUDE_ROUTINE_TOKEN", "sk-ant-oat01-xyz"):
        with pytest.raises(upgrade.UpgradeError, match="too long"):
            upgrade.fire("x" * 65_537)


def test_fire_posts_expected_payload_and_returns_session():
    from bot.ta import upgrade
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "type": "routine_fire",
        "claude_code_session_id":  "session_01HABC",
        "claude_code_session_url": "https://claude.ai/code/session_01HABC",
    }
    with patch("bot.ta.upgrade.CLAUDE_ROUTINE_ID", "rt_abc"), \
         patch("bot.ta.upgrade.CLAUDE_ROUTINE_TOKEN", "sk-ant-oat01-xyz"), \
         patch("bot.ta.upgrade.requests.post", return_value=resp) as post:
        result = upgrade.fire("add a /ping command")

    assert result.session_id  == "session_01HABC"
    assert result.session_url == "https://claude.ai/code/session_01HABC"
    # URL carries the routine id.
    url = post.call_args.args[0]
    assert "rt_abc" in url and url.endswith("/fire")
    # Bearer token + beta header present.
    headers = post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer sk-ant-oat01-xyz"
    assert "anthropic-beta" in headers
    # Instructions passed verbatim as `text`.
    assert post.call_args.kwargs["json"] == {"text": "add a /ping command"}


def test_fire_surfaces_api_error_message():
    from bot.ta import upgrade
    resp = MagicMock()
    resp.status_code = 403
    resp.json.return_value = {"error": {"message": "invalid routine token"}}
    with patch("bot.ta.upgrade.CLAUDE_ROUTINE_ID", "rt_abc"), \
         patch("bot.ta.upgrade.CLAUDE_ROUTINE_TOKEN", "sk-ant-oat01-xyz"), \
         patch("bot.ta.upgrade.requests.post", return_value=resp):
        with pytest.raises(upgrade.UpgradeError, match="403.*invalid routine token"):
            upgrade.fire("do a thing")


def test_fire_wraps_network_errors():
    from bot.ta import upgrade
    with patch("bot.ta.upgrade.CLAUDE_ROUTINE_ID", "rt_abc"), \
         patch("bot.ta.upgrade.CLAUDE_ROUTINE_TOKEN", "sk-ant-oat01-xyz"), \
         patch("bot.ta.upgrade.requests.post",
               side_effect=requests.ConnectionError("boom")):
        with pytest.raises(upgrade.UpgradeError, match="Network error"):
            upgrade.fire("do a thing")


def test_fire_rejects_response_missing_session_fields():
    from bot.ta import upgrade
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"type": "routine_fire"}  # no session_id/url
    with patch("bot.ta.upgrade.CLAUDE_ROUTINE_ID", "rt_abc"), \
         patch("bot.ta.upgrade.CLAUDE_ROUTINE_TOKEN", "sk-ant-oat01-xyz"), \
         patch("bot.ta.upgrade.requests.post", return_value=resp):
        with pytest.raises(upgrade.UpgradeError, match="missing session fields"):
            upgrade.fire("do a thing")


# ── /upgrade command ──────────────────────────────────────────────────────
def _prepared(*, is_instructor=True, command_args="add a /ping command"):
    p = MagicMock()
    p.user_id = 42
    p.username = "ediksimonian" if is_instructor else "randomadmin"
    p.chat_id = 42
    p.command = "upgrade"
    p.command_args = command_args
    p.group_key = "-100123"
    p.is_dm = True
    p.is_instructor = is_instructor
    return p


def test_upgrade_rejects_non_instructor_admin():
    from bot.ta.commands import _cmd_upgrade
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.upgrade_mod.fire") as fire:
        _cmd_upgrade(_prepared(is_instructor=False))
        assert fire.call_count == 0
        text = sm.call_args.args[1]
        assert "instructor" in text.lower()


def test_upgrade_shows_usage_when_no_args():
    from bot.ta.commands import _cmd_upgrade
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.upgrade_mod.fire") as fire:
        _cmd_upgrade(_prepared(command_args=""))
        assert fire.call_count == 0
        assert "Usage" in sm.call_args.args[1]


def test_upgrade_fires_routine_and_replies_with_session_link():
    from bot.ta import upgrade as upgrade_mod
    from bot.ta.commands import _cmd_upgrade
    fake = upgrade_mod.FireResult(
        session_id="session_01H", session_url="https://claude.ai/code/session_01H",
    )
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.upgrade_mod.fire", return_value=fake) as fire:
        _cmd_upgrade(_prepared(command_args="add a /ping command"))
        fire.assert_called_once_with("add a /ping command")
        text = sm.call_args.args[1]
        assert "triggered" in text.lower()
        assert "session_01H" in text
        assert "https://claude.ai/code/session_01H" in text


def test_upgrade_surfaces_fire_error_to_admin():
    from bot.ta import upgrade as upgrade_mod
    from bot.ta.commands import _cmd_upgrade
    with patch("bot.ta.commands.send_message") as sm, \
         patch("bot.ta.commands.upgrade_mod.fire",
               side_effect=upgrade_mod.UpgradeError("routine offline")):
        _cmd_upgrade(_prepared())
        text = sm.call_args.args[1]
        assert "routine offline" in text
        assert "❌" in text
