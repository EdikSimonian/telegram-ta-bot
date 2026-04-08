from bot.clients import redis
from bot.config import (
    DEFAULT_PROVIDER, HF_SPACE_ID, ARMGPT_BASE_URL, ARMGPT_API_KEY,
)

VALID_PROVIDERS = ("openai", "hf", "armgpt")


def _is_provider_enabled(provider: str) -> bool:
    """Whether the given provider is currently configured via env vars."""
    if provider == "openai":
        return True
    if provider == "hf":
        return bool(HF_SPACE_ID)
    if provider == "armgpt":
        return bool(ARMGPT_BASE_URL and ARMGPT_API_KEY)
    return False


def enabled_providers() -> tuple:
    """Return the tuple of providers currently enabled in this deployment."""
    return tuple(p for p in VALID_PROVIDERS if _is_provider_enabled(p))


def get_provider(user_id: int) -> str:
    """Return the user's chosen provider, or DEFAULT_PROVIDER.

    Falls back to DEFAULT_PROVIDER if Redis is down, the user has no saved
    preference, the saved value is invalid, or the saved provider is no
    longer enabled in this deployment.
    """
    try:
        value = redis.get(f"provider:{user_id}")
    except Exception as e:
        print(f"[prefs] redis read error for user={user_id}: {e}")
        return DEFAULT_PROVIDER
    if value not in VALID_PROVIDERS:
        print(f"[prefs] user={user_id} stored={value!r} -> default (invalid)")
        return DEFAULT_PROVIDER
    if not _is_provider_enabled(value):
        print(f"[prefs] user={user_id} stored={value!r} -> default (provider disabled)")
        return DEFAULT_PROVIDER
    print(f"[prefs] user={user_id} stored={value!r} -> {value}")
    return value


def set_provider(user_id: int, provider: str) -> bool:
    """Save the user's provider choice. Returns True on success.

    Rejects providers that are not currently enabled in this deployment.
    """
    if provider not in VALID_PROVIDERS:
        print(f"[prefs] set_provider rejected: {provider!r} not in VALID_PROVIDERS")
        return False
    if not _is_provider_enabled(provider):
        print(f"[prefs] set_provider rejected: {provider!r} not enabled (env vars missing)")
        return False
    try:
        redis.set(f"provider:{user_id}", provider)
        print(f"[prefs] set_provider user={user_id} -> {provider}")
        return True
    except Exception as e:
        print(f"[prefs] redis write error for user={user_id}: {e}")
        return False
