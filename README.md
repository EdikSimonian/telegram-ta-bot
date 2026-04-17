# Vercel Telegram Bot — Starter Template

A minimal Python Telegram bot running on Vercel (free tier) with persistent conversation memory via Upstash Redis and AI powered by Cerebras (defaults to `qwen-3-235b-a22b-instruct-2507`, with `llama3.1-8b` and other models available on the free tier).

**Stack:** Python · Flask · pyTelegramBotAPI · OpenAI SDK · Upstash Redis · Vercel

**All services used are free. No credit card required.**

> **Live demo:** <a href="https://t.me/JillWatson_Bot" target="_blank"><img src="https://img.shields.io/badge/Chat%20on-Telegram-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white" alt="Chat on Telegram"/></a>

---

## What you will need

| Service | Purpose | Needed for | Free tier |
|---|---|---|---|
| [Telegram](https://telegram.org) | The bot platform | Everything | Always free |
| [Cerebras](https://cloud.cerebras.ai) | AI API — `qwen-3-235b-a22b-instruct-2507` (default), `llama3.1-8b`, and more | Everything | 1M tokens/day, 30 req/min |
| [GitHub](https://github.com) | Source code | Everything | Always free |
| [Upstash](https://upstash.com) | Redis for conversation memory | Deployment *(optional for local)* | 10,000 req/day |
| [Vercel](https://vercel.com) | Hosting the bot | Deployment | 100GB bandwidth/month |
| [Tavily](https://tavily.com) | Web search *(optional)* | Extras | 1,000 searches/month |
| [UptimeRobot](https://uptimerobot.com) | Keep-warm pings *(optional)* | Extras | 50 monitors, 5-min interval |

---

# Part 1 — Run it on your laptop

You can have the bot replying to your messages on Telegram in about 10 minutes without touching Vercel, Upstash, or any deployment. Perfect for getting started and iterating on changes.

## Step 1 — Create a Telegram bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g. `My AI Bot`) and a username ending in `bot` (e.g. `myai_bot`)
4. BotFather will reply with a **bot token** that looks like `7123456789:AAF...`
5. Save this token — you will need it in Step 4

---

## Step 2 — Get a Cerebras API key

1. Go to [cloud.cerebras.ai](https://cloud.cerebras.ai) and sign up (free, no credit card)
2. Verify your email and log in
3. Click your profile icon (top right) → **API Keys**
4. Click **Create new API key**, give it a name
5. Copy the key (looks like `csk-...`)
6. Save it — you will need it in Step 4

> **Using a different provider?** Any OpenAI-compatible API works. Set `AI_API_KEY` to your provider's key, `AI_BASE_URL` to their base URL, and `AI_MODEL` to the model name.

---

## Step 3 — Fork and clone the repo

1. Create a [GitHub account](https://github.com) if you don't have one
2. Go to the template repo and click **Fork** (top right) to copy it to your account
3. Clone your fork to your computer:

```bash
git clone https://github.com/<your-username>/telegram-vercel-bot.git
cd telegram-vercel-bot
```

---

## Step 4 — Install dependencies and configure `.env`

Create the virtualenv and install Python dependencies:

```bash
make install
```

Then copy the template and fill in the values you saved in Steps 1 and 2:

```bash
cp .env.example .env
```

Open `.env` in your editor and set these two lines:

```
TELEGRAM_BOT_TOKEN=<paste your BotFather token here>
AI_API_KEY=<paste your Cerebras API key here>
```

Leave everything else as-is for now. Upstash Redis is optional — without it the bot runs in **stateless mode** (no conversation memory, no rate limit), which is fine for initial testing.

---

## Step 5 — Run the bot locally

```bash
make run
```

You should see something like:

```
Redis not configured — running in stateless mode (no memory, no rate limit).
Bot @your_bot_username starting in polling mode.
Send your bot a message on Telegram to try it out.
Press Ctrl+C to stop.
```

Open Telegram, find your bot, and send it a message. You'll see each exchange logged in your terminal:

```
[14:32:15] @alice → @your_bot: hello, who are you?
[14:32:17] @your_bot → @alice: Hi! I'm an AI assistant powered by Cerebras.
```

This is the same bot code you'll eventually deploy to Vercel — the only difference is how Telegram delivers messages. Locally we poll; in production Telegram pushes to a webhook. Edit any file in `bot/`, `Ctrl+C` the bot, rerun `make run`, and you'll see your changes immediately.

---

# Part 2 — Deploy it to the internet

Once you have the bot working locally, the next step is to put it on Vercel so it keeps running when your laptop is closed.

## Step 6 — Create an Upstash Redis database *(recommended)*

Upstash gives the bot persistent conversation memory (so it remembers what you said in the previous message) and per-user rate limiting. It's free with no credit card.

1. Go to [upstash.com](https://upstash.com) and sign up
2. Click **Create Database**
3. Give it a name, choose the region closest to you, click **Create**
4. On the database page, scroll to **REST API** section
5. Copy the **UPSTASH_REDIS_REST_URL** and **UPSTASH_REDIS_REST_TOKEN**
6. Paste them into your `.env` file, uncommenting the lines:

```
UPSTASH_REDIS_REST_URL=<paste here>
UPSTASH_REDIS_REST_TOKEN=<paste here>
```

Re-run `make run` and you'll see the "stateless mode" message disappear. Memory and rate limiting are now active locally.

---

## Step 7 — Create a Vercel account and install the CLI

1. Go to [vercel.com](https://vercel.com) and sign up using your GitHub account
2. Install Node.js from [nodejs.org](https://nodejs.org) if you don't have it (required for the Vercel CLI)
3. Install the Vercel CLI:

```bash
npm install -g vercel
```

4. Log in to Vercel from your terminal:

```bash
vercel login
```

Choose **Continue with GitHub** and follow the browser prompt.

---

## Step 8 — First deploy

From inside the project folder:

```bash
vercel
```

When prompted:
- **Set up and deploy?** → `Y`
- **Which scope?** → select your account
- **Link to existing project?** → `N`
- **Project name?** → press Enter to accept default
- **In which directory is your code?** → press Enter (`.`)

After it finishes, Vercel will print your project URL, e.g. `https://telegram-vercel-bot.vercel.app`. Save this URL — you need it for the next step.

---

## Step 9 — Add `PROD_URL` to `.env`

Open `.env` and add (or uncomment) the line:

```
PROD_URL=https://<your-vercel-url-from-step-8>
```

This tells `make push` which Vercel deployment to point the Telegram webhook at. It's a local-only setting — it's never uploaded to Vercel. Without it, `make push` will refuse to run to prevent accidentally pointing the webhook at the wrong bot.

---

## Step 10 — Sync secrets and register the webhook

One command handles everything: it pushes every variable from `.env` to Vercel production, then calls Telegram's `setWebhook` against your new deployment URL.

```bash
make push
```

You'll see a prompt:

```
Update Vercel env vars from .env? [y/N]
```

Answer **`y`** the first time. You'll see each secret pushed one by one, followed by:

```
Registering Telegram webhook → https://your-bot.vercel.app/api/webhook ... ok
```

Now redeploy so Vercel picks up the new env vars:

```bash
make deploy
```

**Your bot is now live on the internet.** Open Telegram, find your bot, and send it a message. Responses now come from Vercel, not your laptop.

> **Tip:** if you ever re-run `make run` locally, it will remove the production webhook so polling can take over. When you're done and want production back, just run `make push` again and answer `n` to the env prompt — it will re-register the webhook without touching your secrets.

---

# Part 3 — Customize it

## Enable web search *(optional)*

The bot can automatically search the web when it needs current information.

1. Go to [tavily.com](https://tavily.com) and sign up (free, no credit card)
2. Click **API Keys** → **Create API Key**
3. Copy the key and add it to `.env`:

```
TAVILY_API_KEY=<your key>
```

4. Push to Vercel and redeploy:

```bash
make push    # answer y to sync the new key
make deploy
```

Safe search is always set to **strict**. Without this key the bot works normally — web search is simply disabled.

When search is used, the bot appends a **Sources:** section with links to every page it used. Results are cached for 10 minutes, so repeated questions don't burn your quota.

---

## Secure the webhook *(optional but recommended)*

Without a webhook secret, anyone who knows your webhook URL can send fake messages to your bot.

1. Generate a random secret:

```bash
openssl rand -hex 16
```

2. Add it to `.env`:

```
WEBHOOK_SECRET=<your secret>
```

3. Push and redeploy — `make push` will automatically include the secret in its `setWebhook` call, so the secret is wired up end-to-end in one step:

```bash
make push
make deploy
```

The bot will now reject any Telegram webhook request that doesn't include the correct secret header.

---

## Keep the bot warm *(optional)*

On Vercel's free tier, serverless functions go to sleep after a few minutes of inactivity. The first message sent to a sleeping bot has to wait for a **cold start** — typically 2–5 seconds of extra latency while Python imports the bot modules. For a chat bot this feels sluggish.

You can mitigate this by pinging the bot's `/api/health` endpoint every few minutes so Vercel keeps a warm instance ready. The bot ships with this endpoint specifically for uptime checks — it returns `OK` 200 without touching Redis, Telegram, or the AI provider, so it's free and safe to hit frequently.

**Set it up with [UptimeRobot](https://uptimerobot.com) (free, no credit card):**

1. Sign up at [uptimerobot.com](https://uptimerobot.com)
2. Click **+ New monitor**
3. Configure:
   - **Monitor Type:** `HTTP(s)`
   - **Friendly Name:** `Telegram bot health`
   - **URL:** `https://<your-vercel-url>/api/health`
   - **Monitoring Interval:** `5 minutes` (the free-tier minimum)
4. Click **Create Monitor**

That's it. UptimeRobot will hit `/api/health` every 5 minutes, which is frequent enough to keep Vercel's free-tier instance from going fully cold. You also get a free status page and email alerts if the bot ever goes down.

> **A few caveats:**
> - This is a workaround, not a guarantee. Vercel may still cold-start occasionally under load-balancer changes.
> - Keeping the bot warm consumes free-tier invocations. 5-minute pings = ~8,640 invocations/month, well within Vercel Hobby's limit (100k/month), but something to be aware of if you combine this with heavy usage.
> - Respect [Vercel's fair use policy](https://vercel.com/docs/limits) — don't run aggressive sub-minute pings on the free tier.

---

## Add a second AI provider *(optional)*

If you set `HF_SPACE_ID` in `.env`, the bot registers a `/model` command that lets users switch between the default provider (`main`) and a Hugging Face Gradio Space (`hf`). This is useful for demoing multiple models in the same bot or for adding a domain-specific model alongside a general one.

```
HF_SPACE_ID=username/space-name
HF_TOKEN=your_hf_token_here   # only for private/gated Spaces
```

Push and redeploy:

```bash
make push
make deploy
```

Users can now run `/model main` or `/model hf` to switch per-user.

---

## Customization reference

| What to change | How |
|---|---|
| Bot personality / instructions | Edit `SYSTEM_PROMPT` in `bot/config.py` |
| AI model | Set `AI_MODEL` env var (free-tier tested: `qwen-3-235b-a22b-instruct-2507`, `llama3.1-8b`, `gpt-oss-120b`) |
| AI provider | Set `AI_BASE_URL` env var (any OpenAI-compatible endpoint) |
| Enable web search | Set `TAVILY_API_KEY` env var (from tavily.com) |
| Secure the webhook | Set `WEBHOOK_SECRET` env var |
| Daily message limit | Set `RATE_LIMIT` env var (default `250`) |
| Add a second provider | Set `HF_SPACE_ID` (and optionally `HF_TOKEN`) — enables `/model` command |
| Conversation memory length | Edit `MAX_HISTORY` in `bot/config.py` |
| Add a new command | Add a handler in `bot/handlers.py` |

---

# Reference

## Project structure

```
telegram-vercel-bot/
├── api/
│   └── index.py          # Entry point — Flask app, webhook route, /api/health, secret verification
├── bot/
│   ├── config.py         # All env vars and constants
│   ├── clients.py        # bot, ai, redis instances (redis is optional)
│   ├── ai.py             # ask_ai orchestration — history, web search injection, source citations
│   ├── providers.py      # Provider dispatch: OpenAI-compatible (with retry) or HF Gradio space
│   ├── preferences.py    # Per-user provider preference stored in Redis
│   ├── search.py         # Tavily web search with Redis result caching
│   ├── history.py        # Conversation memory (Redis, graceful degradation)
│   ├── rate_limit.py     # Per-user rate limiting (graceful degradation)
│   ├── helpers.py        # Utilities (send_reply, keep_typing, should_respond)
│   └── handlers.py       # Telegram commands — add new commands here
├── tests/
│   ├── conftest.py       # Mocks for running tests without real API keys
│   ├── test_ai.py
│   ├── test_providers.py
│   ├── test_preferences.py
│   ├── test_handlers.py
│   ├── test_helpers.py
│   ├── test_history.py
│   ├── test_rate_limit.py
│   ├── test_search.py
│   └── test_webhook.py
├── .github/
│   └── workflows/
│       └── ci.yml        # Runs tests on every push and pull request
├── .env.example          # Copy to .env for local dev (never commit .env)
├── .gitignore
├── Makefile              # install / run / test / push / deploy shortcuts
├── run_local.py          # Local polling entry point (used by `make run`)
├── requirements.txt
├── vercel.json
├── CLAUDE.md             # Agent-readable project guide
└── README.md
```

---

## Make commands

```bash
make install    # set up virtual environment and install dependencies
make run        # run the bot locally via polling (no Vercel needed, reads .env)
make test       # run all tests
make push       # push .env secrets to Vercel + register Telegram webhook (prompts before each step)
make deploy     # deploy to Vercel production
```

---

## Bot commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | List all commands |
| `/reset` | Clear your conversation history |
| `/about` | Show model and hosting info |
| `/model` | Switch AI provider (only available when `HF_SPACE_ID` is set) |

---

## Running tests

```bash
make test
```

Tests run offline against mocked Telegram, OpenAI, and Upstash clients — no real API keys or network access required. The same suite runs automatically via GitHub Actions on every push and pull request.

---

## Advanced local development

If you want to test the Flask webhook path directly instead of polling (e.g. to exercise `/api/webhook` and `/api/health`), you can run the Flask app locally and expose it via [ngrok](https://ngrok.com):

```bash
.venv/bin/flask --app api/index run --port 3000
ngrok http 3000
```

Then re-register the webhook against your ngrok URL:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://<your-ngrok-url>/api/webhook"
```

This is usually only needed when debugging Flask-level concerns; for day-to-day development, `make run` is simpler.
