from bot.config import SYSTEM_PROMPT, TAVILY_API_KEY
from bot.history import get_history, save_history
from bot.preferences import get_provider
from bot.providers import generate

# Keywords that suggest the query needs current/real-time information
SEARCH_TRIGGERS = [
    "today", "latest", "current", "news", "now", "recent", "this week",
    "this month", "this year", "happened", "who won", "what is happening",
    "weather", "price", "score", "update", "announce", "release",
]


def needs_search(text: str) -> bool:
    text_lower = text.lower()
    return any(trigger in text_lower for trigger in SEARCH_TRIGGERS)


def ask_ai(user_id: int, user_message: str) -> str:
    history = get_history(user_id)
    history.append({"role": "user", "content": user_message})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    provider = get_provider(user_id)

    sources = []
    # Skip web search for the HF provider — ArmGPT is Armenian-only and
    # English search results would just pollute its prompt.
    if provider != "hf" and TAVILY_API_KEY and needs_search(user_message):
        try:
            from bot.search import web_search
            results, sources = web_search(user_message)
            messages.append({
                "role": "system",
                "content": (
                    "The following are real-time web search results retrieved just now. "
                    "They reflect current events and are more up-to-date than your training data. "
                    "Use them to answer the user's question directly. Do not dispute or override them with your training data.\n\n"
                    f"{results}"
                ),
            })
        except Exception as e:
            print(f"Search error: {e}")

    messages += history

    reply = generate(user_id, messages)

    if sources:
        citations = "\n".join(f"• [{s['title']}]({s['url']})" for s in sources)
        reply += f"\n\n**Sources:**\n{citations}"

    history.append({"role": "assistant", "content": reply})
    save_history(user_id, history)
    return reply
