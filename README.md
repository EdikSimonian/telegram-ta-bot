# Vercel Telegram Bot — Starter Template

A minimal Python Telegram bot running on Vercel (free tier) with persistent conversation memory via Upstash Redis and AI responses via LiteLLM.

**Stack:** Python · Flask · pyTelegramBotAPI · OpenAI SDK · Upstash Redis · Vercel

---

## Prerequisites

- [Vercel account](https://vercel.com) (free)
- [Upstash account](https://upstash.com) (free)
- Telegram account
- LiteLLM API key (provided by your instructor)

---

## Setup

### 1. Create a Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** (looks like `123456:ABC-DEF...`)

### 2. Create an Upstash Redis database

1. Go to [console.upstash.com](https://console.upstash.com)
2. Click **Create Database** → choose a region → create
3. Copy the **REST URL** and **REST Token** from the database details page

### 3. Deploy to Vercel

```bash
# Install Vercel CLI
npm install -g vercel

# Clone this repo
git clone <repo-url>
cd vercel-telegram

# Deploy
vercel
```

When prompted, accept the defaults. After deploy, note your project URL (e.g., `https://your-project.vercel.app`).

### 4. Set environment variables on Vercel

```bash
vercel env add TELEGRAM_BOT_TOKEN
vercel env add LITELLM_API_KEY
vercel env add UPSTASH_REDIS_REST_URL
vercel env add UPSTASH_REDIS_REST_TOKEN
```

Paste the values from steps 1–2 when prompted. Then redeploy to apply:

```bash
vercel --prod
```

### 5. Register the Telegram webhook

Replace `<YOUR_BOT_TOKEN>` and `<YOUR_VERCEL_URL>` and run once:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://<YOUR_VERCEL_URL>/api/webhook"
```

You should see `{"ok":true,"result":true}`.

---

## Project structure

```
vercel-telegram/
├── api/
│   └── webhook.py      # All bot logic lives here
├── .env.example        # Copy to .env for local dev (never commit .env)
├── .gitignore
├── requirements.txt
├── vercel.json
└── README.md
```

---

## Local development

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your values
flask --app api/webhook run --port 3000
```

For local testing with Telegram, use [ngrok](https://ngrok.com) to expose your local server, then re-run the `setWebhook` command with your ngrok URL.

---

## Customisation

| What to change | Where |
|---|---|
| Bot personality / instructions | `SYSTEM_PROMPT` in `api/webhook.py` |
| AI model | `MODEL` in `api/webhook.py` |
| Conversation memory length | `MAX_HISTORY` in `api/webhook.py` |
| Add a new command | Add a `@bot.message_handler(commands=["yourcommand"])` function |

---

## Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | List commands |
| `/reset` | Clear your conversation history |
| `/about` | Show model and hosting info |
