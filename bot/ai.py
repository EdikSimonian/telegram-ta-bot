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

from bot.clients import ai
from bot.config import (
    DEFAULT_MODEL,
    MAX_HISTORY,
    SYSTEM_PROMPT,
    TAVILY_API_KEY,
)
from bot.ta import guardrail, rag
from bot.ta.prepare import Prepared, prompt_prefix
from bot.ta.state import (
    append_history,
    get_active_model,
    get_history,
    get_last_group_qa,
    save_last_group_qa,
)


SEARCH_TRIGGERS = [
    "today", "latest", "current", "news", "now", "recent", "this week",
    "this month", "this year", "happened", "who won", "what is happening",
    "weather", "price", "score", "update", "announce", "release",
]


def needs_search(text: str) -> bool:
    lower = text.lower()
    return any(t in lower for t in SEARCH_TRIGGERS)


def _build_system(context_block: str | None) -> str:
    if not context_block:
        return SYSTEM_PROMPT
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Course context (from indexed docs — cite or paraphrase as needed):\n"
        f"{context_block}"
    )


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


def answer(p: Prepared) -> str | None:
    """Produce a reply for the prepared message, or None if we shouldn't reply.

    Side effects: persists user+assistant to group history on success.
    """
    raw = (p.stripped_text or "").strip()
    if not raw:
        return None

    # 1. RAG retrieval.
    matches = rag.retrieve(raw)
    context_block = rag.format_context(matches) if matches else None

    # 2. Assemble messages. System first, then prior turns (group-keyed),
    #    then the new user turn (with the spec §5.9 prefix).
    system_msg = _build_system(context_block)
    extra_system = _maybe_search_block(raw, has_rag_hits=bool(matches))

    messages: list[dict] = [{"role": "system", "content": system_msg}]
    if extra_system:
        messages.append({"role": "system", "content": extra_system})

    # In DMs: inject the student's last group Q&A as context so follow-ups
    # work without the student having to re-state the question.
    if p.is_dm:
        prior = get_last_group_qa(p.user_id)
        if prior:
            messages.append({
                "role": "system",
                "content": (
                    "The student is following up on a recent group conversation. "
                    "Here is the original exchange:\n\n"
                    f"Student asked: {prior.get('question', '')}\n"
                    f"You replied: {prior.get('answer', '')}\n\n"
                    "Use this as context for the follow-up question below."
                ),
            })

    history = get_history(p.group_key, limit=MAX_HISTORY)
    for turn in history:
        role = turn.get("role")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    prefix = prompt_prefix(p)
    user_payload = f"{prefix} {raw}".strip() if prefix else raw
    messages.append({"role": "user", "content": user_payload})

    # 3. Call OpenAI.
    model = get_active_model(p.group_key) or DEFAULT_MODEL
    try:
        resp = ai.chat.completions.create(model=model, messages=messages)
        raw_reply = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[ai] chat error: {e}")
        return None

    # 3b. Guardrail: strip <think> blocks, leading reasoning, drop hedged /
    #     IGNORE / empty replies. Suppressed replies don't persist to history
    #     (we don't want "IGNORE" polluting the context).
    reply = guardrail.clean(raw_reply)
    if not reply:
        return None

    # 4. Persist — group-level history so the whole class shares context.
    append_history(p.group_key, "user", user_payload, limit=MAX_HISTORY)
    append_history(p.group_key, "assistant", reply, limit=MAX_HISTORY)

    # 4b. In groups: snapshot this Q&A per student so DM follow-ups work.
    if not p.is_dm:
        save_last_group_qa(p.user_id, raw, reply, p.group_key)

    # 5. Append source citations when RAG hit something.
    if matches:
        seen_urls: set[str] = set()
        sources: list[str] = []
        for m in matches:
            url = m.get("blobUrl") or ""
            title = m.get("title") or "doc"
            if url and url in seen_urls:
                continue
            if url:
                sources.append(f"• [{title}]({url})")
                seen_urls.add(url)
            else:
                sources.append(f"• {title}")
        reply = f"{reply}\n\n**Sources:**\n" + "\n".join(sources[:5])

    # 6. In groups: nudge students to DM for follow-up.
    if not p.is_dm:
        reply += "\n\n_DM me if you'd like to ask follow-up questions._"

    return reply
