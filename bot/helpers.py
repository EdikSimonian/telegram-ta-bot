from bot.clients import bot, BOT_INFO
from bot.config import MAX_MSG_LEN


def send_reply(message, text: str) -> None:
    """Split and send reply in chunks if over Telegram's 4096 char limit."""
    for i in range(0, len(text), MAX_MSG_LEN):
        bot.send_message(message.chat.id, text[i:i + MAX_MSG_LEN], parse_mode="Markdown")


def should_respond(message) -> bool:
    """In groups, only respond when mentioned or replied to."""
    if message.chat.type == "private":
        return True
    if message.reply_to_message and message.reply_to_message.from_user.id == BOT_INFO.id:
        return True
    if message.text and f"@{BOT_INFO.username}" in message.text:
        return True
    return False
