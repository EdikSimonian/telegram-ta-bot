import os

# ── Telegram ──────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"].strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()

# ── LLM provider (OpenAI-compatible) ──────────────────────────────────────
AI_API_KEY = os.environ["AI_API_KEY"].strip()
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.openai.com/v1").strip()
MODEL = os.environ.get("AI_MODEL", "gpt-5.4-nano").strip()
QUIZ_MODEL = os.environ.get("QUIZ_MODEL", "").strip() or MODEL

# Models the /model admin command will accept. Kept tight on purpose:
# this deployment targets OpenAI direct, and invalid model IDs just cause
# 404s at request time. Extend when you add a second provider.
VALID_MODELS = [
    "gpt-5.5-nano",
    "gpt-5.5-mini",
    "gpt-5.5",
    "gpt-5.4-nano",
    "gpt-5.4-mini",
    "gpt-5.4",
]
DEFAULT_MODEL = MODEL

# ── HF provider (legacy fallback; usually unset for TA bot) ───────────────
HF_SPACE_ID = os.environ.get("HF_SPACE_ID", "").strip()
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()
DEFAULT_PROVIDER = "main"

# ── Upstash Redis (required for TA bot — stateful) ────────────────────────
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "").strip()
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip()
# Prefix prepended to every Redis key. Lets one shared Upstash Redis DB
# host multiple bots (prod + test) without key collisions. Default "ta:"
# keeps backwards compatibility with single-bot deployments. Override to
# "ta:prod:" / "ta:test:" when sharing a DB.
_raw_redis_prefix = os.environ.get("REDIS_PREFIX", "ta:").strip()
REDIS_PREFIX = (_raw_redis_prefix.rstrip(":") + ":") if _raw_redis_prefix else "ta:"

# ── Upstash Vector (RAG) ──────────────────────────────────────────────────
UPSTASH_VECTOR_URL = os.environ.get("UPSTASH_VECTOR_REST_URL", "").strip()
UPSTASH_VECTOR_TOKEN = os.environ.get("UPSTASH_VECTOR_REST_TOKEN", "").strip()
# Upstash Vector has first-class namespaces: one index can host many
# isolated corpora. Blank = default namespace. Use "prod" / "test" when
# sharing an index.
VECTOR_NAMESPACE = os.environ.get("VECTOR_NAMESPACE", "").strip()

# ── Upstash QStash (delayed callbacks for quiz auto-reveal) ───────────────
# Upstash exposes a generic endpoint and region-scoped endpoints (e.g.
# https://qstash-us-east-1.upstash.io). Override via QSTASH_URL when the
# console gives you a regional URL — keeps publish latency low.
QSTASH_URL = (
    os.environ.get("QSTASH_URL", "https://qstash.upstash.io").strip().rstrip("/")
)
QSTASH_TOKEN = os.environ.get("QSTASH_TOKEN", "").strip()
QSTASH_CURRENT_SIGNING_KEY = os.environ.get("QSTASH_CURRENT_SIGNING_KEY", "").strip()
QSTASH_NEXT_SIGNING_KEY = os.environ.get("QSTASH_NEXT_SIGNING_KEY", "").strip()

# ── GitHub ────────────────────────────────────────────────────────────────
# Optional PAT for private repos or to avoid 60-req/hour unauthenticated
# rate limit. Public repos work without it for typical course volume.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

# ── Claude Code Routine (self-upgrade) ────────────────────────────────────
# Routine created in the claude.ai/code/routines UI, bound to the
# EdikSimonian/telegram-ta-bot repo. The /upgrade command (instructor only)
# fires this routine with the instruction text; the routine edits the code,
# writes tests, and opens a PR against the test branch.
CLAUDE_ROUTINE_ID = os.environ.get("CLAUDE_ROUTINE_ID", "").strip()
CLAUDE_ROUTINE_TOKEN = os.environ.get("CLAUDE_ROUTINE_TOKEN", "").strip()
# Shared secret configured on every GitHub webhook that posts to us. The
# webhook endpoint verifies X-Hub-Signature-256 against this — unsigned
# requests get 401.
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "").strip()

# ── Vercel Blob ───────────────────────────────────────────────────────────
BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()
# Prefix every blob path. Lets one shared Blob store back multiple bots
# (prod + test) without collisions. Normalize to end with "/".
_raw_prefix = os.environ.get("BLOB_PATH_PREFIX", "docs/").strip()
BLOB_PATH_PREFIX = (_raw_prefix.rstrip("/") + "/") if _raw_prefix else "docs/"

# ── Embeddings ────────────────────────────────────────────────────────────
EMBEDDINGS_PROVIDER = os.environ.get("EMBEDDINGS_PROVIDER", "openai").strip().lower()
EMBEDDINGS_MODEL = os.environ.get("EMBEDDINGS_MODEL", "text-embedding-3-small").strip()

# ── Search (optional) ─────────────────────────────────────────────────────
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "").strip()

# ── Deployment ────────────────────────────────────────────────────────────
# Base URL used to build QStash callback targets. Prefer explicit PROD_URL
# (no scheme stripping needed); fall back to VERCEL_URL which Vercel injects
# without a scheme.
PROD_URL = os.environ.get("PROD_URL", "").strip()
_vercel_url = os.environ.get("VERCEL_URL", "").strip()


