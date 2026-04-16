"""POST endpoint that QStash hits 3 minutes after a quiz starts.

Verifies the ``Upstash-Signature`` JWT before doing anything (unsigned
requests could reveal arbitrary chats). Falls through to the same
``reveal_now`` path the /reveal command uses.
"""
from flask import Flask, request

from bot import qstash
from bot.config import PUBLIC_URL
from bot.ta.quiz import reveal_now
from bot.ta.state import get_active_quiz


app = Flask(__name__)


@app.route("/api/autoreveal", methods=["POST"])
def autoreveal():
    body = request.get_data() or b""
    # Build the expected URL for `sub` claim verification. QStash signs
    # with the callback URL used at publish-time, so this MUST match.
    expected_url = f"{PUBLIC_URL}/api/autoreveal" if PUBLIC_URL else None

    payload = qstash.verify_and_parse(
        dict(request.headers),
        body,
        url=expected_url,
    )
    if payload is None:
        return ("unauthorized", 401)

    chat_id = payload.get("chatId")
    if not chat_id:
        return ("bad request", 400)

    # Guard: only reveal if the CURRENT active quiz matches the one this
    # callback was scheduled for. Without this, a stale callback from
    # Quiz A (manually /reveal'd early) would reveal Quiz B.
    expected_msg_id = payload.get("questionMessageId")
    if expected_msg_id is not None:
        active = get_active_quiz(chat_id)
        if active is None:
            return ("quiz already ended", 200)
        if active.get("questionMessageId") != expected_msg_id:
            return ("stale callback — different quiz active", 200)

    reveal_now(chat_id)
    return ("ok", 200)
