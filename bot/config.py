import os

# Telegram
TELEGRAM_TOKEN  = os.environ["TELEGRAM_BOT_TOKEN"].strip()
WEBHOOK_SECRET  = os.environ.get("WEBHOOK_SECRET", "").strip()  # optional, but recommended

# AI provider
AI_API_KEY  = os.environ["AI_API_KEY"].strip()
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.cerebras.ai/v1").strip()
MODEL       = os.environ.get("AI_MODEL", "llama3.1-8b").strip()

# Hugging Face provider (optional) — when set, users can switch via /model
HF_SPACE_ID = os.environ.get("HF_SPACE_ID", "").strip()
DEFAULT_PROVIDER = "openai"

# Redis
UPSTASH_URL   = os.environ["UPSTASH_REDIS_REST_URL"].strip()
UPSTASH_TOKEN = os.environ["UPSTASH_REDIS_REST_TOKEN"].strip()

# Search
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "").strip()

# App
SYSTEM_PROMPT = (
    "You are a knowledgeable and concise AI assistant. "
    "Answer clearly and directly. Avoid unnecessary filler. "
    "Keep responses appropriately brief for a chat interface. "
    "When web search results are provided, treat them as current factual information and use them to answer the user's question. "
    "Do not dispute or second-guess search results based on your training data — your training data may be outdated."
)
MAX_HISTORY     = 20        # messages kept per user (10 conversation turns)
HISTORY_TTL     = 2592000   # conversation history expires after 30 days (seconds)
RATE_LIMIT      = int(os.environ.get("RATE_LIMIT", "50"))  # max messages per user per day
MAX_MSG_LEN     = 4096      # Telegram's character limit per message
