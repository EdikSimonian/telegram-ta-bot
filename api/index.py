import hmac
import sys
import traceback

import telebot
from flask import Flask, jsonify, request
import bot.handlers  # registers all handlers with the bot
from bot.clients import bot
from bot.config import BOT_ENV, PERMANENT_ADMIN, WEBHOOK_SECRET
from bot.deploy_notice import notify_once
from bot.ta import tg
from bot.ta.state import get_user_chat, mark_update_seen

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
    # Idempotency gate: Telegram redelivers an update (same update_id) when
    # the previous attempt didn't ack in time (long streamed answer, function
    # timeout). Ack duplicates immediately instead of re-answering — without
    # this, one slow answer becomes an infinite redelivery loop.
    if update is not None and getattr(update, "update_id", None) is not None:
        if not mark_update_seen(update.update_id):
            return "OK", 200
    # Track Telegram API rejections during this update so a swallowed 400
    # (bad HTML entities, "message too long", flood control) surfaces as a
    # 500 in Vercel instead of a misleading 200. The dedup gate above means a
    # Telegram retry of this same update_id is acked immediately, so returning
    # 500 here does NOT cause a redelivery loop.
    tg.reset_errors()
    try:
        bot.process_new_updates([update])
    except Exception:
        # Non-Telegram bugs: ack 200 (dedup already guards redelivery) but the
        # traceback is printed so it's still visible in Vercel.
        traceback.print_exc()
    tg_errors = tg.errors()
    if tg_errors:
        print(
            f"[WEBHOOK-ERROR] {len(tg_errors)} Telegram rejection(s) on update "
            f"{getattr(update, 'update_id', None)}: {tg_errors}",
            file=sys.stderr,
            flush=True,
        )
        return "Telegram rejected a response", 500
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
