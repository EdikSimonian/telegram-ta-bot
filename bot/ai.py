"""Question-answering pipeline for the TA bot.

Flow (stage 5):
    1. Retrieve RAG matches from Upstash Vector via bot.ta.rag.retrieve.
    2. Load group-level history from bot.ta.state.get_history.
    3. Compose messages: [system + context, ...history, user w/ prefix].
    4. Call OpenAI with the group's active model (or DEFAULT_MODEL).
    5. Persist user + assistant turns to history.

Web search (Tavily) is kept only as a secondary signal for dated or
real-time queries when RAG has no hits. When TAVILY_API_KEY is unset
(default) this path is skipped entirely.
"""

from __future__ import annotations

import html
import re

from bot.clients import ai
from bot.config import (
    DEFAULT_MODEL,
    DMS_ENABLED,
    MAX_HISTORY,
    SYSTEM_PROMPT,
    TAVILY_API_KEY,
)
from bot.ta import guardrail, rag
from bot.ta.prepare import Prepared, prompt_prefix
from bot.ta.state import (
    append_dm_log,
    append_history,
    get_active_model,
    get_history,
    get_last_group_qa,
    save_last_group_qa,
)


SEARCH_TRIGGERS = [
    "today",
    "latest",
    "current",
    "news",
    "now",
    "recent",
    "this week",
    "this month",
    "this year",
    "happened",
    "who won",
    "what is happening",
    "weather",
    "price",
    "score",
    "update",
    "announce",
    "release",
]


def needs_search(text: str) -> bool:
    lower = text.lower()
    return any(t in lower for t in SEARCH_TRIGGERS)


# Trailer must (a) start at a word boundary on its left edge — preceded by
# start-of-string, whitespace, or newline, never markdown like ** — and
# (b) end the string. The lookbehind blocks mid-line matches such as
# `**SOURCES_USED:** 1` from corrupting the visible reply.
_TRAILER_RE = re.compile(
    r"(?<!\S)SOURCES_USED\s*:\s*([^\n]*)\s*$",
    re.IGNORECASE,
)


def _format_numbered_context(matches: list[dict]) -> str:
    """Render matches as `[N] Title — chunk` blocks so the model can cite by index.

    Caller must pre-filter empty-chunk matches so source numbers stay
    aligned with `matches[idx-1]` lookups in the citation step.
    """
    blocks = []
    for idx, m in enumerate(matches, 1):
        title = ((m.get("title") or "").strip()) or "Untitled"
        text = (m.get("chunkText") or "").strip()
        blocks.append(f"[{idx}] {title}\n{text}")
    return "\n\n---\n\n".join(blocks)


def _build_system(context_block: str | None) -> str:
    if not context_block:
        return SYSTEM_PROMPT
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Course context (from indexed docs — cite or paraphrase as needed). "
        f"Sources are numbered [1], [2], etc.\n\n"
        f"{context_block}\n\n"
        f"On the very last line of your reply, write exactly one of:\n"
        f"  SOURCES_USED: 1,3    (comma-separated numbers you actually drew from)\n"
        f"  SOURCES_USED: none   (if you answered from your own knowledge)\n"
        f"This line is machine-parsed and stripped before the user sees it."
    )


def _extract_sources_used(reply: str) -> tuple[str, set[int] | None]:
    """Parse + strip the SOURCES_USED trailer.

    Returns (clean_reply, used_indices). `used_indices` is None if no trailer
    was emitted, an empty set for `none`, or the parsed integers otherwise.
    """
    m = _TRAILER_RE.search(reply)
    if not m:
        return reply, None
    clean = reply[: m.start()].rstrip()
    payload = m.group(1).strip().lower()
    if not payload or payload == "none":
        return clean, set()
    used: set[int] = set()
    for tok in payload.split(","):
        tok = tok.strip()
        if tok.isdigit():
            used.add(int(tok))
    return clean, used


def _maybe_search_block(question: str, has_rag_hits: bool) -> str | None:
    """Only call Tavily when RAG has no hits AND the query looks time-sensitive."""
    if has_rag_hits or not TAVILY_API_KEY or not needs_search(question):
        return None
    try:
        from bot.search import web_search

        results, _sources = web_search(question)
        if not results:
            return None
        return (
            "The following are real-time web search results retrieved just now. "
            "Use them to answer the user's question directly.\n\n"
            f"{results}"
        )
    except Exception as e:
        print(f"[ai] search error: {e}")
        return None


