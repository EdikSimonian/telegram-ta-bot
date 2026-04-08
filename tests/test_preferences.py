from unittest.mock import patch


def test_get_provider_default_when_unset():
    with patch("bot.preferences.redis") as mock_redis:
        mock_redis.get.return_value = None
        from bot.preferences import get_provider
        assert get_provider(123) == "openai"


def test_get_provider_returns_saved_openai():
    with patch("bot.preferences.redis") as mock_redis, \
         patch("bot.preferences.HF_SPACE_ID", "fake/space"):
        mock_redis.get.return_value = "openai"
        from bot.preferences import get_provider
        assert get_provider(123) == "openai"


def test_get_provider_returns_saved_hf_when_configured():
    with patch("bot.preferences.redis") as mock_redis, \
         patch("bot.preferences.HF_SPACE_ID", "fake/space"):
        mock_redis.get.return_value = "hf"
        from bot.preferences import get_provider
        assert get_provider(123) == "hf"


def test_get_provider_falls_back_to_default_when_hf_not_configured():
    """Saved value is 'hf' but HF_SPACE_ID is empty — fall back."""
    with patch("bot.preferences.redis") as mock_redis, \
         patch("bot.preferences.HF_SPACE_ID", ""):
        mock_redis.get.return_value = "hf"
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


def test_set_provider_saves_to_redis():
    with patch("bot.preferences.redis") as mock_redis:
        from bot.preferences import set_provider
        assert set_provider(123, "hf") is True
        mock_redis.set.assert_called_once_with("provider:123", "hf")


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
