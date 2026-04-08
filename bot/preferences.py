from bot.clients import redis
from bot.config import DEFAULT_PROVIDER, HF_SPACE_ID

VALID_PROVIDERS = ("openai", "hf")


def get_provider(user_id: int) -> str:
    """Return the user's chosen provider, or DEFAULT_PROVIDER.

    Falls back to DEFAULT_PROVIDER if Redis is down, the user has no saved
    preference, or the saved preference is "hf" but HF_SPACE_ID is not configured.
    """
    try:
        value = redis.get(f"provider:{user_id}")
    except Exception as e:
        print(f"Redis read error (preferences): {e}")
        return DEFAULT_PROVIDER
    if value not in VALID_PROVIDERS:
        return DEFAULT_PROVIDER
    if value == "hf" and not HF_SPACE_ID:
        return DEFAULT_PROVIDER
    return value


def set_provider(user_id: int, provider: str) -> bool:
    """Save the user's provider choice. Returns True on success."""
    if provider not in VALID_PROVIDERS:
        return False
    try:
        redis.set(f"provider:{user_id}", provider)
        return True
    except Exception as e:
        print(f"Redis write error (preferences): {e}")
        return False
