from bot.clients import bot, BOT_INFO
from bot.config import MODEL, RATE_LIMIT
from bot.ai import ask_ai
from bot.helpers import send_reply, should_respond
from bot.history import clear_history
from bot.rate_limit import is_rate_limited


@bot.message_handler(commands=["start"])
def cmd_start(message):
    bot.send_message(message.chat.id, "Hello! I'm your AI assistant. Send me a message to get started.\n\nUse /help to see available commands.")


@bot.message_handler(commands=["help"])
def cmd_help(message):
    bot.send_message(message.chat.id,
        "/start — welcome message\n"
        "/help  — show this message\n"
        "/reset — clear conversation history\n"
        "/about — about this bot"
    )


@bot.message_handler(commands=["reset"])
def cmd_reset(message):
    clear_history(message.from_user.id)
    bot.send_message(message.chat.id, "Conversation cleared. Starting fresh!")


@bot.message_handler(commands=["about"])
def cmd_about(message):
    bot.send_message(message.chat.id, f"Model  : {MODEL}\nStorage: Upstash Redis\nHosting: Vercel")


@bot.message_handler(func=lambda m: True)
def handle_message(message):
    if not should_respond(message):
        return
    if is_rate_limited(message.from_user.id):
        bot.send_message(message.chat.id, f"You've reached the daily limit of {RATE_LIMIT} messages. Try again tomorrow.")
        return
    text = (message.text or "").replace(f"@{BOT_INFO.username}", "").strip()
    try:
        bot.send_chat_action(message.chat.id, "typing")
        reply = ask_ai(message.from_user.id, text)
        bot.send_chat_action(message.chat.id, "typing")
        send_reply(message, reply)
    except Exception as e:
        print(f"Error in handle_message: {e}")
        bot.send_message(message.chat.id, "Something went wrong. Please try again.")
