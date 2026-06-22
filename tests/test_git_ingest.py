"""git_ingest batch pipeline — time-boxing so chunk-heavy repos don't stall.

Regression: 20 chunk-heavy code files spent ~57s just fetching+embedding,
busting Vercel's 60s cap before the follow-up batch was published, so ingest
stalled partway. process_batch now stops at a wall-clock budget and chains the
remainder instead of taking a fixed file slice.
"""

from unittest.mock import patch


def _paths(n):
    return [{"path": f"f{i}.py", "sha": f"sha{i}"} for i in range(n)]


def test_process_batch_time_boxes_and_chains_remainder():
    import bot.ta.git_ingest as gi

    clock = {"t": 0.0}
    captured = {}

    def slow_ingest(*a, **k):
        clock["t"] += 4.0  # each file "costs" 4s of embedding round-trips
        return True

    def capture_publish(url, body, delay_seconds=0):
        captured["paths"] = body["paths"]
        captured["added"] = body["added"]
        return "msg-id"

    with (
        patch.object(gi.time, "monotonic", lambda: clock["t"]),
        patch.object(gi, "ingest_one_file", slow_ingest),
        patch.object(gi.qstash, "publish", capture_publish),
        patch.object(gi, "get_git_repo", lambda *a: {}),
        patch.object(gi, "add_git_repo", lambda *a: None),
    ):
        summary = gi.process_batch(
            {
                "owner": "o",
                "repo": "r",
                "branch": "main",
                "paths": _paths(26),
                "added": 0,
                "skipped": 0,
                "notifyChatId": "",
                "addedBy": "x",
            }
        )

    budget = gi.BATCH_TIME_BUDGET_SECONDS
    processed = 26 - len(captured["paths"])
    # Stopped on the first file that pushed cumulative cost past the budget —
    # not a fixed count, and not unbounded.
    assert (processed - 1) * 4 < budget <= processed * 4
    assert summary["phase"] == "continued"
    assert summary["remaining"] == 26 - processed
    assert summary["added"] == processed
    assert captured["added"] == processed  # carried counters propagate forward


def test_process_batch_caps_at_batch_size_when_files_are_fast():
    """Instant files still stop at the BATCH_SIZE hard cap (not unbounded)."""
    import bot.ta.git_ingest as gi

    captured = {}
    with (
        patch.object(gi.time, "monotonic", lambda: 0.0),
        patch.object(gi, "ingest_one_file", lambda *a, **k: True),
        patch.object(
            gi.qstash,
            "publish",
            lambda url, body, delay_seconds=0: (
                captured.update(paths=body["paths"]) or "m"
            ),
        ),
        patch.object(gi, "get_git_repo", lambda *a: {}),
        patch.object(gi, "add_git_repo", lambda *a: None),
    ):
        summary = gi.process_batch(
            {
                "owner": "o",
                "repo": "r",
                "branch": "main",
                "paths": _paths(50),
                "added": 0,
                "skipped": 0,
                "notifyChatId": "",
                "addedBy": "x",
            }
        )
    assert summary["phase"] == "continued"
    assert 50 - len(captured["paths"]) == gi.BATCH_SIZE


def test_process_batch_completes_and_marks_done():
    """When everything fits, no follow-up is published and phase is 'done'."""
    import bot.ta.git_ingest as gi

    published = []
    with (
        patch.object(gi.time, "monotonic", lambda: 0.0),
        patch.object(gi, "ingest_one_file", lambda *a, **k: True),
        patch.object(gi.qstash, "publish", lambda *a, **k: published.append(1) or "m"),
        patch.object(gi, "get_git_repo", lambda *a: {}),
        patch.object(gi, "add_git_repo", lambda *a: None),
    ):
        summary = gi.process_batch(
            {
                "owner": "o",
                "repo": "r",
                "branch": "main",
                "paths": _paths(3),
                "added": 0,
                "skipped": 0,
                "notifyChatId": "",
                "addedBy": "x",
            }
        )
    assert summary == {"phase": "done", "added": 3, "skipped": 0, "remaining": 0}
    assert published == []  # nothing chained
