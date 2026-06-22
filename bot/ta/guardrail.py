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
    re.compile(
        r"^(looking at the (history|context|conversation|message))", re.IGNORECASE
    ),
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

# Inappropriate content topics for teenage audience. Matched as whole words
# (see _INAPPROPRIATE_RE) — NEVER bare substrings. Substring matching was a
# real bug confirmed in prod: a benign answer containing "whatever" (-> "hate")
# was suppressed, surfacing to the student as "Something went wrong."
_INAPPROPRIATE_TOPICS = [
    "alcohol",
    "drugs",
    "sex",
    "sexual",
    "porn",
    "nudity",
    "illegal",
    "violence",
    "hate",
    "discrimination",
    "harassment",
    "suicide",
    "self-harm",
    "weapons",
    "gambling",
    "adult",
]

# Whole-word match: \b on both edges so "sex" matches "sex" but not "Sussex",
# and "hate" matches "hate" but not "whatever". The hyphen in "self-harm" is a
# non-word char, so the surrounding \b still anchors correctly.
_INAPPROPRIATE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _INAPPROPRIATE_TOPICS) + r")\b",
    re.IGNORECASE,
)

# A hedging *non-answer* is short and stops at the caveat. A long, useful reply
# that pivots past the caveat ("…but here's how…") is a real answer — bias
# toward delivering it, since suppressing surfaces as "Something went wrong."
_MAX_HEDGE_LEN = 200
_HEDGE_PIVOTS = (
    " but ",
    " however",
    " though",
    " instead",
    "here's",
    "here is",
    "you can",
    "you could",
    "generally",
    "try ",
    "for example",
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
    """True only for short replies that are *purely* a hedge.

    A long, helpful answer that merely contains a hedging phrase (opens with a
    caveat then answers) is a real answer; suppressing it would surface as
    "Something went wrong." So: hedge phrase present, no pivot to content, and
    short.
    """
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()
    if not any(phrase in low for phrase in HEDGING_PHRASES):
        return False
    if any(pivot in low for pivot in _HEDGE_PIVOTS):
        return False
    return len(t) <= _MAX_HEDGE_LEN


# ── Step 6: inappropriate content check ───────────────────────────────────
def is_inappropriate_content(text: str) -> bool:
    """Check if the text contains inappropriate content for teens.

    Whole-word match only (see ``_INAPPROPRIATE_RE``). Bare-substring matching
    here suppressed legitimate replies containing "whatever", "Sussex", etc.
    """
    return bool(_INAPPROPRIATE_RE.search(text or ""))


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
    if is_inappropriate_content(step2):
        return None
    return step2
