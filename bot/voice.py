"""Voice in/out via Cloudflare Workers AI.

In: ``transcribe()`` — POSTs OGG/Opus audio to Whisper-large-v3-turbo with
the audio base64-encoded inside a JSON envelope. Telegram voice messages
are 48kHz mono OGG/Opus; Cloudflare accepts them as-is, no transcoding.

Out: ``synthesize()`` — POSTs text to Deepgram Aura-1 (also hosted on
Cloudflare Workers AI) and gets back **raw MP3 bytes** (not base64,
unlike most other CF AI models). Telegram ``sendVoice`` accepts MP3 over
multipart upload, so we forward the bytes directly without re-encoding.

Disabled gracefully when CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_TOKEN
is unset — callers check ``is_enabled()`` and short-circuit before paying
any cost.
"""

from __future__ import annotations

import base64

import requests

from bot.config import (
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
    VOICE_REPLY_SPEAKER,
)

WHISPER_ENDPOINT_TEMPLATE = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}"
    "/ai/run/@cf/openai/whisper-large-v3-turbo"
)
AURA_ENDPOINT_TEMPLATE = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}"
    "/ai/run/@cf/deepgram/aura-1"
)
TRANSCRIBE_TIMEOUT = 30
SYNTHESIZE_TIMEOUT = 30

# Aura-1 speakers and their voice gender. Order is what /voice will list.
# Genders sourced from Deepgram's Aura-1 voice catalog.
AURA_SPEAKER_GENDERS: dict[str, str] = {
    "angus": "male",
    "asteria": "female",
    "arcas": "male",
    "orion": "male",
    "orpheus": "male",
    "athena": "female",
    "luna": "female",
    "zeus": "male",
    "perseus": "male",
    "helios": "male",
    "hera": "female",
    "stella": "female",
}
AURA_SPEAKERS = list(AURA_SPEAKER_GENDERS.keys())
DEFAULT_SPEAKER = "angus"


def is_enabled() -> bool:
    return bool(CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN)


def get_active_speaker() -> str:
    """Resolve the bot's current TTS voice.

    Priority: Redis-stored override (from /voice) > VOICE_REPLY_SPEAKER env
    default > ``DEFAULT_SPEAKER``. Defends against stale or invalid stored
    values by re-validating against ``AURA_SPEAKERS`` on every read.
    """
    # Local import: bot.ta.state imports from bot.clients which imports
    # config; keeping this import lazy avoids any boot-time cycle.
    from bot.ta.state import get_voice_speaker

    stored = (get_voice_speaker() or "").strip().lower()
    if stored in AURA_SPEAKERS:
        return stored
    env_default = (VOICE_REPLY_SPEAKER or "").strip().lower()
    if env_default in AURA_SPEAKERS:
        return env_default
    return DEFAULT_SPEAKER


def transcribe(audio_bytes: bytes) -> str:
    """Send OGG/Opus audio to Cloudflare Whisper-turbo, return transcript text.

    Caller must check ``is_enabled()`` first. Any failure (missing creds,
    HTTP error, malformed response) raises — handlers catch and reply with
    a generic error so we never leak provider details to students.
    """
    if not is_enabled():
        raise RuntimeError("Cloudflare credentials not configured")

    url = WHISPER_ENDPOINT_TEMPLATE.format(account_id=CLOUDFLARE_ACCOUNT_ID)
    payload = {"audio": base64.b64encode(audio_bytes).decode("ascii")}
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        url, json=payload, headers=headers, timeout=TRANSCRIBE_TIMEOUT
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("success"):
        errors = body.get("errors", [])
        raise RuntimeError(f"Cloudflare transcription failed: {errors}")
    return ((body.get("result") or {}).get("text") or "").strip()


def synthesize(text: str, speaker: str | None = None) -> bytes:
    """Generate MP3 audio from text via Cloudflare Aura-1 (Deepgram TTS).

    Returns raw MP3 bytes (mono, 22.05 kHz, 48 kbps) ready for
    ``bot.send_voice``. Aura-1 is English-only at the moment — non-English
    text will produce gibberish or silence; callers should length-gate and
    language-gate before calling this.
    """
    if not is_enabled():
        raise RuntimeError("Cloudflare credentials not configured")

    url = AURA_ENDPOINT_TEMPLATE.format(account_id=CLOUDFLARE_ACCOUNT_ID)
    payload = {"text": text, "speaker": speaker or VOICE_REPLY_SPEAKER}
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        url, json=payload, headers=headers, timeout=SYNTHESIZE_TIMEOUT
    )
    response.raise_for_status()
    # Aura returns binary MP3 on success and JSON on error. A 200 with JSON
    # would be a contract surprise — surface it loudly rather than send
    # garbage to Telegram.
    content_type = response.headers.get("content-type", "")
    if "json" in content_type.lower():
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text[:200]}
        raise RuntimeError(f"Cloudflare TTS unexpected JSON response: {body}")
    return response.content
