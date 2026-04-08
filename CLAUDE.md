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
│   └── index.py          # Vercel entrypoint — Flask app + webhook route + secret verification
├── bot/
│   ├── __init__.py
│   ├── config.py         # All env vars and constants (edit this to configure the bot)
│   ├── clients.py        # Instantiates bot, ai, redis clients (do not edit unless adding a client)
│   ├── ai.py             # ask_ai() orchestration — history, search injection, source citations
│   ├── providers.py      # Provider dispatch: OpenAI-compatible (with retry) or HF Gradio space
│   ├── preferences.py    # Per-user provider preference stored in Redis
│   ├── search.py         # Tavily web search with Redis result caching
│   ├── history.py        # get/save/clear conversation history in Redis (graceful degradation)
│   ├── rate_limit.py     # Per-user daily message rate limiting via Redis (graceful degradation)
│   ├── helpers.py        # send_reply() and should_respond() utilities
│   └── handlers.py       # All Telegram command and message handlers — add new commands here
├── tests/
│   ├── conftest.py       # Mocks env vars and external packages (telebot, openai, upstash_redis, flask)
│   ├── test_ai.py        # needs_search(), _call_ai() retry, ask_ai() orchestration + source citations
│   ├── test_handlers.py  # handle_message() — typing, error handling, rate limit, None text
│   ├── test_helpers.py
│   ├── test_history.py   # includes graceful degradation (Redis down) tests
│   ├── test_rate_limit.py # includes graceful degradation test
│   ├── test_search.py    # web_search() including cache hit/miss and Redis failure tests
│   └── test_webhook.py   # webhook secret validation (accept, reject, skip)
├── .github/
│   └── workflows/
│       └── ci.yml        # Runs pytest on every push and pull request
├── .env.example          # Template for required environment variables
├── Makefile              # install / test / deploy shortcuts
├── requirements.txt
├── vercel.json           # Rewrites /api/webhook → api/index.py
├── CLAUDE.md             # Agent-readable project guide (this file)
└── README.md             # Student-facing setup guide
```

---

## How the bot works

1. Telegram sends a POST to `https://<vercel-url>/api/webhook` on every message
2. `vercel.json` rewrites that path to `api/index.py` (Vercel only recognises specific filenames as Flask entrypoints — `index.py` is one of them)
3. `api/index.py` validates the `X-Telegram-Bot-Api-Secret-Token` header (if `WEBHOOK_SECRET` is set), then deserialises the update and passes it to pyTelegramBotAPI
4. pyTelegramBotAPI routes to the correct handler in `bot/handlers.py`
5. For text messages: checks `should_respond()` → checks rate limit → sends typing action → calls `ask_ai()` → sends reply
6. `ask_ai()` loads history from Redis, checks `needs_search()` for keywords, optionally calls `web_search()` (which checks the Redis cache first), prepends results as a system message, calls `_call_ai()` with retry logic, appends source citations to the reply, saves updated history

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
| `TAVILY_API_KEY` | No | — | From tavily.com — enables web search when set |
| `HF_SPACE_ID` | No | — | Hugging Face Gradio space ID (e.g. `edisimon/armgpt-demo`) — enables `/model` command when set |
| `WEBHOOK_SECRET` | No | — | Random string to verify requests come from Telegram |
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

## Web search

Web search is powered by the Tavily Search API (`bot/search.py`) and injected as context in `bot/ai.py`.

- **Opt-in:** only active when `TAVILY_API_KEY` is set. Without it the bot works normally with no code changes needed
- **Safe search:** always `strict` — hardcoded in `bot/search.py`, not configurable
- **How it works:** `needs_search()` checks the user message for keywords (today, latest, news, etc.). If matched, Tavily is called and results are prepended as a system message before the AI call
- **Caching:** results are cached in Redis for 10 minutes by query hash — duplicate queries skip Tavily entirely
- **User visibility:** replies include a **Sources:** footer with clickable `[Title](url)` links for every result used
- **Free tier:** 1,000 searches/month, no credit card required
- **Getting a key:** go to `tavily.com` → sign up → API Keys → Create API Key

**Adding the key to Vercel:**
```bash
vercel env add TAVILY_API_KEY --value "your_key" --force --yes
vercel --prod
```

---

## Multi-provider support

The bot can dispatch requests to one of two providers per user:

1. **`openai`** (default) — any OpenAI-compatible endpoint via `AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL`. Has retry logic (3 attempts with exponential backoff).
2. **`hf`** (optional) — a Hugging Face Gradio space set via `HF_SPACE_ID`. Called via `gradio_client.Client(...).predict(prompt, length, temperature, top_k)`. No retry (HF is slow).

**When `HF_SPACE_ID` is empty, the bot works exactly as before** — the `/model` command is not registered and users always hit the OpenAI-compatible endpoint.

**When `HF_SPACE_ID` is set**, users get a `/model` command:
- `/model` — show current provider + options
- `/model openai` — switch to the OpenAI-compatible endpoint
- `/model hf` — switch to the HF space

Preferences are stored in Redis under `provider:{user_id}` (no TTL). If Redis is down, the bot falls back to `DEFAULT_PROVIDER` (`"openai"`).

**HF provider caveats** — the current target (`edisimon/armgpt-demo`, ArmGPT) has:
- No messages array — `bot/providers.py::_flatten_messages` flattens the last 3 turns into a `"User: ...\nAssistant: ..."` prompt string
- No system prompt support — the system prompt is dropped entirely for HF
- Hardcoded knobs — length=150, temperature=0.8, top_k=40
- No web search — `bot/ai.py::ask_ai` skips Tavily injection when provider is `hf` (the ArmGPT model is Armenian-only; English search results would just pollute the prompt)
- Cold start on free HF tier can take 30–60s while the model downloads

To switch to a different HF space, change `HF_SPACE_ID` and confirm the target space exposes a `/generate` API with the same signature, or adapt `_call_hf` in `bot/providers.py`.

---

## Webhook verification

To block spoofed requests, set a random secret and pass it when registering the webhook:

```bash
vercel env add WEBHOOK_SECRET --value "your_random_secret" --force --yes
vercel --prod
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<VERCEL_URL>/api/webhook&secret_token=your_random_secret"
```

When `WEBHOOK_SECRET` is set, `api/index.py` checks the `X-Telegram-Bot-Api-Secret-Token` header on every request and returns 403 if it does not match. If the variable is not set, verification is skipped (backwards compatible).

---

## Reliability

- **AI retry logic:** `_call_ai()` in `bot/ai.py` retries up to 3 times with exponential backoff (1s, 2s) before raising. Handles transient network errors and rate limit spikes
- **Redis graceful degradation:** all Redis calls in `bot/history.py` and `bot/rate_limit.py` are wrapped in try-except. If Redis is down: history falls back to empty (stateless mode), rate limiting is skipped

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
make install   # creates .venv and installs dependencies
make test      # runs pytest -v
```

Or manually:
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
- **Webhook secret must match** — if `WEBHOOK_SECRET` is set, the same value must be passed as `secret_token` in `setWebhook`. Mismatch causes all updates to return 403 and the bot goes silent
