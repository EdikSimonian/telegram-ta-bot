"""Singleton clients used across the bot.

Every optional dependency degrades to ``None`` when its env vars are unset
so the bot can still boot. Consumers must handle ``None``.
"""
import telebot
from openai import OpenAI

from bot.config import (
    TELEGRAM_TOKEN,
    AI_API_KEY,
    AI_BASE_URL,
    UPSTASH_URL,
    UPSTASH_TOKEN,
    UPSTASH_VECTOR_URL,
    UPSTASH_VECTOR_TOKEN,
)

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

# LLM client. AI_API_KEY is required at config load, so this is always live.
ai = OpenAI(base_url=AI_BASE_URL, api_key=AI_API_KEY)

# Embeddings currently share the same OpenAI client and key. When we add a
# non-OpenAI provider, `bot/ta/rag.py` can swap this out without touching
# anything else.
embeddings_client = ai

# Redis — optional but strongly recommended for the TA bot. Without it the
# stats, quizzes, admin list, announcements, etc. all no-op.
if UPSTASH_URL and UPSTASH_TOKEN:
    from upstash_redis import Redis
    redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)
else:
    redis = None
    print("Redis not configured — running in stateless mode (no memory, no rate limit, no TA state).")

# Upstash Vector — optional. When unset, RAG retrieval is skipped and the
# bot falls back to plain LLM answers.
if UPSTASH_VECTOR_URL and UPSTASH_VECTOR_TOKEN:
    try:
        from upstash_vector import Index as _VectorIndex
        vector_index = _VectorIndex(url=UPSTASH_VECTOR_URL, token=UPSTASH_VECTOR_TOKEN)
    except ImportError:
        vector_index = None
        print("upstash-vector not installed — RAG retrieval disabled.")
else:
    vector_index = None

BOT_INFO = bot.get_me()
