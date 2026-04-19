#!/usr/bin/env python3
"""Call OpenAI to review a PR diff; emit the review as markdown.

Invoked from .github/workflows/pr-review.yml. Reads four files passed
on the command line and prints the review to stdout for `gh pr comment`
to post.

    usage: review_pr.py <diff> <pr.json> <CLAUDE.md> <prior_reviews.json>

`prior_reviews.json` is a JSON array of strings — the bodies of every
previous OpenAI review posted on this PR, oldest first. May be empty.

Required env: OPENAI_API_KEY
Optional env: OPENAI_MODEL  (defaults to gpt-5.4)
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

from openai import OpenAI


# Token-budget guards. GitHub diffs get huge, CLAUDE.md is long, prior
# reviews can stack up across retries. Truncation markers are appended
# inside each blob so the model knows context was cut.
_MAX_DIFF_CHARS          = 30_000
_MAX_CLAUDE_CHARS        = 6_000
_MAX_BODY_CHARS          = 4_000
_MAX_PRIOR_REVIEW_CHARS  = 4_000   # per-review cap
_MAX_PRIOR_REVIEWS_TOTAL = 20_000  # total cap across all prior reviews


SYSTEM_PROMPT = """\
You are a senior code reviewer for a Python Telegram bot deployed on Vercel.
You review pull requests opened by an automated self-upgrade routine (Claude
Code). Your review is part of a loop: if you request changes, the routine
gets another attempt (max 3) to address your concerns on the SAME PR branch.

REVIEW RULES — internalise these:

(a) Be comprehensive in a SINGLE pass. Flag every issue you see in the
    current PR state in this one review. Never hold back a concern to
    raise later. If there are 7 issues, list all 7 now.

(b) Prior reviews on this PR (if any) will be provided below. For any
    concern from a prior review that is STILL present in the current diff,
    write ONE line: "Still present: <short gist> (see prior review)". Do
    NOT re-elaborate, re-quote code, or repeat suggested fixes — the
    routine already has that context. Your prose belongs on NEW issues
    and on NEWLY-RESOLVED ones ("Resolved: <gist>").

(c) Focus (in this order):
    1. Intent match — does the diff actually accomplish what the PR body
       says?
    2. Security — command injection, secret leaks, over-broad permissions,
       missing webhook verification, ReDoS, etc.
    3. Correctness — bugs, off-by-ones, wrong types, missing None-checks
       at boundaries, unhandled error paths that should be handled.
    4. Test coverage — are new tests meaningful? Any obvious edge case
       missing? Demand at least the happy path + one failure path.
    5. Project conventions — violations of patterns in CLAUDE.md.
    6. Scope — drive-by refactors or abstractions beyond the task.

(d) Be concrete. Cite file paths and line ranges from the diff hunks.
    When you suggest a change, show the corrected code.

(e) Do NOT:
    - Praise the PR or pad with compliments.
    - Restate what the diff does — the maintainer reads the diff.
    - Raise style-only nits a linter would catch.
    - Invent issues. If a section has nothing to report, write "None.".

OUTPUT FORMAT (GitHub-flavored Markdown, nothing else):

## 🤖 OpenAI review

**Intent match:** <one sentence — does the code match the stated intent?>

**Concerns**
<bulleted list, or "None.". Use "Still present: ..." for unresolved prior concerns.>

**Test coverage**
<bulleted list or "None.">

**Suggestions**
<bulleted list or "None.">

**Resolved since last review**
<bulleted list of prior concerns now fixed, or "N/A" if this is the first review.>

**Verdict:** one of ✅ approve / ⚠️ request changes / 🛑 block — with a short reason.
"""


def _truncate(text: str, limit: int, label: str) -> str:
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n\n[...{label} truncated, {omitted} chars omitted]"


def _format_prior_reviews(reviews: list[str]) -> str:
    """Render prior reviews for the user prompt, respecting budgets."""
    if not reviews:
        return "(none — this is the first review of this PR)"

    rendered: list[str] = []
    total = 0
    for i, body in enumerate(reviews, start=1):
        snippet = _truncate(
            (body or "").strip(),
            _MAX_PRIOR_REVIEW_CHARS,
            f"prior review #{i}",
        )
        header = f"### Prior review #{i} (oldest first)\n"
        block = header + snippet
        if total + len(block) > _MAX_PRIOR_REVIEWS_TOTAL:
            rendered.append(f"[...{len(reviews) - i + 1} earlier reviews omitted to stay in budget]")
            break
        rendered.append(block)
        total += len(block)
    return "\n\n".join(rendered)


def main(diff_path: str, pr_json_path: str, claude_md_path: str,
         prior_reviews_path: str) -> None:
    diff = _truncate(
        pathlib.Path(diff_path).read_text(errors="replace"),
        _MAX_DIFF_CHARS, "diff",
    )
    pr = json.loads(pathlib.Path(pr_json_path).read_text())
    claude_md = _truncate(
        pathlib.Path(claude_md_path).read_text(errors="replace"),
        _MAX_CLAUDE_CHARS, "CLAUDE.md",
    )
    body = _truncate(
        pr.get("body") or "(empty)", _MAX_BODY_CHARS, "PR body",
    )

    prior_reviews = json.loads(
        pathlib.Path(prior_reviews_path).read_text() or "[]"
    )
    if not isinstance(prior_reviews, list):
        prior_reviews = []
    prior_reviews_block = _format_prior_reviews(prior_reviews)

    user = (
        f"PR title:  {pr.get('title', '')}\n"
        f"Branch:    {pr.get('headRefName', '')}\n"
        f"Author:    {pr.get('author', '')}\n"
        f"Review #:  {len(prior_reviews) + 1} (of up to 4 per PR)\n\n"
        "## PR body\n"
        f"{body}\n\n"
        "## Prior OpenAI reviews on this PR\n"
        f"{prior_reviews_block}\n\n"
        "## Project conventions (CLAUDE.md)\n"
        f"{claude_md}\n\n"
        "## Current diff (base..HEAD)\n"
        "```diff\n"
        f"{diff}\n"
        "```\n"
    )

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-5.4"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user},
        ],
    )
    review = (resp.choices[0].message.content or "(empty review)").strip()
    sys.stdout.write(review + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "usage: review_pr.py <diff> <pr.json> <CLAUDE.md> <prior_reviews.json>",
            file=sys.stderr,
        )
        sys.exit(2)
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
