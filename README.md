# Vercel Telegram Bot — Starter Template

A minimal Python Telegram bot running on Vercel (free tier) with persistent conversation memory via Upstash Redis and AI powered by Cerebras (llama3.1-8b).

**Stack:** Python · Flask · pyTelegramBotAPI · OpenAI SDK · Upstash Redis · Vercel

**All services used are free. No credit card required.**

---

## What you will need to create

| Service | Purpose | Free tier |
|---|---|---|
| [Telegram](https://telegram.org) | The bot platform | Always free |
| [Cerebras](https://cloud.cerebras.ai) | AI API (llama3.1-8b) | 1M tokens/day, 30 req/min |
| [Upstash](https://upstash.com) | Redis for conversation memory | 10,000 req/day |
| [Vercel](https://vercel.com) | Hosting the bot | 100GB bandwidth/month |
| [GitHub](https://github.com) | Source code (Vercel deploys from here) | Always free |

---

## Step 1 — Create a Telegram bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g. `My AI Bot`) and a username ending in `bot` (e.g. `myai_bot`)
4. BotFather will reply with a **bot token** that looks like `7123456789:AAF...`
5. Save this token — you will need it later

---

## Step 2 — Get a Cerebras API key

1. Go to [cloud.cerebras.ai](https://cloud.cerebras.ai) and sign up (free, no credit card)
2. Verify your email and log in
3. Click your profile icon (top right) → **API Keys**
4. Click **Create new API key**, give it a name
5. Copy the key (looks like `csk-...`)
6. Save it — you will need it later

> **Using a different provider?** Any OpenAI-compatible API works. Set `AI_API_KEY` to your provider's key, `AI_BASE_URL` to their base URL, and `AI_MODEL` to the model name.

---

## Step 3 — Create an Upstash Redis database

1. Go to [upstash.com](https://upstash.com) and sign up (free, no credit card)
2. Click **Create Database**
3. Give it a name, choose the region closest to you, click **Create**
4. On the database page, scroll to **REST API** section
5. Copy the **UPSTASH_REDIS_REST_URL** and **UPSTASH_REDIS_REST_TOKEN**
6. Save both — you will need them later

---

## Step 4 — Set up GitHub and clone the repo

1. Create a [GitHub account](https://github.com) if you don't have one
2. Go to the template repo and click **Fork** (top right) to copy it to your account
3. Clone your fork to your computer:

```bash
git clone https://github.com/<your-username>/VercelTelegramBot.git
cd VercelTelegramBot
```

---

## Step 5 — Create a Vercel account and install the CLI

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

## Step 6 — Deploy to Vercel

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

After it finishes, Vercel will print your project URL, e.g. `https://vercel-telegram-bot.vercel.app`. Save this URL.

---

## Step 7 — Add environment variables to Vercel

Run each command below and paste the corresponding value when prompted:

```bash
vercel env add TELEGRAM_BOT_TOKEN
vercel env add AI_API_KEY
vercel env add UPSTASH_REDIS_REST_URL
vercel env add UPSTASH_REDIS_REST_TOKEN
```

For each one, select **Production**, **Preview**, and **Development** when asked which environments to apply to.

Then redeploy to apply the variables:

```bash
vercel --prod
```

---

## Step 8 — Register the Telegram webhook

This tells Telegram where to send messages. Run the command below, replacing the placeholders:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://<YOUR_VERCEL_URL>/api/webhook"
```

Example:
```bash
curl "https://api.telegram.org/bot7123456789:AAF.../setWebhook?url=https://vercel-telegram-bot.vercel.app/api/webhook"
```

You should see: `{"ok":true,"result":true}`

**Your bot is now live.** Open Telegram, find your bot, and send it a message.

---

## Project structure

```
VercelTelegramBot/
├── api/
│   └── index.py        # All bot logic lives here
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
cp .env.example .env    # fill in your real values
flask --app api/index run --port 3000
```

To test with Telegram locally, install [ngrok](https://ngrok.com), then:

```bash
ngrok http 3000
```

Copy the `https://...ngrok-free.app` URL and re-run the `setWebhook` curl from Step 8 with that URL instead.

---

## Customisation

| What to change | How |
|---|---|
| Bot personality / instructions | Edit `SYSTEM_PROMPT` in `api/index.py` |
| AI model | Set `AI_MODEL` env var (e.g. `llama3.1-8b`, `gpt-oss-120b`) |
| AI provider | Set `AI_BASE_URL` env var (any OpenAI-compatible endpoint) |
| Conversation memory length | Edit `MAX_HISTORY` in `api/index.py` |
| Add a new command | Add a `@bot.message_handler(commands=["yourcommand"])` function |

---

## Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | List all commands |
| `/reset` | Clear your conversation history |
| `/about` | Show model and hosting info |
