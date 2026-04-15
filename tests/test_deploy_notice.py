"""Deploy-notice one-shot DM to the permanent admin."""
import os
from unittest.mock import MagicMock, patch


def _reset_module_flag():
    import bot.deploy_notice as d
    d._DONE_THIS_PROCESS = False


def test_notify_once_does_nothing_without_sha():
    _reset_module_flag()
    with patch.dict(os.environ, {"VERCEL_GIT_COMMIT_SHA": ""}, clear=False), \
         patch("bot.deploy_notice.bot") as b, \
         patch("bot.deploy_notice.redis") as r:
        from bot.deploy_notice import notify_once
        notify_once()
        b.send_message.assert_not_called()
        r.set.assert_not_called()


def test_notify_once_sends_dm_first_time():
    _reset_module_flag()
    r = MagicMock()
    r.set.return_value = True  # claimed
    with patch.dict(os.environ, {"VERCEL_GIT_COMMIT_SHA": "abcdef1234567"}, clear=False), \
         patch("bot.deploy_notice.bot") as b, \
         patch("bot.deploy_notice.redis", r), \
         patch("bot.deploy_notice.get_user_chat", return_value="9001"):
        from bot.deploy_notice import notify_once
        notify_once()
        b.send_message.assert_called_once()
        args = b.send_message.call_args.args
        # Format: "🚀 {env} deploy live — {short}" — exactly, no extras
        assert args[1] == "🚀 local deploy live — abcdef1"


def test_notify_once_dedupes_via_redis_nx():
    _reset_module_flag()
    r = MagicMock()
    r.set.return_value = None  # someone else already claimed
    with patch.dict(os.environ, {"VERCEL_GIT_COMMIT_SHA": "abcdef"}, clear=False), \
         patch("bot.deploy_notice.bot") as b, \
         patch("bot.deploy_notice.redis", r), \
         patch("bot.deploy_notice.get_user_chat", return_value="9001"):
        from bot.deploy_notice import notify_once
        notify_once()
        b.send_message.assert_not_called()


def test_notify_once_skips_when_no_admin_chat_known():
    _reset_module_flag()
    r = MagicMock()
    r.set.return_value = True
    with patch.dict(os.environ, {"VERCEL_GIT_COMMIT_SHA": "abc"}, clear=False), \
         patch("bot.deploy_notice.bot") as b, \
         patch("bot.deploy_notice.redis", r), \
         patch("bot.deploy_notice.get_user_chat", return_value=None):
        from bot.deploy_notice import notify_once
        notify_once()
        b.send_message.assert_not_called()


def test_notify_once_second_call_in_same_process_is_noop():
    _reset_module_flag()
    r = MagicMock()
    r.set.return_value = True
    with patch.dict(os.environ, {"VERCEL_GIT_COMMIT_SHA": "abc"}, clear=False), \
         patch("bot.deploy_notice.bot") as b, \
         patch("bot.deploy_notice.redis", r), \
         patch("bot.deploy_notice.get_user_chat", return_value="9001"):
        from bot.deploy_notice import notify_once
        notify_once()
        notify_once()
        assert b.send_message.call_count == 1
