"""/leaderboard — per-group quiz scoreboard. Stage 2 stub; Stage 7 fills in."""
from __future__ import annotations

from bot.ta.prepare import Prepared
from bot.ta.state import get_quiz_scores
from bot.ta.tg import send_message


def send_leaderboard(p: Prepared) -> None:
    scores = get_quiz_scores(p.group_key)
    if not scores:
        send_message(p.chat_id, "No quiz scores yet. Play some quizzes first!")
        return
    # Naive render — Stage 7 adds medals, sorting by accuracy, formatting.
    ranked = sorted(
        scores.items(),
        key=lambda kv: (int(kv[1].get("correct", 0)), int(kv[1].get("total", 0))),
        reverse=True,
    )
    lines = ["<b>Leaderboard</b>"]
    for idx, (_uid, data) in enumerate(ranked[:10], start=1):
        name = data.get("firstName") or data.get("username") or "student"
        c, t = int(data.get("correct", 0)), int(data.get("total", 0))
        lines.append(f"{idx}. {name} — {c}/{t}")
    send_message(p.chat_id, "\n".join(lines), parse_mode="HTML")
