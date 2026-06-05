import html
import io
import re
import time
import threading
from contextlib import contextmanager
from bot.clients import bot
from bot.config import MAX_MSG_LEN, VOICE_REPLY_MAX_CHARS

# Telegram "typing" chat action expires after ~5 seconds, so re-send it every
# 4 seconds while slow providers (e.g. HF ArmGPT) are generating.
TYPING_REFRESH_SECONDS = 4

# Strip the RAG sources footer before TTS — long URLs read as garbage.
_SOURCES_FOOTER_RE = re.compile(r"\n+\*?\*?Sources:.*$", re.DOTALL | re.IGNORECASE)
# Strip any HTML tags the AI reply included; bot.send_message uses HTML
# parse mode, but Aura-1 should hear plain prose.
_HTML_TAG_RE = re.compile(r"<[^>]+>")
# Strip emoji + pictograph codepoints before TTS — Aura reads them as the
# emoji name or makes garbled sounds. Covers the main Unicode emoji blocks
# plus modifiers/joiners/variation selectors so multi-codepoint emoji
# (e.g. flags, skin-tone, ZWJ sequences) don't leave fragments behind.
_EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001faff"  # symbols, emoticons, transport, extensions
    "\U00002600-\U000027bf"  # misc symbols + dingbats (✅, ☀, ✨, ✔)
    "\U00002300-\U000023ff"  # misc technical (⌚, ⌛)
    "\U00002b00-\U00002bff"  # misc symbols & arrows (⭐, ⬆, ⬇)
    "\U00002900-\U0000297f"  # supplemental arrows-B
    "\U0001f000-\U0001f02f"  # mahjong
    "\U0001f0a0-\U0001f0ff"  # playing cards
    "\U0001f100-\U0001f2ff"  # enclosed alphanumeric / ideographic
    "\U0001f1e6-\U0001f1ff"  # regional indicators (flags)
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0000200c-\U0000200d"  # ZWNJ / ZWJ
    "\U000020e0-\U000020ff"  # combining marks for symbols
    "]+",
    flags=re.UNICODE,
)
# Collapse runs of whitespace that emoji removal can leave behind.
_WHITESPACE_RUN_RE = re.compile(r"[ \t]{2,}")


def _split_for_telegram(text: str, limit: int) -> list[str]:
    """Chunk ``text`` so each piece fits inside ``limit`` chars.

    Prefers line boundaries to avoid splitting inside HTML tags (our reply
    formatter emits one tag per line). Lines longer than ``limit`` fall back
    to fixed-width character chunking — that's only reachable when an LLM
    emits a single 4000+ char line, which the model is told not to do.
    """
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    cur = ""
    for line in text.split("\n"):
        candidate = f"{cur}\n{line}" if cur else line
        if len(candidate) <= limit:
            cur = candidate
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        if len(line) <= limit:
            cur = line
        else:
            for i in range(0, len(line), limit):
                chunks.append(line[i : i + limit])
            cur = ""
    if cur:
        chunks.append(cur)
    return chunks


def _strip_for_speech(text: str) -> str:
    """Render an HTML reply down to plain prose for TTS.

    Order matters: drop the sources footer first so its URL gibberish
    doesn't survive into the spoken output, then strip tags, then unescape
    HTML entities so ``&amp;`` becomes ``&`` etc., then strip emoji so the
    voice doesn't read "white heavy check mark" out loud.
    """
    text = _SOURCES_FOOTER_RE.sub("", text)
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _EMOJI_RE.sub("", text)
    text = _WHITESPACE_RUN_RE.sub(" ", text)
    return text.strip()