def _dm_fallback_reply(question: str, p: Prepared) -> str:
    """Last-resort DM response when the model emits IGNORE/empty/hedged text."""
    if getattr(p, "is_instructor", False):
        return "I'm here. Send me what you want to check or change."
    if question.strip().endswith(("?", "՞", "؟")):
        return (
            "I don't have enough context to answer that confidently yet. "
            "Send me a little more detail, or mention the exact course topic."
        )
    return "I'm here. Send me a course question or a follow-up from the group."


def _assemble_messages(
    p: Prepared,
    raw: str,
    system_msg: str,
    extra_system: str | None,
) -> tuple[list[dict], str]:
    """Assemble the messages list for an LLM call.

    Returns (messages, user_payload).
    """
    messages: list[dict] = [{"role": "system", "content": system_msg}]
    if extra_system:
        messages.append({"role": "system", "content": extra_system})
    if p.is_dm:
        messages.append(
            {
                "role": "system",
                "content": (
                    "This is a private DM. Always send a useful reply in DMs "
                    "for both students and the instructor. Never output IGNORE "
                    "in a DM. For greetings or unclear messages, reply briefly "
                    "and invite the user to send the question or follow-up."
                ),
            }
        )

    # In DMs: inject the student's last group Q&A as context so follow-ups
    # work without the student having to re-state the question.
    if p.is_dm:
        prior = get_last_group_qa(p.user_id)
        if prior:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "The student is following up on a recent group conversation. "
                        "Here is the original exchange:\n\n"
                        f"Student asked: {prior.get('question', '')}\n"
                        f"You replied: {prior.get('answer', '')}\n\n"
                        "Use this as context for the follow-up question below."
                    ),
                }
            )

    history = get_history(p.group_key, limit=MAX_HISTORY)
    for turn in history:
        role = turn.get("role")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    prefix = prompt_prefix(p)
    user_payload = f"{prefix} {raw}".strip() if prefix else raw
    messages.append({"role": "user", "content": user_payload})

    return messages, user_payload


def _format_outbound(
    reply: str, matches: list[dict], used_sources: set[int] | None, is_dm: bool
) -> str:
    """Build the outbound HTML message from a cleaned reply text."""
    outbound = html.escape(reply)

    # Append source citations
    if matches and used_sources:
        seen_urls: set[str] = set()
        sources: list[str] = []
        for idx in sorted(used_sources):
            if idx < 1 or idx > len(matches):
                continue
            m = matches[idx - 1]
            url = m.get("blobUrl") or ""
            title = ((m.get("title") or "").strip()) or "doc"
            if url and url in seen_urls:
                continue
            title_html = html.escape(title)
            if url:
                sources.append(
                    f'• <a href="{html.escape(url, quote=True)}">{title_html}</a>'
                )
                seen_urls.add(url)
            else:
                sources.append(f"• {title_html}")
        if sources:
            outbound = f"{outbound}\n\n<b>Sources:</b>\n" + "\n".join(sources[:5])

    # In groups: nudge students to DM for follow-up (only when DMs are on).
    if not is_dm and DMS_ENABLED:
        outbound += "\n\n<i>DM me if you'd like to ask follow-up questions.</i>"

    return outbound


def _persist_history(p: Prepared, user_payload: str, reply: str) -> None:
    """Persist user + assistant turns to history and DM log."""
    append_history(p.group_key, "user", user_payload, limit=MAX_HISTORY)
    append_history(p.group_key, "assistant", reply, limit=MAX_HISTORY)

    if p.is_dm:
        append_dm_log(
            p.user_id,
            "user",
            (p.stripped_text or "").strip(),
            username=p.username,
            first_name=p.first_name,
        )
        append_dm_log(
            p.user_id,
            "assistant",
            reply,
            username=p.username,
            first_name=p.first_name,
        )

    if not p.is_dm:
        save_last_group_qa(
            p.user_id, (p.stripped_text or "").strip(), reply, p.group_key
        )


