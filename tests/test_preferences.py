from unittest.mock import patch


# ── get_provider ──────────────────────────────────────────────────────────────

def test_get_provider_default_when_unset():
    with patch("bot.preferences.redis") as mock_redis:
        mock_redis.get.return_value = None
        from bot.preferences import get_provider
        assert get_provider(123) == "openai"


def test_get_provider_returns_saved_openai():
    with patch("bot.preferences.redis") as mock_redis:
        mock_redis.get.return_value = "openai"
        from bot.preferences import get_provider
        assert get_provider(123) == "openai"


def test_get_provider_returns_saved_hf_when_configured():
    with patch("bot.preferences.redis") as mock_redis, \
         patch("bot.preferences.HF_SPACE_ID", "fake/space"):
        mock_redis.get.return_value = "hf"
        from bot.preferences import get_provider
        assert get_provider(123) == "hf"


def test_get_provider_falls_back_when_hf_not_configured():
    with patch("bot.preferences.redis") as mock_redis, \
         patch("bot.preferences.HF_SPACE_ID", ""):
        mock_redis.get.return_value = "hf"
        from bot.preferences import get_provider
        assert get_provider(123) == "openai"


def test_get_provider_returns_saved_armgpt_when_configured():
    with patch("bot.preferences.redis") as mock_redis, \
         patch("bot.preferences.ARMGPT_BASE_URL", "https://fake.modal.run/v1"), \
         patch("bot.preferences.ARMGPT_API_KEY", "fake_key"):
        mock_redis.get.return_value = "armgpt"
        from bot.preferences import get_provider
        assert get_provider(123) == "armgpt"


def test_get_provider_falls_back_when_armgpt_not_configured():
    with patch("bot.preferences.redis") as mock_redis, \
         patch("bot.preferences.ARMGPT_BASE_URL", ""), \
         patch("bot.preferences.ARMGPT_API_KEY", ""):
        mock_redis.get.return_value = "armgpt"
        from bot.preferences import get_provider
        assert get_provider(123) == "openai"


def test_get_provider_falls_back_when_only_url_set():
    with patch("bot.preferences.redis") as mock_redis, \
         patch("bot.preferences.ARMGPT_BASE_URL", "https://fake.modal.run/v1"), \
         patch("bot.preferences.ARMGPT_API_KEY", ""):
        mock_redis.get.return_value = "armgpt"
        from bot.preferences import get_provider
        assert get_provider(123) == "openai"


def test_get_provider_ignores_invalid_value():
    with patch("bot.preferences.redis") as mock_redis:
        mock_redis.get.return_value = "garbage"
        from bot.preferences import get_provider
        assert get_provider(123) == "openai"


def test_get_provider_redis_down_returns_default():
    with patch("bot.preferences.redis") as mock_redis:
        mock_redis.get.side_effect = Exception("connection refused")
        from bot.preferences import get_provider
        assert get_provider(123) == "openai"


# ── set_provider ──────────────────────────────────────────────────────────────

def test_set_provider_openai_always_works():
    with patch("bot.preferences.redis") as mock_redis:
        from bot.preferences import set_provider
        assert set_provider(123, "openai") is True
        mock_redis.set.assert_called_once_with("provider:123", "openai")


def test_set_provider_hf_when_configured():
    with patch("bot.preferences.redis") as mock_redis, \
         patch("bot.preferences.HF_SPACE_ID", "fake/space"):
        from bot.preferences import set_provider
        assert set_provider(123, "hf") is True
        mock_redis.set.assert_called_once_with("provider:123", "hf")


def test_set_provider_hf_rejected_when_not_configured():
    with patch("bot.preferences.redis") as mock_redis, \
         patch("bot.preferences.HF_SPACE_ID", ""):
        from bot.preferences import set_provider
        assert set_provider(123, "hf") is False
        mock_redis.set.assert_not_called()


def test_set_provider_armgpt_when_configured():
    with patch("bot.preferences.redis") as mock_redis, \
         patch("bot.preferences.ARMGPT_BASE_URL", "https://fake/v1"), \
         patch("bot.preferences.ARMGPT_API_KEY", "key"):
        from bot.preferences import set_provider
        assert set_provider(123, "armgpt") is True
        mock_redis.set.assert_called_once_with("provider:123", "armgpt")


def test_set_provider_armgpt_rejected_when_not_configured():
    with patch("bot.preferences.redis") as mock_redis, \
         patch("bot.preferences.ARMGPT_BASE_URL", ""), \
         patch("bot.preferences.ARMGPT_API_KEY", ""):
        from bot.preferences import set_provider
        assert set_provider(123, "armgpt") is False
        mock_redis.set.assert_not_called()


def test_set_provider_rejects_invalid():
    with patch("bot.preferences.redis") as mock_redis:
        from bot.preferences import set_provider
        assert set_provider(123, "bogus") is False
        mock_redis.set.assert_not_called()


def test_set_provider_redis_down_returns_false():
    with patch("bot.preferences.redis") as mock_redis:
        mock_redis.set.side_effect = Exception("connection refused")
        from bot.preferences import set_provider
        assert set_provider(123, "openai") is False


# ── enabled_providers ─────────────────────────────────────────────────────────

def test_enabled_providers_only_openai_by_default():
    with patch("bot.preferences.HF_SPACE_ID", ""), \
         patch("bot.preferences.ARMGPT_BASE_URL", ""), \
         patch("bot.preferences.ARMGPT_API_KEY", ""):
        from bot.preferences import enabled_providers
        assert enabled_providers() == ("openai",)


def test_enabled_providers_includes_hf_when_set():
    with patch("bot.preferences.HF_SPACE_ID", "fake/space"), \
         patch("bot.preferences.ARMGPT_BASE_URL", ""), \
         patch("bot.preferences.ARMGPT_API_KEY", ""):
        from bot.preferences import enabled_providers
        assert enabled_providers() == ("openai", "hf")


def test_enabled_providers_includes_armgpt_when_both_vars_set():
    with patch("bot.preferences.HF_SPACE_ID", ""), \
         patch("bot.preferences.ARMGPT_BASE_URL", "https://fake/v1"), \
         patch("bot.preferences.ARMGPT_API_KEY", "key"):
        from bot.preferences import enabled_providers
        assert enabled_providers() == ("openai", "armgpt")


def test_enabled_providers_all_three():
    with patch("bot.preferences.HF_SPACE_ID", "fake/space"), \
         patch("bot.preferences.ARMGPT_BASE_URL", "https://fake/v1"), \
         patch("bot.preferences.ARMGPT_API_KEY", "key"):
        from bot.preferences import enabled_providers
        assert enabled_providers() == ("openai", "hf", "armgpt")