def _send_text_chunks(message, text: str) -> None:
    is_group = getattr(message.chat, "type", "private") != "private"
    chunks = _split_for_telegram(text, MAX_MSG_LEN)
    for i, chunk in enumerate(chunks):
        # Citation URLs (RAG sources, blob links) trigger noisy previews
        # in chat. Suppressed always — bot replies are conversational, not
        # link-shares.
        kwargs = {
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if i == 0 and is_group:
            kwargs["reply_to_message_id"] = message.message_id
        bot.send_message(message.chat.id, chunk, **kwargs)


def _send_voice_reply(message, text: str) -> bool:
    """Synthesize ``text`` via Cloudflare Aura-1 and send as a voice message.

    Returns True on success, False to signal the caller should fall back to
    text. Length-gates above ``VOICE_REPLY_MAX_CHARS`` because anything
    longer is unpleasant to listen to in chat.
    """
    spoken = _strip_for_speech(text)
    if not spoken:
        return False
    if len(spoken) > VOICE_REPLY_MAX_CHARS:
        return False
    try:
        from bot import voice as voice_module

        speaker = voice_module.get_active_speaker()
        audio_bytes = voice_module.synthesize(spoken, speaker=speaker)
    except Exception as e:
        print(f"[helpers] voice synthesis failed, falling back to text: {e}")
        return False

    buf = io.BytesIO(audio_bytes)
    buf.name = "reply.mp3"
    is_group = getattr(message.chat, "type", "private") != "private"
    kwargs: dict = {}
    if is_group:
        kwargs["reply_to_message_id"] = message.message_id
    try:
        bot.send_voice(message.chat.id, buf, **kwargs)
    except Exception as e:
        print(f"[helpers] send_voice failed, falling back to text: {e}")
        return False
    return True


def send_reply(message, text: str) -> None:
    """Split and send reply in chunks if over Telegram's 4096 char limit.

    Sends with ``parse_mode="HTML"``. Callers must HTML-escape any untrusted
    content (LLM output, user-supplied strings) before passing it in. Plain
    Markdown was retired because legacy Markdown parses each chunk
    independently and a stray underscore or backtick from the LLM would 400
    the whole message — HTML with explicit escaping survives that.

    In group chats the first chunk replies to the original message so the
    thread stays linked; subsequent chunks post as standalone follow-ups
    (Telegram doesn't chain reply-to through chunks well). DMs don't need
    reply threading — it's already a 1:1 view.

    When the originating message is flagged ``_reply_as_voice`` (set by the
    voice handler), we route through Cloudflare Aura-1 TTS and Telegram
    ``sendVoice``. Falls back silently to text on any synthesis failure or
    if the reply is too long for a coherent voice message.
    """
    # Compare with ``is True`` so MagicMock messages in tests (which auto-
    # generate truthy attrs on access) don't accidentally trigger the
    # voice path. Only the voice handler's explicit boolean assignment
    # activates TTS.
    #
    # When voice mode is on we send BOTH a voice message and the text —
    # students hear the answer and can read along (and skim the sources
    # footer). On synthesis or send_voice failure, the text is the
    # fallback. Either way the same _send_text_chunks runs.
    if getattr(message, "_reply_as_voice", False) is True:
        _send_voice_reply(message, text)
    _send_text_chunks(message, text)


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


def stream_reply(message, on_chunk_factory) -> str | None:
    """Set up streaming Telegram reply, then invoke ``on_chunk_factory``.

    ``on_chunk_factory`` is a callable that receives the ``on_chunk(partial_html)``
    callback and returns the final text (or None if suppressed). The factory
    is called immediately; inside it, invoking ``on_chunk`` sends/edits the
    Telegram message.

    When ``on_chunk(None)`` is called (guardrail suppression), the temporary
    message is deleted if one was sent and the post-stream path is skipped.

    Returns the final text, or None if suppressed or nothing was sent.
    """
    from bot.ta.tg import delete_message as tg_delete_message
    from bot.ta.tg import edit_message as tg_edit_message

    chat_id = message.chat.id
    is_group = getattr(message.chat, "type", "private") != "private"
    message_id = None
    last_edit = 0.0
    final_text = None
    full_text = None  # untruncated text for overflow chunks
    send_error = False
    suppressed = False

    # Kwargs for the initial send — reply_to_message_id only applies here.
    send_kwargs = {
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if is_group:
        send_kwargs["reply_to_message_id"] = message.message_id

    # Kwargs for subsequent edits — no reply_to_message_id (not valid for
    # editMessageText), but same parse_mode and preview settings.
    edit_kwargs = {
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    def on_chunk(partial) -> bool:
        nonlocal message_id, last_edit, final_text, full_text, send_error, suppressed
        # None signal — guardrail suppressed the reply; delete temp message.
        if partial is None:
            suppressed = True
            if message_id:
                tg_delete_message(chat_id, message_id)
            message_id = None
            final_text = None
            full_text = None
            return False
        if not partial:
            return True
        # Track the full text for overflow handling after the factory returns.
        full_text = partial
        safe = _split_for_telegram(partial, MAX_MSG_LEN)[0]
        if message_id is None:
            try:
                sent = bot.send_message(chat_id, safe, **send_kwargs)
                message_id = getattr(sent, "message_id", None)
                send_error = False  # clear on successful send
            except Exception as e:
                print(f"[helpers] stream_reply send_message error: {e}")
                send_error = True
                return False
        else:
            now = time.monotonic()
            if now - last_edit >= 0.2:
                tg_edit_message(chat_id, message_id, safe, **edit_kwargs)
                last_edit = now
        final_text = safe
        return True

    result = on_chunk_factory(on_chunk)

    # Suppressed — skip final edit, overflow, voice, and return None.
    if suppressed:
        return None

    # If the initial send failed, bail — don't return success.
    if send_error:
        return None

    # Final edit — always force it, regardless of throttle timing.
    if message_id and final_text:
        tg_edit_message(chat_id, message_id, final_text, **edit_kwargs)

        # If the answer is longer than one Telegram chunk, send follow-ups
        # (same behavior as the old send_reply / _send_text_chunks).
        if full_text:
            chunks = _split_for_telegram(full_text, MAX_MSG_LEN)
            for extra in chunks[1:]:
                bot.send_message(chat_id, extra, **edit_kwargs)

    # Voice reply: if the originating message was a voice question, synthesize
    # and send voice alongside the text (matches old send_reply behavior).
    if getattr(message, "_reply_as_voice", False) is True and final_text:
        _send_voice_reply(message, final_text)

    return result if result is not None else final_text