def stream_answer(p: Prepared, on_chunk):
    """Stream a reply, calling ``on_chunk(partial_html)`` as tokens arrive.

    ``on_chunk`` receives HTML-escaped partial text. During the stream the
    partial is the raw model output (``on_chunk`` is responsible for
    displaying it temporarily). After the stream completes, guardrail and
    source extraction run on the full text. If the reply is suppressed
    (IGNORE in a non-DM), ``on_chunk`` is called with ``None`` to signal
    the caller to delete the temporary message. Otherwise the final call
    is the complete formatted reply with sources and footer.

    Returns the final outbound HTML string, or None if suppressed. History
    is persisted only when the reply is not suppressed — same as ``answer()``.
    """
    raw = (p.stripped_text or "").strip()
    if not raw:
        return None

    # 1. RAG retrieval
    matches = [m for m in rag.retrieve(raw) if (m.get("chunkText") or "").strip()]
    context_block = _format_numbered_context(matches) if matches else None

    # 2. Assemble messages
    system_msg = _build_system(context_block)
    extra_system = _maybe_search_block(raw, has_rag_hits=bool(matches))
    messages, user_payload = _assemble_messages(p, raw, system_msg, extra_system)

    # 3. Call OpenAI with streaming
    model = get_active_model(p.group_key) or DEFAULT_MODEL
    try:
        response = ai.chat.completions.create(
            model=model, messages=messages, stream=True
        )
        accumulated = []
        for chunk in response:
            delta = (
                chunk.choices[0].delta.content
                if chunk.choices and chunk.choices[0].delta
                else None
            )
            if delta:
                accumulated.append(delta)
                partial = "".join(accumulated)
                on_chunk(html.escape(partial))
        raw_reply = "".join(accumulated).strip()
    except Exception as e:
        print(f"[ai] stream chat error: {e}")
        on_chunk(None)  # signal caller to clean up
        return None

    if not raw_reply:
        on_chunk(None)
        return None

    # 3b. Pull off the SOURCES_USED trailer before guardrail
    raw_reply, used_sources = _extract_sources_used(raw_reply)

    # 3c. Guardrail
    reply = guardrail.clean(raw_reply)
    if not reply:
        if not p.is_dm:
            on_chunk(None)  # suppressed — delete temp message
            return None
        reply = _dm_fallback_reply(raw, p)

    # 4. Build final outbound with sources + footer and emit as last chunk.
    #    on_chunk delivers the final text synchronously; only persist after
    #    delivery so a Telegram send failure doesn't pollute history.
    outbound = _format_outbound(reply, matches, used_sources, p.is_dm)
    delivered = on_chunk(outbound)
    if not delivered:
        return None

    # 5. Persist — group-level history so the whole class shares context.
    _persist_history(p, user_payload, reply)

    return outbound


def answer(p: Prepared) -> str | None:
    """Produce a reply for the prepared message, or None if we shouldn't reply.

    Side effects: persists user+assistant to group history on success.
    """
    raw = (p.stripped_text or "").strip()
    if not raw:
        return None

    # 1. RAG retrieval. Filter empty-chunk hits up front so source numbers
    #    in the prompt line up 1:1 with matches[idx-1] in the citation step.
    matches = [m for m in rag.retrieve(raw) if (m.get("chunkText") or "").strip()]
    context_block = _format_numbered_context(matches) if matches else None

    # 2. Assemble messages. System first, then prior turns (group-keyed),
    #    then the new user turn (with the spec §5.9 prefix).
    system_msg = _build_system(context_block)
    extra_system = _maybe_search_block(raw, has_rag_hits=bool(matches))
    messages, user_payload = _assemble_messages(p, raw, system_msg, extra_system)

    # 3. Call OpenAI.
    model = get_active_model(p.group_key) or DEFAULT_MODEL
    try:
        resp = ai.chat.completions.create(model=model, messages=messages)
        raw_reply = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[ai] chat error: {e}")
        return None

    # 3b. Pull off the SOURCES_USED trailer before guardrail so it can't
    #     interfere with IGNORE detection or hedging checks.
    raw_reply, used_sources = _extract_sources_used(raw_reply)

    # 3c. Guardrail: strip <think> blocks, leading reasoning, drop hedged /
    #     IGNORE / empty replies. Suppressed replies don't persist to history
    #     (we don't want "IGNORE" polluting the context).
    reply = guardrail.clean(raw_reply)
    if not reply:
        if not p.is_dm:
            return None
        reply = _dm_fallback_reply(raw, p)

    # 4. Persist
    _persist_history(p, user_payload, reply)

    # 5. Build outbound HTML
    outbound = _format_outbound(reply, matches, used_sources, p.is_dm)

    return outbound
