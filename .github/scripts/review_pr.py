#!/usr/bin/env python3
"""Call OpenAI to review a PR diff; emit the review as markdown.

Invoked from .github/workflows/pr-review.yml. Reads three files passed
on the command line and prints the review to stdout for `gh pr comment`
to post.

    usage: review_pr.py <diff> <pr.json> <CLAUDE.md>

Required env: OPENAI_API_KEY
Optional env: OPENAI_MODEL  (defaults to gpt-5.4)
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

from openai import OpenAI


# Token-budget guards. GitHub diffs can get huge; CLAUDE.md is long; we
# don't need every byte of either to spot issues. Truncation markers are
# appended inside each blob so the model knows context was cut.
_MAX_DIFF_CHARS   = 30_000
_MAX_CLAUDE_CHARS = 6_000
_MAX_BODY_CHARS   = 4_000


SYSTEM_PROMPT = """\
You are a senior code reviewer for a Python Telegram bot deployed on Vercel.
You review pull requests opened by an automated self-upgrade routine (Claude
Code). Your job is to catch issues the routine may have missed before the
maintainer merges.

Focus (in this order):
1. Intent match — does the diff actually accomplish what the PR body says?
2. Security — command injection, secret leaks, over-broad permissions,
   missing webhook verification, ReDoS, etc.
3. Correctness — bugs, off-by-ones, wrong types, missing None-checks at
   boundaries, unhandled error paths that should be handled.
4. Test coverage — are the new tests meaningful? Any obvious edge case
   missing? (Don't demand exhaustive tests; do demand the happy path +
   one failure path.)
5. Project conventions — violations of patterns documented in CLAUDE.md.
6. Size / scope — is the PR doing more than the instruction asked? Call
   out drive-by refactors or abstractions beyond the task.

Be concrete. Cite file paths and line ranges from the diff hunks. When
you suggest a change, show the corrected code.

Do NOT:
- Praise the PR or pad with compliments.
- Restate what the diff does — the maintainer can read it.
- Raise style-only nits that a linter would catch.
- Invent issues. If a section has nothing to report, write "None.".

Output format (GitHub-flavored Markdown, nothing else):

## 🤖 OpenAI review

**Intent match:** <one sentence — does the code match the stated intent?>

**Concerns**
<bulleted list or "None.">

**Test coverage**
<bulleted list or "None.">

**Suggestions**
<bulleted list or "None.">

**Verdict:** one of ✅ approve / ⚠️ request changes / 🛑 block — with a short reason.
"""


def _truncate(text: str, limit: int, label: str) -> str:
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n\n[...{label} truncated, {omitted} chars omitted]"


def main(diff_path: str, pr_json_path: str, claude_md_path: str) -> None:
    diff      = _truncate(
        pathlib.Path(diff_path).read_text(errors="replace"),
        _MAX_DIFF_CHARS, "diff",
    )
    pr        = json.loads(pathlib.Path(pr_json_path).read_text())
    claude_md = _truncate(
        pathlib.Path(claude_md_path).read_text(errors="replace"),
        _MAX_CLAUDE_CHARS, "CLAUDE.md",
    )
    body      = _truncate(
        pr.get("body") or "(empty)", _MAX_BODY_CHARS, "PR body",
    )

    user = (
        f"PR title:  {pr.get('title', '')}\n"
        f"Branch:    {pr.get('headRefName', '')}\n"
        f"Author:    {pr.get('author', '')}\n\n"
        "## PR body\n"
        f"{body}\n\n"
        "## Project conventions (CLAUDE.md)\n"
        f"{claude_md}\n\n"
        "## Diff\n"
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
    if len(sys.argv) != 4:
        print("usage: review_pr.py <diff> <pr.json> <CLAUDE.md>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
