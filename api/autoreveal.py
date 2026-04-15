"""POST endpoint that QStash hits 3 minutes after a quiz starts.

Verifies the ``Upstash-Signature`` JWT before doing anything (unsigned
requests could reveal arbitrary chats). Falls through to the same
``reveal_now`` path the /reveal command uses.
"""
from flask import Flask, request

from bot import qstash
from bot.config import PUBLIC_URL
from bot.ta.quiz import reveal_now


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

    reveal_now(chat_id)
    return ("ok", 200)
