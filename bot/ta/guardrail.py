"""Post-processing for LLM replies (spec §5.10).

Steps applied in order:

    1. Strip <think>...</think> blocks (case-insensitive, multiline).
    2. Drop leading "reasoning" paragraphs ("Okay, the user is asking…").
    3. If the result is empty → no reply.
    4. Drop if the reply equals "IGNORE" (case-insensitive).
    5. Drop if the reply is a hedging non-answer
       ("I don't have access to...", etc.).

``clean(text)`` returns the cleaned text or ``None`` when the reply
should be suppressed entirely. Callers should ``if cleaned is None:
return`` and skip history persistence so we don't pollute the context.
"""
from __future__ import annotations

import re


# ── Patterns ──────────────────────────────────────────────────────────────
_THINK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)

_LEADING_REASONING = [
    re.compile(
        r"^(okay|ok|alright|hmm|let me|first|so),?\s+"
        r"(the user|looking at|i need|i should|let me|i'll)",
        re.IGNORECASE,
    ),
    re.compile(r"^(the user (is asking|asked|wants|said|mentioned))", re.IGNORECASE),
    re.compile(r"^(looking at the (history|context|conversation|message))", re.IGNORECASE),
    re.compile(
        r"^(i think|i need to|i should|let me think|"
        r"let me (check|analyze|consider|unpack))",
        re.IGNORECASE,
    ),
]

HEDGING_PHRASES = (
    "i don't have access",
    "i don't have information",
    "i'm not able to access",
    "i cannot access",
    "i don't know if",
    "i'm not sure if",
    "i have no way of knowing",
    "i have no information about",
    "not in my knowledge",
    "outside my knowledge",
    "i can't answer that",
    "i cannot answer that",
)


# ── Step 1: strip <think> blocks ──────────────────────────────────────────
def strip_thinking(text: str) -> str:
    if not text:
        return ""
    return _THINK_RE.sub("", text).strip()


# ── Step 2: drop leading reasoning paragraphs ─────────────────────────────
def _looks_like_reasoning(para: str) -> bool:
    return any(rx.match(para.strip()) for rx in _LEADING_REASONING)


def trim_leading_reasoning(text: str) -> str:
    """Split on blank lines; drop paragraphs while they look like thinking."""
    if not text:
        return ""
    paragraphs = re.split(r"\n\s*\n", text)
    i = 0
    while i < len(paragraphs) and _looks_like_reasoning(paragraphs[i]):
        i += 1
    return "\n\n".join(paragraphs[i:]).strip()


# ── Step 5: hedging check ─────────────────────────────────────────────────
def is_hedging(text: str) -> bool:
    t = (text or "").lower()
    return any(phrase in t for phrase in HEDGING_PHRASES)


# ── Step 4: ignore marker ─────────────────────────────────────────────────
def is_ignore_marker(text: str) -> bool:
    return (text or "").strip().upper() == "IGNORE"


# ── Public ────────────────────────────────────────────────────────────────
def clean(text: str) -> str | None:
    """Return cleaned text or ``None`` if the reply should be suppressed."""
    if not text:
        return None
    step1 = strip_thinking(text)
    step2 = trim_leading_reasoning(step1)
    if not step2.strip():
        return None
    if is_ignore_marker(step2):
        return None
    if is_hedging(step2):
        return None
    return step2
