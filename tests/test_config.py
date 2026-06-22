"""Config model validation — a typo'd model env must fail safe, not 400.

Regression: QUIZ_MODEL=gpt-5.4 (not a real model) 400'd every /quiz with
"Couldn't generate a quiz". Env-var models aren't user-gated, so config now
coerces an out-of-allowlist value to a known-good fallback.
"""


def test_coerce_model_passes_valid_values():
    from bot.config import _coerce_model

    assert _coerce_model("gpt-5.5", "gpt-5.4-nano") == "gpt-5.5"
    assert _coerce_model("gpt-5.4-mini", "gpt-5.4-nano") == "gpt-5.4-mini"
    assert _coerce_model("gpt-5.4-nano", "gpt-5.5") == "gpt-5.4-nano"


def test_coerce_model_falls_back_on_invalid():
    from bot.config import _coerce_model

    # the exact prod typo
    assert _coerce_model("gpt-5.4", "gpt-5.4-nano") == "gpt-5.4-nano"
    assert _coerce_model("bogus-model", "gpt-5.4-mini") == "gpt-5.4-mini"
    assert _coerce_model("", "gpt-5.5") == "gpt-5.5"


def test_resolved_models_are_always_valid():
    """Whatever the env, the resolved models must be in the allowlist."""
    import bot.config as c

    assert c.MODEL in c.VALID_MODELS
    assert c.QUIZ_MODEL in c.VALID_MODELS
    assert c.DEFAULT_MODEL in c.VALID_MODELS
