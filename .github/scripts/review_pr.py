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
import re
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

# Touched-file context: whole-file snapshots for every file in the diff,
# plus a one-hop expansion of any symbol the diff imports from a local
# module. Without this the reviewer only sees diff hunks, so it can't
# tell whether a helper it's about to critique is already doing the
# right thing upstream (e.g. `Prepared.group_key` already being the
# resolved key from `resolve_group_key(...)`).
_MAX_TOUCHED_FILE_CHARS  = 8_000
_MAX_TOUCHED_TOTAL_CHARS = 40_000
_MAX_SYMBOL_DEF_CHARS    = 3_000
_MAX_SYMBOL_DEFS_TOTAL   = 20_000


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
    When you suggest a change, show the corrected code. Before asserting
    that a helper/caller upstream does NOT already handle something,
    check the "Touched files" and "Local symbol definitions" sections
    below. If a symbol's definition is not present in that context,
    list it under "Verify" rather than flagging it as a concern — do
    not invent behavior you cannot see.

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

**Verify** (optional)
<bulleted list of behaviors you suspect but cannot confirm from the provided context, or omit the section entirely if none. Each item should name the symbol/path you would need to inspect.>

**Verdict:** one of ✅ approve / ⚠️ request changes / 🛑 block — with a short reason.
"""


def _truncate(text: str, limit: int, label: str) -> str:
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n\n[...{label} truncated, {omitted} chars omitted]"


def _touched_files_from_diff(diff: str) -> list[str]:
    """Filenames introduced or modified in the diff, preserving order."""
    out: list[str] = []
    seen: set[str] = set()
    for line in diff.splitlines():
        m = re.match(r"^diff --git a/(.+?) b/(.+)$", line)
        if not m:
            continue
        path = m.group(2)
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _format_touched_files(paths: list[str]) -> tuple[str, list[str]]:
    """Render each touched file at its current on-disk contents.

    Returns (markdown_block, shown_paths) so the symbol expander can
    dedupe against files already shown in full.
    """
    if not paths:
        return "(no files in diff)", []

    blocks: list[str] = []
    shown: list[str] = []
    total = 0
    for path in paths:
        try:
            p = pathlib.Path(path)
            if not p.is_file():
                continue
            content = p.read_text(errors="replace")
        except Exception:
            continue
        content = _truncate(content, _MAX_TOUCHED_FILE_CHARS, path)
        lang = "python" if path.endswith(".py") else ""
        block = f"### `{path}` (current contents at PR HEAD)\n```{lang}\n{content}\n```\n"
        if total + len(block) > _MAX_TOUCHED_TOTAL_CHARS:
            remaining = len(paths) - len(shown)
            blocks.append(f"[...{remaining} touched file(s) omitted to stay in budget]")
            break
        blocks.append(block)
        shown.append(path)
        total += len(block)
    return ("\n".join(blocks) if blocks else "(none readable)"), shown


# Match `from X.Y import a, b` — the dominant import style in this
# repo. `import X` forms are ignored; they usually don't name a specific
# symbol we'd want to expand, and pulling a whole module file can blow
# the budget. Stars (`import *`) are ignored.
_FROM_IMPORT_RE = re.compile(
    r"^\s*from\s+([\w\.]+)\s+import\s+(.+?)$",
    re.MULTILINE,
)


def _resolve_local_module(module: str) -> str | None:
    """Map a Python dotted module to a repo-relative file path, or None."""
    parts = module.split(".")
    for candidate in (
        pathlib.Path(*parts).with_suffix(".py"),
        pathlib.Path(*parts, "__init__.py"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _extract_symbol_def(source: str, symbol: str) -> str | None:
    """Regex-extract a top-level `def`/`class` block for `symbol` from source.

    Best-effort. Handles decorators immediately preceding the def. Ends
    at the next top-level `def`/`class` or EOF. Returns None if not
    found — callers should skip silently.
    """
    header = re.search(
        rf"^(?:@[^\n]*\n)*(?:async\s+def|def|class)\s+{re.escape(symbol)}\b",
        source,
        re.MULTILINE,
    )
    if not header:
        return None
    start = header.start()
    # Walk backward over decorators — `re.MULTILINE` anchored `^` should
    # already be on the first decorator's line, but be defensive.
    tail = source[header.end():]
    next_top = re.search(r"\n(?:@\w|async\s+def|def|class)\s", tail)
    end = header.end() + next_top.start() if next_top else len(source)
    block = source[start:end].rstrip()
    return _truncate(block, _MAX_SYMBOL_DEF_CHARS, f"{symbol} body")


def _format_symbol_defs(touched_paths: list[str]) -> str:
    """For each `from X.Y import sym` in the touched files, include sym's def.

    Only resolves modules that live inside this repo — third-party and
    stdlib imports are skipped. Deduped across touched files.
    """
    if not touched_paths:
        return "(none)"

    seen: set[tuple[str, str]] = set()
    blocks: list[str] = []
    total = 0
    for importing_path in touched_paths:
        try:
            src = pathlib.Path(importing_path).read_text(errors="replace")
        except Exception:
            continue
        for m in _FROM_IMPORT_RE.finditer(src):
            module = m.group(1)
            # `from .foo import bar` — relative; skip for simplicity.
            if module.startswith("."):
                continue
            resolved = _resolve_local_module(module)
            if not resolved:
                continue
            # Parse the `import a, b as c, (d,` portion. Strip parens,
            # trailing comments, and `as` aliases.
            names_blob = re.split(r"#", m.group(2), maxsplit=1)[0]
            names_blob = names_blob.strip().strip("()").rstrip("\\").strip()
            # Multi-line parenthesised imports end at the closing paren;
            # our regex already stops at the first line. Good enough —
            # if someone puts `from X import (a,\n b)`, we catch `a`.
            symbols = [
                s.strip().split(" as ")[0].strip()
                for s in names_blob.split(",")
                if s.strip() and s.strip() != "*"
            ]
            try:
                target_src = pathlib.Path(resolved).read_text(errors="replace")
            except Exception:
                continue
            for sym in symbols:
                key = (resolved, sym)
                if key in seen:
                    continue
                body = _extract_symbol_def(target_src, sym)
                if not body:
                    continue
                seen.add(key)
                block = (
                    f"### `{module}.{sym}` — from `{resolved}`\n"
                    f"```python\n{body}\n```\n"
                )
                if total + len(block) > _MAX_SYMBOL_DEFS_TOTAL:
                    blocks.append("[...remaining symbol defs omitted to stay in budget]")
                    return "\n".join(blocks)
                blocks.append(block)
                total += len(block)
    return "\n".join(blocks) if blocks else "(none — no local imports resolved)"


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

    # Touched files + symbol expansion. Reads the actual file contents
    # at the PR HEAD from cwd (the workflow checkout). Diff text is
    # used only to decide *which* files to include.
    touched_paths = _touched_files_from_diff(diff)
    touched_files_block, shown_touched = _format_touched_files(touched_paths)
    symbol_defs_block = _format_symbol_defs(shown_touched)

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
        "## Touched files (full current contents at PR HEAD)\n"
        "Ground concerns in what's actually in these files, not in what the\n"
        "diff hunks seem to imply. The diff below shows what CHANGED; this\n"
        "section shows the current state of every file the diff touches.\n\n"
        f"{touched_files_block}\n\n"
        "## Local symbol definitions (one-hop expansion)\n"
        "For each `from <local_module> import <sym>` in the touched files,\n"
        "the definition of `<sym>` from its source module. Use this to\n"
        "check whether a helper a concern depends on already does the\n"
        "right thing upstream (e.g. whether a resolver is already called\n"
        "by the shared preparation path) before flagging it.\n\n"
        f"{symbol_defs_block}\n\n"
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
