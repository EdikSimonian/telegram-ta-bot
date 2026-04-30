import hmac

import telebot
from flask import Flask, jsonify, request
import bot.handlers  # registers all handlers with the bot
from bot.clients import bot
from bot.config import BOT_ENV, PERMANENT_ADMIN, WEBHOOK_SECRET
from bot.deploy_notice import notify_once
from bot.ta.state import get_user_chat

app = Flask(__name__)


@app.route("/api/health")
@app.route("/api/index")
def health():
    notify_once()
    return "OK", 200


@app.route("/api/webhook", methods=["POST"])
def webhook():
    # Fail-closed in any non-local environment. Previously we accepted
    # unauthenticated webhooks when WEBHOOK_SECRET was unset; that turned
    # a single-env-var misconfiguration into open exposure of the bot to
    # spoofed updates. Local dev still allows it for run_local.py /
    # ngrok-style flows where setting a secret is friction without value.
    if not WEBHOOK_SECRET:
        if BOT_ENV != "local":
            return "Webhook secret not configured", 500
        # Local: fall through, no header check.
    else:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(token, WEBHOOK_SECRET):
            return "Forbidden", 403
    notify_once()
    update = telebot.types.Update.de_json(request.get_data(as_text=True))
    bot.process_new_updates([update])
    return "OK", 200


@app.route("/api/notify-admin", methods=["POST"])
def notify_admin():
    """DM the permanent admin via the bot.

    Used by GitHub Actions (notably deploy.yml's notify job) so we
    don't have to stash the admin's numeric chat id as a separate
    secret — the bot already learned it from an earlier DM and has
    it in Redis. Auth is via the existing WEBHOOK_SECRET header.
    """
    if not WEBHOOK_SECRET:
        return jsonify(error="WEBHOOK_SECRET not configured"), 500
    token = request.headers.get("X-Webhook-Secret", "")
    if not hmac.compare_digest(token, WEBHOOK_SECRET):
        return "Forbidden", 403

    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify(error="missing text"), 400
    parse_mode = payload.get("parse_mode")  # optional: "HTML" or "Markdown"

    chat_id = get_user_chat(PERMANENT_ADMIN)
    if not chat_id:
        # Admin hasn't DM'd the bot yet, so we don't know their chat id.
        return jsonify(error=f"no chat id on file for @{PERMANENT_ADMIN}"), 404

    try:
        bot.send_message(chat_id, text, parse_mode=parse_mode)
    except Exception as e:
        return jsonify(error=f"send_message failed: {e}"), 502
    return jsonify(ok=True, chat_id=chat_id), 200
