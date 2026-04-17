"""Fire the self-upgrade Claude Code routine.

The routine itself is created + configured in the claude.ai/code/routines
UI (prompt, target repo, branch permissions, environment). This module
is the thin HTTP client that the /upgrade Telegram command calls.

Fire returns immediately with a session id + URL; the routine runs
asynchronously on Anthropic's side and opens the PR on its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests

from bot.config import CLAUDE_ROUTINE_ID, CLAUDE_ROUTINE_TOKEN


_FIRE_URL_TEMPLATE = "https://api.anthropic.com/v1/claude_code/routines/{id}/fire"
_BETA_HEADER       = "experimental-cc-routine-2026-04-01"
_MAX_TEXT_LEN      = 65_536
_TIMEOUT_SECONDS   = 15


class UpgradeError(Exception):
    """Fatal error firing the routine — caller shows the message to the admin."""


@dataclass
class FireResult:
    session_id: str
    session_url: str


def is_configured() -> bool:
    return bool(CLAUDE_ROUTINE_ID and CLAUDE_ROUTINE_TOKEN)


def fire(instructions: str) -> FireResult:
    """POST to the routine's /fire endpoint. Returns the session info.

    Raises UpgradeError on any failure so the command handler can DM a
    readable message back to the instructor.
    """
    if not is_configured():
        raise UpgradeError(
            "CLAUDE_ROUTINE_ID / CLAUDE_ROUTINE_TOKEN not set on Vercel."
        )
    text = (instructions or "").strip()
    if not text:
        raise UpgradeError("Instructions are empty.")
    if len(text) > _MAX_TEXT_LEN:
        raise UpgradeError(
            f"Instructions too long ({len(text)} chars, max {_MAX_TEXT_LEN})."
        )

    url = _FIRE_URL_TEMPLATE.format(id=CLAUDE_ROUTINE_ID)
    headers = {
        "Authorization":     f"Bearer {CLAUDE_ROUTINE_TOKEN}",
        "anthropic-beta":    _BETA_HEADER,
        "anthropic-version": "2023-06-01",
        "Content-Type":      "application/json",
    }
    try:
        resp = requests.post(
            url, headers=headers, json={"text": text}, timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise UpgradeError(f"Network error calling Claude routine: {e}") from e

    if resp.status_code >= 400:
        # Anthropic errors are JSON; fall back to raw text if parsing fails.
        detail = _extract_error(resp)
        raise UpgradeError(f"Routine fire failed ({resp.status_code}): {detail}")

    try:
        data = resp.json()
    except ValueError as e:
        raise UpgradeError(f"Routine returned non-JSON response: {e}") from e

    session_id  = data.get("claude_code_session_id") or ""
    session_url = data.get("claude_code_session_url") or ""
    if not session_id or not session_url:
        raise UpgradeError(f"Routine response missing session fields: {data!r}")
    return FireResult(session_id=session_id, session_url=session_url)


def _extract_error(resp: "requests.Response") -> str:
    try:
        data = resp.json()
    except ValueError:
        return (resp.text or "")[:300]
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err)
    return str(data)[:300]
