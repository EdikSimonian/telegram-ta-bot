"""QStash callback that refreshes a web-app quiz's "N answered" counter.

Chained: each tick edits the teaser message with the current answered-count
and, while the quiz is still live, schedules the next tick (~15s later). Stops
on its own once the quiz is revealed/expired (``tick_quiz`` returns False).

Verifies the ``Upstash-Signature`` JWT before doing anything — an unsigned
request could spam edits to arbitrary chats.
"""

from flask import Flask, request

from bot import qstash
from bot.config import PUBLIC_URL
from bot.ta.quiz import schedule_quiz_tick, tick_quiz

app = Flask(__name__)


@app.route("/api/quiz-tick", methods=["POST"])
def quiz_tick():
    body = request.get_data() or b""
    expected_url = f"{PUBLIC_URL}/api/quiz-tick" if PUBLIC_URL else None
    payload = qstash.verify_and_parse(dict(request.headers), body, url=expected_url)
    if payload is None:
        return ("unauthorized", 401)

    chat_id = payload.get("chatId")
    q_msg_id = payload.get("questionMessageId")
    token = payload.get("token")
    try:
        seq = int(payload.get("seq", 0) or 0)
    except (TypeError, ValueError):
        seq = 0
    if not chat_id or not token:
        return ("bad request", 400)

    # tick_quiz claims this seq; only the winning delivery schedules seq+1, so a
    # QStash retry can't fork a second tick chain.
    if tick_quiz(chat_id, q_msg_id, token, seq):
        schedule_quiz_tick(chat_id, q_msg_id, token, seq + 1)  # keep the counter live
    return ("ok", 200)
