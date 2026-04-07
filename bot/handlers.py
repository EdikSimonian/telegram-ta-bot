from bot.clients import bot, BOT_INFO
from bot.config import MODEL, RATE_LIMIT, HF_SPACE_ID
from bot.ai import ask_ai
from bot.helpers import keep_typing, send_reply, should_respond
from bot.history import clear_history
from bot.preferences import get_provider, set_provider
from bot.rate_limit import is_rate_limited


@bot.message_handler(commands=["start"])
def cmd_start(message):
    bot.send_message(message.chat.id, "Hello! I'm your AI assistant. Send me a message to get started.\n\nUse /help to see available commands.")


@bot.message_handler(commands=["help"])
def cmd_help(message):
    lines = [
        "/start — welcome message",
        "/help  — show this message",
        "/reset — clear conversation history",
        "/about — about this bot",
    ]
    if HF_SPACE_ID:
        lines.append("/model — switch AI provider")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["reset"])
def cmd_reset(message):
    clear_history(message.from_user.id)
    bot.send_message(message.chat.id, "Conversation cleared. Starting fresh!")


@bot.message_handler(commands=["about"])
def cmd_about(message):
    if HF_SPACE_ID:
        provider = get_provider(message.from_user.id)
        model_line = f"{MODEL} (openai)" if provider == "openai" else f"{HF_SPACE_ID} (hf)"
    else:
        model_line = MODEL
    bot.send_message(message.chat.id, f"Model  : {model_line}\nStorage: Upstash Redis\nHosting: Vercel")


if HF_SPACE_ID:
    @bot.message_handler(commands=["model"])
    def cmd_model(message):
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 1:
            current = get_provider(message.from_user.id)
            bot.send_message(
                message.chat.id,
                f"Current provider: {current}\n\n"
                "Options:\n"
                "/model openai — Cerebras (fast, multilingual, with memory)\n"
                "/model hf — ArmGPT (Armenian only, slow, no memory)",
            )
            return
        choice = parts[1].strip().lower()
        if choice not in ("openai", "hf"):
            bot.send_message(message.chat.id, "Invalid choice. Use: /model openai or /model hf")
            return
        if not set_provider(message.from_user.id, choice):
            bot.send_message(message.chat.id, "Could not save preference. Try again later.")
            return
        if choice == "hf":
            bot.send_message(
                message.chat.id,
                "Switched to hf (ArmGPT).\n\n"
                "Note: this is a tiny base completion model trained only on Armenian text. "
                "It will continue whatever you write rather than answer questions, "
                "and it does not understand English. Replies take ~30-60s and there is no memory.",
            )
        else:
            bot.send_message(message.chat.id, "Switched to openai (Cerebras).")


@bot.message_handler(func=lambda m: True)
def handle_message(message):
    if not should_respond(message):
        return
    if is_rate_limited(message.from_user.id):
        bot.send_message(message.chat.id, f"You've reached the daily limit of {RATE_LIMIT} messages. Try again tomorrow.")
        return
    text = (message.text or "").replace(f"@{BOT_INFO.username}", "").strip()
    try:
        with keep_typing(message.chat.id):
            reply = ask_ai(message.from_user.id, text)
        send_reply(message, reply)
    except Exception as e:
        print(f"Error in handle_message: {e}")
        bot.send_message(message.chat.id, "Something went wrong. Please try again.")
