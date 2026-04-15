import telebot
from flask import Flask, request
import bot.handlers  # registers all handlers with the bot
from bot.clients import bot
from bot.config import WEBHOOK_SECRET
from bot.deploy_notice import notify_once

app = Flask(__name__)


@app.route("/api/health")
@app.route("/api/index")
def health():
    notify_once()
    return "OK", 200


@app.route("/api/webhook", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if token != WEBHOOK_SECRET:
            return "Forbidden", 403
    notify_once()
    update = telebot.types.Update.de_json(request.get_data(as_text=True))
    bot.process_new_updates([update])
    return "OK", 200
