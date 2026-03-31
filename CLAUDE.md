# CLAUDE.md — Project Guide for AI Agents

This file describes the architecture, conventions, and deployment process for this project so an AI agent can work on it without guessing.

---

## What this project is

A serverless Telegram bot template built for students. It runs on Vercel's free tier, uses Cerebras (or any OpenAI-compatible API) for AI responses, and Upstash Redis for per-user conversation memory.

**Stack:** Python 3.12 · Flask · pyTelegramBotAPI · OpenAI SDK · Upstash Redis · Vercel

---

## Project structure

```
VercelTelegramBot/
├── api/
│   └── index.py          # Vercel entrypoint — Flask app + webhook route only
├── bot/
│   ├── __init__.py
│   ├── config.py         # All env vars and constants (edit this to configure the bot)
│   ├── clients.py        # Instantiates bot, ai, redis clients (do not edit unless adding a client)
│   ├── history.py        # get/save/clear conversation history in Redis
│   ├── rate_limit.py     # Per-user daily message rate limiting via Redis
│   ├── ai.py             # ask_ai() — calls the AI provider and manages history
│   ├── helpers.py        # send_reply() and should_respond() utilities
│   └── handlers.py       # All Telegram command and message handlers — add new commands here
├── tests/
│   ├── conftest.py       # Mocks env vars and external packages (telebot, openai, upstash_redis)
│   ├── test_history.py
│   ├── test_rate_limit.py
│   └── test_helpers.py
├── .github/
│   └── workflows/
│       └── ci.yml        # Runs pytest on every push and pull request
├── .env.example          # Template for required environment variables
├── requirements.txt
├── vercel.json           # Rewrites /api/webhook → api/index.py
└── README.md             # Student-facing setup guide
```

---

## How the bot works

1. Telegram sends a POST to `https://<vercel-url>/api/webhook` on every message
2. `vercel.json` rewrites that path to `api/index.py` (Vercel only recognises specific filenames as Flask entrypoints — `index.py` is one of them)
3. `api/index.py` deserialises the update and passes it to pyTelegramBotAPI
4. pyTelegramBotAPI routes to the correct handler in `bot/handlers.py`
5. For text messages: checks `should_respond()` → checks rate limit → sends typing action → calls `ask_ai()` → sends reply
6. `ask_ai()` loads history from Redis, appends the new message, calls the AI, saves updated history, returns the reply

**Critical:** `telebot.TeleBot` must be created with `threaded=False`. Without this, handlers run in threads that are killed when the serverless function returns — the bot receives the message but never replies.

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | — | From @BotFather on Telegram |
| `AI_API_KEY` | Yes | — | API key for the AI provider |
| `UPSTASH_REDIS_REST_URL` | Yes | — | From Upstash console |
| `UPSTASH_REDIS_REST_TOKEN` | Yes | — | From Upstash console |
| `AI_BASE_URL` | No | `https://api.cerebras.ai/v1` | Any OpenAI-compatible base URL |
| `AI_MODEL` | No | `llama3.1-8b` | Model name for the provider |
| `RATE_LIMIT` | No | `50` | Max messages per user per day |

All env vars are read in `bot/config.py`. `.strip()` is called on every value — this prevents subtle bugs from trailing newlines when setting vars via CLI pipes.

---

## AI provider

The bot uses the OpenAI Python SDK pointed at any OpenAI-compatible endpoint. Switching providers only requires changing `AI_BASE_URL` and `AI_MODEL` (via env vars — no code change needed).

**Known working providers (free tier):**

| Provider | Base URL | Notes |
|---|---|---|
| Cerebras | `https://api.cerebras.ai/v1` | Default. Models: `llama3.1-8b`, `gpt-oss-120b` (restricted) |
| Groq | `https://api.groq.com/openai/v1` | 14,400 req/day free. Model: `llama-3.1-8b-instant` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | Model: `gemini-2.5-flash` (250 req/day) |

**Cerebras model IDs** (exact strings — wrong format causes 404):
- `llama3.1-8b` ✓ (note: dot not dash, no space)
- `gpt-oss-120b` ✓ (may require special access on new accounts)
- `qwen-3-235b-a22b-instruct-2507` ✓

---

## How to add a new command

Edit `bot/handlers.py` and add a handler before the catch-all `handle_message`:

```python
@bot.message_handler(commands=["mycommand"])
def cmd_mycommand(message):
    bot.reply_to(message, "Your response here")
```

Also update `/help` in `cmd_help` to list the new command.

---

## How to add a new feature module

1. Create `bot/myfeature.py`
2. Import and call it from `bot/handlers.py`
3. Add tests in `tests/test_myfeature.py` — mock any Redis or AI calls

Do not touch `api/index.py` for new features.

---

## Running tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest tests/ -v
```

Tests use `unittest.mock` to patch external dependencies. `tests/conftest.py` sets fake env vars and mocks `telebot`, `openai`, `upstash_redis`, and `flask` at the `sys.modules` level before any bot module is imported. Individual tests then patch specific module-level names (e.g. `bot.history.redis`) to control return values.

Tests run automatically via GitHub Actions on every push and PR (`.github/workflows/ci.yml`).

---

## Deployment

**Manual:**
```bash
vercel --prod
```

**Automatic (recommended):** Connect the GitHub repo to Vercel via the Vercel dashboard (Settings → Git). Every push to `main` triggers a deploy after GitHub Actions tests pass.

**Setting env vars:**
```bash
vercel env add VARIABLE_NAME --value "value" --force --yes
vercel --prod  # redeploy to apply
```

**Always use `--value` flag** when setting env vars non-interactively. Piping values (e.g. `echo "..." | vercel env add`) adds a trailing newline which breaks URL parsing.

**Registering the Telegram webhook** (run once after deploy or URL change):
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<VERCEL_URL>/api/webhook"
```

**Production URL:** `https://vercel-telegram-bot-theta.vercel.app`

---

## Known gotchas

- **`threaded=False` is required** — see "How the bot works" above
- **Vercel entrypoint filenames** — Vercel only detects Flask apps in specific filenames (`index.py`, `app.py`, `main.py`, etc.). `webhook.py` is not recognised. `api/index.py` is used here
- **`vercel.json` rewrite** — Vercel's file-based routing sends `/api/webhook` requests to a function named `webhook`, not `index`. The rewrite in `vercel.json` maps `/api/webhook` → `/api/index` so Flask receives the request
- **Env var newlines** — always use `--value` flag with Vercel CLI, never pipe values
- **Cerebras model names** — use `llama3.1-8b` not `llama-3.1-8b`. The dot format is required
- **Telegram 4096 char limit** — `send_reply()` in `bot/helpers.py` handles splitting automatically
- **Group chats** — bot only responds when `@mentioned` or replied to. The mention is stripped from the message before sending to AI