def _normalize_public_url(raw: str) -> str:
    raw = raw.strip().rstrip("/")
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return f"https://{raw}"


PUBLIC_URL = _normalize_public_url(PROD_URL) or _normalize_public_url(_vercel_url)

# ── Bot identity / policy ─────────────────────────────────────────────────
# Label surfaced in /info and logs so you can tell which deployment is
# answering when multiple bots share this codebase (prod vs test).
BOT_ENV = os.environ.get("BOT_ENV", "").strip().lower() or "local"

PERMANENT_ADMIN = os.environ.get("PERMANENT_ADMIN", "ediksimonian").strip().lower()


# Numeric Telegram user ID for the permanent admin. STRONGLY recommended:
# Telegram usernames are mutable and can be recycled to a new account 30
# days after release, so a username-only gate could hand `/upgrade` to a
# stranger. When set, this overrides the username-based instructor check.
# Find your ID by DMing @userinfobot on Telegram.
def _parse_admin_id(raw: str) -> int:
    raw = (raw or "").strip()
    if not raw or not raw.lstrip("-").isdigit():
        return 0
    return int(raw)


PERMANENT_ADMIN_ID = _parse_admin_id(os.environ.get("PERMANENT_ADMIN_ID", ""))
# Human-readable instructor name for welcome messages + system prompt.
INSTRUCTOR_NAME = os.environ.get("INSTRUCTOR_NAME", "Edik Simonian").strip()

# TA bot: per-student questions in a rolling window (student-facing limit).
TA_RATE_LIMIT = int(os.environ.get("TA_RATE_LIMIT", "10"))
TA_RATE_LIMIT_WINDOW = int(os.environ.get("TA_RATE_LIMIT_WINDOW", "3600"))

# Legacy hard daily cap (kept for the original polling runner).
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "250"))

QUIZ_TIMEOUT_MINUTES = int(os.environ.get("QUIZ_TIMEOUT_MINUTES", "3"))
QUIZ_TIMEOUT_SECONDS = QUIZ_TIMEOUT_MINUTES * 60

# ── App ───────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    f"You are the Teaching Assistant for the Summer 2026 AI Bot Workshop in "
    f"Armenia, led by {INSTRUCTOR_NAME} (@{PERMANENT_ADMIN}).\n\n"
    "Architecture facts (always true, never contradict):\n"
    "- This bot runs on Vercel Functions (Python) via webhook\n"
    "- State lives in Upstash Redis\n"
    "- RAG uses Upstash Vector with OpenAI embeddings\n"
    "- Docs are stored in Vercel Blob\n"
    "- Quiz auto-reveal uses Upstash QStash delayed queue\n\n"
    "WHEN TO ANSWER vs STAY SILENT — read this carefully:\n"
    "Most messages in the group are between students; you are NOT a chat "
    "participant. Reply ONLY when the message is BOTH a course-related "
    "question AND you have a confident answer. Otherwise reply with the "
    "single word: IGNORE\n\n"
    "Reply IGNORE when:\n"
    "- Greetings, small talk, or chatter between students "
    '("hi Jack", "good morning", "thanks!", "lol", reactions, emoji-only)\n'
    "- Messages addressed to another student by name\n"
    "- Off-topic content unrelated to programming, AI/ML, the course material, "
    "  or workshop logistics\n"
    "- Questions where the course context below + your general knowledge are "
    "  insufficient to give a confident, useful answer\n"
    "- The message is a statement, not a question, and doesn't require help\n\n"
    "Reply normally when:\n"
    "- The user @-mentions you or replies directly to your message (you can "
    "  see this from the prompt prefix)\n"
    "- Clear technical question about Python, AI/ML, data science, the bot "
    "  itself, or course material\n"
    "- Workshop logistics question the context covers\n\n"
    "Use the course context below as ground truth. If context covers it, "
    "ground the answer there. If a question is course-adjacent and you can "
    "answer from general knowledge, do so concisely — but if you're guessing, "
    "reply IGNORE instead of fabricating.\n\n"
    "Special prefix handling:\n"
    f"- `[INSTRUCTOR @{PERMANENT_ADMIN}]:` → from the instructor, highest priority\n"
    "- `[DIRECT]:` → bot was @-mentioned or message is DM "
    "(answer if it's a question; small talk in DM still gets IGNORE)\n"
    "- `[REPLY_TO @user]:` → reply to another student, not the bot — "
    "almost always IGNORE\n"
    "- `[DM]:` → private chat context, no group history\n\n"
    "Format: plain text, short paragraphs, prefer bullet points for lists. "
    "No HTML unless asked.\n"
    "Language: match the student's language. If they write in Armenian, reply in Armenian. If in Russian, reply in Russian. Default to English."
)
MAX_HISTORY = 20
HISTORY_TTL = 2592000  # 30 days
MAX_MSG_LEN = 4096
TG_CHUNK_LEN = 4000  # safety margin under Telegram's 4096 limit

# RAG knobs
RAG_CHUNK_SIZE = 800
RAG_CHUNK_OVERLAP = 100
RAG_TOP_K = 5
RAG_MIN_SCORE = 0.6
