"""Minimal GitHub REST client for repo ingestion.

Only the endpoints we actually need:
    - parse_repo_url(url)          → owner, repo, branch (optional)
    - list_tree(owner, repo, ref)  → [{path, sha, type, size}, ...]
    - fetch_blob(owner, repo, sha) → utf-8 text or None (binary/too-big)

Binary files and anything over ~1 MB are skipped silently — the course
content we index is almost all markdown / notebooks / small source files.
Auth is optional: anonymous requests get 60/hour, authed get 5000/hour
(GITHUB_TOKEN env).
"""

from __future__ import annotations

import base64
import re

import requests

from bot.config import GITHUB_TOKEN


MAX_BLOB_BYTES = 1_000_000  # 1 MB
GH_API = "https://api.github.com"

# Extensions we actually try to embed. Anything else is ignored.
_TEXT_EXTENSIONS = {
    ".md",
    ".mdx",
    ".markdown",
    ".rst",
    ".txt",
    ".py",
    ".ipynb",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".html",
    ".css",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".swift",
    ".kt",
    ".c",
    ".cpp",
    ".h",
    ".sh",
    ".bash",
    ".zsh",
    ".sql",
}


# ── URL parsing ───────────────────────────────────────────────────────────
_URL_RE = re.compile(
    r"^(?:https?://github\.com/)?"
    r"(?P<owner>[^/\s]+)/(?P<repo>[^/\s#]+?)(?:\.git)?"
    # Branch name allows slashes (e.g. "feature/foo", "release/2025-q4");
    # non-greedy so the trailing /?$ can still consume an optional slash.
    r"(?:/tree/(?P<branch>[^\s#]+?))?"
    r"/?$"
)


def parse_repo_url(url: str) -> tuple[str, str, str | None] | None:
    """Return (owner, repo, branch_or_None) or None on unrecognized input.

    Accepts:
        owner/repo
        https://github.com/owner/repo
        https://github.com/owner/repo.git
        https://github.com/owner/repo/tree/branch
    """
    if not url:
        return None
    m = _URL_RE.match(url.strip())
    if not m:
        return None
    return m.group("owner"), m.group("repo"), m.group("branch")


def canonical_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}"


# ── HTTP ──────────────────────────────────────────────────────────────────
def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def _get(path: str, **kwargs) -> requests.Response | None:
    try:
        return requests.get(f"{GH_API}{path}", headers=_headers(), timeout=15, **kwargs)
    except Exception as e:
        print(f"[github] GET {path} failed: {e}")
        return None


# ── Default branch ────────────────────────────────────────────────────────
def default_branch(owner: str, repo: str) -> str | None:
    resp = _get(f"/repos/{owner}/{repo}")
    if resp is None or resp.status_code >= 400:
        return None
    try:
        return resp.json().get("default_branch")
    except Exception:
        return None


# ── Tree walk ─────────────────────────────────────────────────────────────
def list_tree(owner: str, repo: str, ref: str) -> list[dict]:
    """Return files under ``ref`` that look ingestible (extension + size)."""
    resp = _get(f"/repos/{owner}/{repo}/git/trees/{ref}", params={"recursive": "1"})
    if resp is None or resp.status_code >= 400:
        print(f"[github] tree fetch failed: {resp.status_code if resp else '?'}")
        return []
    payload = resp.json()
    if payload.get("truncated"):
        print(f"[github] {owner}/{repo}@{ref} tree truncated — some files skipped")
    out: list[dict] = []
    for entry in payload.get("tree", []):
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        size = int(entry.get("size", 0))
        if size > MAX_BLOB_BYTES:
            continue
        if not _has_text_extension(path):
            continue
        out.append(
            {
                "path": path,
                "sha": entry.get("sha", ""),
                "size": size,
            }
        )
    return out


def _has_text_extension(path: str) -> bool:
    lower = path.lower()
    for ext in _TEXT_EXTENSIONS:
        if lower.endswith(ext):
            return True
    return False


# ── Blob fetch ────────────────────────────────────────────────────────────
def fetch_blob(owner: str, repo: str, sha: str) -> str | None:
    """Download a blob by SHA. Returns decoded text or None on error/binary."""
    resp = _get(f"/repos/{owner}/{repo}/git/blobs/{sha}")
    if resp is None or resp.status_code >= 400:
        return None
    try:
        payload = resp.json()
        encoding = payload.get("encoding")
        content = payload.get("content") or ""
        if encoding == "base64":
            raw = base64.b64decode(content)
        else:
            raw = content.encode("utf-8")
        return raw.decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[github] blob {sha[:7]} decode error: {e}")
        return None


# ── Push payload parse (webhook) ──────────────────────────────────────────
def changed_paths_from_push(payload: dict) -> list[str]:
    """Collect added+modified file paths from a GitHub push webhook payload."""
    changed: set[str] = set()
    for commit in payload.get("commits", []) or []:
        for path in commit.get("added", []) or []:
            changed.add(path)
        for path in commit.get("modified", []) or []:
            changed.add(path)
    return [p for p in changed if _has_text_extension(p)]


def removed_paths_from_push(payload: dict) -> list[str]:
    removed: set[str] = set()
    for commit in payload.get("commits", []) or []:
        for path in commit.get("removed", []) or []:
            removed.add(path)
    return list(removed)
