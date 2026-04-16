import threading
from contextlib import contextmanager
from bot.clients import bot, BOT_INFO
from bot.config import MAX_MSG_LEN

# Telegram "typing" chat action expires after ~5 seconds, so re-send it every
# 4 seconds while slow providers (e.g. HF ArmGPT) are generating.
TYPING_REFRESH_SECONDS = 4


def send_reply(message, text: str) -> None:
    """Split and send reply in chunks if over Telegram's 4096 char limit.

    In group chats the first chunk replies to the original message so the
    thread stays linked; subsequent chunks post as standalone follow-ups
    (Telegram doesn't chain reply-to through chunks well). DMs don't need
    reply threading — it's already a 1:1 view.
    """
    is_group = getattr(message.chat, "type", "private") != "private"
    first = True
    for i in range(0, len(text), MAX_MSG_LEN):
        chunk = text[i:i + MAX_MSG_LEN]
        # Citation URLs (RAG sources, blob links) trigger noisy previews
        # in chat. Suppressed always — bot replies are conversational, not
        # link-shares.
        kwargs = {
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        if first and is_group:
            kwargs["reply_to_message_id"] = message.message_id
        bot.send_message(message.chat.id, chunk, **kwargs)
        first = False


@contextmanager
def keep_typing(chat_id: int):
    """Keep the Telegram "typing" indicator alive while the block runs.

    Spawns a background thread that re-sends the typing action every few
    seconds until the context exits, then joins the thread before returning
    so the serverless function can shut down cleanly.
    """
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                bot.send_chat_action(chat_id, "typing")
            except Exception as e:
                print(f"typing indicator error: {e}")
                return
            # Use wait() so we can exit early when stop is set
            if stop.wait(TYPING_REFRESH_SECONDS):
                return

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


def should_respond(message) -> bool:
    """Respond to all messages in private chats and group chats."""
    return True
