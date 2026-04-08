from bot.clients import bot, BOT_INFO
from bot.config import (
    MODEL, RATE_LIMIT, HF_SPACE_ID, ARMGPT_BASE_URL, ARMGPT_API_KEY, ARMGPT_MODEL,
)
from bot.ai import ask_ai
from bot.helpers import keep_typing, send_reply, should_respond
from bot.history import clear_history
from bot.preferences import enabled_providers, get_provider, set_provider
from bot.rate_limit import is_rate_limited

# /model is only useful when at least one alternative provider is configured
_MODEL_COMMAND_ENABLED = len(enabled_providers()) > 1
print(f"[handlers] enabled_providers={enabled_providers()} model_cmd_enabled={_MODEL_COMMAND_ENABLED}")

# Per-provider description shown in /model
_PROVIDER_LABELS = {
    "openai": "Cerebras (fast, multilingual, with memory)",
    "hf": "ArmGPT on Hugging Face (Armenian only, slow ~30s, no memory)",
    "armgpt": "ArmGPT on Modal (Armenian only, fast ~3s, no memory)",
}


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
    if _MODEL_COMMAND_ENABLED:
        lines.append("/model — switch AI provider")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["reset"])
def cmd_reset(message):
    clear_history(message.from_user.id)
    bot.send_message(message.chat.id, "Conversation cleared. Starting fresh!")


@bot.message_handler(commands=["about"])
def cmd_about(message):
    if _MODEL_COMMAND_ENABLED:
        provider = get_provider(message.from_user.id)
        if provider == "openai":
            model_line = f"{MODEL} (openai)"
        elif provider == "hf":
            model_line = f"{HF_SPACE_ID} (hf)"
        elif provider == "armgpt":
            model_line = f"{ARMGPT_MODEL} (armgpt)"
        else:
            model_line = MODEL
    else:
        model_line = MODEL
    bot.send_message(message.chat.id, f"Model  : {model_line}\nStorage: Upstash Redis\nHosting: Vercel")


if _MODEL_COMMAND_ENABLED:
    @bot.message_handler(commands=["model"])
    def cmd_model(message):
        available = enabled_providers()
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 1:
            current = get_provider(message.from_user.id)
            options = "\n".join(f"/model {p} — {_PROVIDER_LABELS[p]}" for p in available)
            bot.send_message(
                message.chat.id,
                f"Current provider: {current}\n\nOptions:\n{options}",
            )
            return
        choice = parts[1].strip().lower()
        if choice not in available:
            valid = ", ".join(available)
            bot.send_message(message.chat.id, f"Invalid choice. Use one of: {valid}")
            return
        if not set_provider(message.from_user.id, choice):
            bot.send_message(message.chat.id, "Could not save preference. Try again later.")
            return
        if choice == "armgpt":
            bot.send_message(
                message.chat.id,
                "Switched to armgpt (ArmGPT on Modal).\n\n"
                "Note: this model only understands Armenian, replies are fast (~3s), "
                "and each message is treated independently (no conversation memory).",
            )
        elif choice == "hf":
            bot.send_message(
                message.chat.id,
                "Switched to hf (ArmGPT on Hugging Face).\n\n"
                "Note: this is a tiny base completion model trained only on Armenian text. "
                "It will continue whatever you write rather than answer questions, "
                "and it does not understand English. Replies take ~30-60s and there is no memory.",
            )
        else:
            bot.send_message(message.chat.id, "Switched to openai (Cerebras).")


@bot.message_handler(func=lambda m: True)
def handle_message(message):
    print(f"[handle_message] user={message.from_user.id} chat={message.chat.id} text={(message.text or '')[:60]!r}")
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
