import os
import json
from flask import Flask, request
import telebot
from openai import OpenAI
from upstash_redis import Redis

# ── Configuration ──────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
UPSTASH_URL    = os.environ["UPSTASH_REDIS_REST_URL"]
UPSTASH_TOKEN  = os.environ["UPSTASH_REDIS_REST_TOKEN"]

MODEL         = "gemini-2.0-flash"
GEMINI_BASE   = "https://generativelanguage.googleapis.com/v1beta/openai/"
SYSTEM_PROMPT = "You are a helpful assistant."
MAX_HISTORY   = 20  # number of messages kept per user (10 conversation turns)

# ── Clients ────────────────────────────────────────────────────────────────────
bot   = telebot.TeleBot(TELEGRAM_TOKEN)
ai    = OpenAI(base_url=GEMINI_BASE, api_key=GOOGLE_API_KEY)
redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)
app   = Flask(__name__)

# ── Redis helpers ──────────────────────────────────────────────────────────────
def get_history(user_id: int) -> list:
    data = redis.get(f"chat:{user_id}")
    return json.loads(data) if data else []

def save_history(user_id: int, history: list) -> None:
    redis.set(f"chat:{user_id}", json.dumps(history[-MAX_HISTORY:]))

def clear_history(user_id: int) -> None:
    redis.delete(f"chat:{user_id}")

# ── AI ─────────────────────────────────────────────────────────────────────────
def ask_ai(user_id: int, user_message: str) -> str:
    history = get_history(user_id)
    history.append({"role": "user", "content": user_message})

    response = ai.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
    )

    reply = response.choices[0].message.content
    history.append({"role": "assistant", "content": reply})
    save_history(user_id, history)
    return reply

# ── Telegram command handlers ──────────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def cmd_start(message):
    bot.reply_to(
        message,
        "Hello! I'm your AI assistant.\nSend me any message to get started.\n\nUse /help to see available commands.",
    )

@bot.message_handler(commands=["help"])
def cmd_help(message):
    bot.reply_to(
        message,
        "/start  — welcome message\n"
        "/help   — show this message\n"
        "/reset  — clear conversation history\n"
        "/about  — about this bot",
    )

@bot.message_handler(commands=["reset"])
def cmd_reset(message):
    clear_history(message.from_user.id)
    bot.reply_to(message, "Conversation cleared. Starting fresh!")

@bot.message_handler(commands=["about"])
def cmd_about(message):
    bot.reply_to(
        message,
        f"Model  : {MODEL}\nStorage: Upstash Redis\nHosting: Vercel",
    )

# ── Message handler ────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: True)
def handle_message(message):
    try:
        reply = ask_ai(message.from_user.id, message.text)
        bot.reply_to(message, reply)
    except Exception:
        bot.reply_to(message, "Something went wrong. Please try again.")

# ── Webhook endpoint ───────────────────────────────────────────────────────────
@app.route("/api/webhook", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(request.get_data(as_text=True))
    bot.process_new_updates([update])
    return "OK", 200
