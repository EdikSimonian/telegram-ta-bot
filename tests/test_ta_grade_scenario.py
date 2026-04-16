"""End-to-end /grade scenario: 20 students, 30 quizzes, varied participation.

Simulates real event flow (messages + quiz answers) through a fake Redis,
then runs /grade and verifies:
  1. Every student appears in the summary
  2. Students are ordered by total_pts descending
  3. Each rendered total matches the engagement formula exactly
  4. The single-user detail view (/grade @username) reports the same numbers
"""
from __future__ import annotations

import re
import time
from unittest.mock import MagicMock, patch


class FakeRedis:
    """Minimal in-memory Redis double covering the ops bot/ta/state uses."""

    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}
        self.strings: dict[str, str] = {}

    def hset(self, key, values=None, **_):
        h = self.hashes.setdefault(key, {})
        for f, v in (values or {}).items():
            h[f] = v
        return len(values or {})

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hincrby(self, key, field, amount):
        h = self.hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, 0)) + amount)
        return int(h[field])

    def incr(self, key):
        self.strings[key] = str(int(self.strings.get(key, 0)) + 1)
        return int(self.strings[key])

    def get(self, key):
        return self.strings.get(key)

    def set(self, key, value, **_):
        self.strings[key] = str(value)
        return True

    def delete(self, *keys):
        for k in keys:
            self.hashes.pop(k, None)
            self.strings.pop(k, None)
        return len(keys)


# Deterministic 20-student profile. Distinct totals so sort order is unambiguous.
def _students():
    out = []
    for i in range(1, 21):
        out.append({
            "user_id":    1000 + i,
            "username":   f"s{i:02d}",
            "first_name": f"Stu{i:02d}",
            "messages":   i * 2,            # 2..40 (some below cap, some above)
            "attempts":   i,                # 1..20 attempts out of 30 quizzes
            "correct":    max(0, i - 5),    # 0 for first 5, scales up after
        })
    return out


def _expected_total(s, total_quizzes):
    m_pts = min(s["messages"], 20) / 20 * 30
    p_pts = s["attempts"] / total_quizzes * 40 if total_quizzes else 0
    a_pts = (s["correct"] / s["attempts"]) * 30 if s["attempts"] else 0
    return m_pts + p_pts + a_pts


def _prepared(*, command_args="", group_key="-100999"):
    p = MagicMock()
    p.user_id = 42
    p.username = "alice"
    p.chat_id = 42
    p.command = "grade"
    p.command_args = command_args
    p.group_key = group_key
    p.is_dm = True
    msg = MagicMock()
    msg.message_id = 100
    p.message = msg
    return p


def _populate(fake, students, group_key, total_quizzes):
    """Drive state.py writes the same way the router/quiz handlers do."""
    with patch("bot.ta.state.redis", fake):
        from bot.ta.state import (
            bump_message_count,
            bump_total_quizzes,
            record_quiz_score,
        )
        for _ in range(total_quizzes):
            bump_total_quizzes(group_key)
        for s in students:
            for _ in range(s["messages"]):
                bump_message_count(group_key, s["user_id"], s["username"], s["first_name"])
            for j in range(s["attempts"]):
                record_quiz_score(
                    group_key, s["user_id"], s["username"], s["first_name"],
                    correct=(j < s["correct"]),
                )


# ── Group summary: 20 students, 30 quizzes ────────────────────────────────
def test_grade_scenario_20_students_30_quizzes():
    fake = FakeRedis()
    group_key = "-100999"
    students = _students()
    total_quizzes = 30
    _populate(fake, students, group_key, total_quizzes)

    with patch("bot.ta.state.redis", fake), \
         patch("bot.ta.commands.send_message") as sm:
        from bot.ta.commands import _cmd_grade
        _cmd_grade(_prepared())
        text = sm.call_args.args[1]

    # Header reflects quiz count.
    assert "Quizzes posted: 30" in text

    # Every student is present.
    for s in students:
        assert s["first_name"] in text, f"{s['first_name']} missing"

    # Expected descending order by total_pts.
    ranked = sorted(students, key=lambda s: _expected_total(s, total_quizzes), reverse=True)

    # Verify order: each subsequent name appears later in text.
    last_idx = -1
    for s in ranked:
        idx = text.index(s["first_name"])
        assert idx > last_idx, f"{s['first_name']} out of order"
        last_idx = idx

    # Verify rendered total for every student matches formula rounded to :.0f.
    for s in students:
        expected = f"{_expected_total(s, total_quizzes):.0f}"
        m = re.search(
            rf"\u2022 [^\n]*{re.escape(s['first_name'])}[^\n]*<b>(\d+)</b>",
            text,
        )
        assert m, f"no rendered total for {s['first_name']}"
        assert m.group(1) == expected, (
            f"{s['first_name']}: expected {expected} pts, got {m.group(1)}"
        )

    # Top scorer is Stu20 (i=20 has max messages/attempts/correct).
    assert ranked[0]["first_name"] == "Stu20"
    # Bottom scorer is Stu01.
    assert ranked[-1]["first_name"] == "Stu01"


# ── Single-user detail view pulls the same numbers ────────────────────────
def test_grade_scenario_single_student_detail_matches_formula():
    fake = FakeRedis()
    group_key = "-100999"
    students = _students()
    total_quizzes = 30
    _populate(fake, students, group_key, total_quizzes)

    target = next(s for s in students if s["username"] == "s10")

    with patch("bot.ta.state.redis", fake), \
         patch("bot.ta.commands.send_message") as sm:
        from bot.ta.commands import _cmd_grade
        _cmd_grade(_prepared(command_args="@s10"))
        text = sm.call_args.args[1]

    assert target["first_name"] in text
    # Total points line.
    m = re.search(r"Total:\s*<b>(\d+)/100</b>", text)
    assert m, f"no total in detail view:\n{text}"
    assert m.group(1) == f"{_expected_total(target, total_quizzes):.0f}"

    # Participation line reports attempts / total_quizzes.
    assert f"{target['attempts']}/{total_quizzes} quizzes" in text
    # Accuracy line reports correct / attempts.
    assert f"{target['correct']}/{target['attempts']} correct" in text
