"""Engagement scoring used by /stats and /grade.

Breakdown (spec §5.3):
    30% — message count capped at 20
    40% — quiz participation (attempts / total quizzes posted)
    30% — quiz accuracy (correct / attempted)

Students inactive for more than 7 days are flagged ⚠️ so instructors can
notice check-outs early.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


INACTIVE_SECONDS = 7 * 24 * 3600
MESSAGE_CAP      = 20
W_MESSAGES       = 30
W_PARTICIPATION  = 40
W_ACCURACY       = 30


@dataclass
class Engagement:
    user_id:       str
    username:      str | None
    first_name:    str | None
    messages:      int
    last_active:   int
    attempts:      int
    correct:       int
    total_quizzes: int
    messages_pts:  float
    particip_pts:  float
    accuracy_pts:  float
    total_pts:     float
    inactive:      bool

    @property
    def display_name(self) -> str:
        return self.first_name or self.username or f"user:{self.user_id}"

    @property
    def accuracy_pct(self) -> float:
        return 100.0 * self.correct / self.attempts if self.attempts else 0.0

    @property
    def participation_pct(self) -> float:
        return 100.0 * self.attempts / self.total_quizzes if self.total_quizzes else 0.0


def compute(
    user_id: str,
    stat_entry: dict | None,
    score_entry: dict | None,
    total_quizzes: int,
    *,
    now: int | None = None,
) -> Engagement:
    """Build an ``Engagement`` record from raw Redis hash values."""
    ts = int(now if now is not None else time.time())
    stat_entry = stat_entry or {}
    score_entry = score_entry or {}

    messages   = int(stat_entry.get("messageCount", 0))
    last_active = int(stat_entry.get("lastActive", 0))
    attempts   = int(score_entry.get("total", 0))
    correct    = int(score_entry.get("correct", 0))

    # Weighted components.
    m_pts = (min(messages, MESSAGE_CAP) / MESSAGE_CAP) * W_MESSAGES if MESSAGE_CAP else 0.0
    p_pts = (attempts / total_quizzes) * W_PARTICIPATION if total_quizzes else 0.0
    a_pts = (correct / attempts) * W_ACCURACY if attempts else 0.0

    inactive = last_active > 0 and (ts - last_active) > INACTIVE_SECONDS
    return Engagement(
        user_id=str(user_id),
        username=stat_entry.get("username") or score_entry.get("username"),
        first_name=stat_entry.get("firstName") or score_entry.get("firstName"),
        messages=messages,
        last_active=last_active,
        attempts=attempts,
        correct=correct,
        total_quizzes=total_quizzes,
        messages_pts=m_pts,
        particip_pts=p_pts,
        accuracy_pts=a_pts,
        total_pts=m_pts + p_pts + a_pts,
        inactive=inactive,
    )


def compute_all(
    stats: dict[str, dict],
    scores: dict[str, dict],
    total_quizzes: int,
    *,
    now: int | None = None,
) -> list[Engagement]:
    """Build one Engagement per student we've seen in either stats or scores."""
    uids = set(stats.keys()) | set(scores.keys())
    out: list[Engagement] = []
    for uid in uids:
        out.append(compute(uid, stats.get(uid), scores.get(uid), total_quizzes, now=now))
    return out
