"""Admin command dispatcher + handlers.

Stage 3 ships the read-only and admin-list mutation commands. Later
stages add /doc, /quiz, /stats, /grade, /announce, /purge, /reveal.
"""
from __future__ import annotations

import html
import random
import time
from typing import Callable

from bot import github as gh
from bot.clients import bot as _bot
from bot.config import BOT_ENV, DEFAULT_MODEL, PERMANENT_ADMIN, VALID_MODELS, VECTOR_NAMESPACE
from bot.ta import announcements as ann_mod
from bot.ta import docs as docs_mod
from bot.ta import git_ingest as git_mod
from bot.ta import joke as joke_mod
from bot.ta import quiz as quiz_mod
from bot.ta import rag as rag_mod
from bot.ta import stats as stats_mod
from bot.ta import upgrade as upgrade_mod
from bot.ta.prepare import Prepared
from bot.ta.state import (
    add_admin,
    add_feedback,
    clear_active_model,
    clear_dm_log,
    clear_feedback,
    clear_history,
    get_active_group_id,
    get_active_model,
    get_dm_log,
    get_dm_meta,
    get_group_stats,
    get_quiz_scores,
    get_streak,
    get_total_quizzes,
    get_user_chat,
    list_admins,
    list_dm_users,
    list_feedback,
    list_groups,
    remove_admin,
    reset_group_stats,
    set_active_group_id,
    set_active_model,
)
from bot.ta.tg import delete_message, send_message


_Handler = Callable[[Prepared], None]
_REGISTRY: dict[str, _Handler] = {}


def _register(*names: str):
    def deco(fn: _Handler) -> _Handler:
        for n in names:
            _REGISTRY[n] = fn
        return fn
    return deco


def dispatch(p: Prepared) -> None:
    """Route an admin command to its handler.

    Most commands DM their reply to the admin. Engagement commands
    (``/quiz``, ``/joke``, ``/announce``) instead post the *result* to
    the originating chat so the class sees it, while still DM'ing
    errors/usage to the admin. ``/roll`` is fully chat-local: every
    reply (result, usage, error) goes to the chat where it was typed,
    so we never depend on ``p.user_id`` being a usable DM target. If
    the command was typed in a group, the router has already deleted
    the original message.
    """
    cmd = (p.command or "").lower()
    handler = _REGISTRY.get(cmd)
    if handler is None:
        send_message(
            p.user_id,
            f"Unknown or not-yet-implemented command: /{cmd}",
        )
        return
    try:
        handler(p)
    except Exception as e:
        print(f"[ta.commands] /{cmd} error: {e}")
        send_message(p.user_id, f"Error running /{cmd}: {e}")


# ── /help ─────────────────────────────────────────────────────────────────
@_register("help")
def _cmd_help(p: Prepared) -> None:
    lines = [
        "<b>Admin commands</b>",
        "",
        "<b>Basics</b>",
        "/help — this message",
        "/info — workspace config",
        "",
        "<b>People</b>",
        "/admin — list admins",
        "/admin add @user",
        "/admin remove @user",
        "",
        "<b>Group</b>",
        "/group — list linked groups",
        "/group &lt;N|chatId&gt; — switch active group",
        "",
        "<b>Model</b>",
        "/model — list models, mark active",
        "/model &lt;name&gt; — switch chat model",
        "/reset — clear history + reset model for active group",
        "",
        "<b>Knowledge</b>",
        "/doc — list indexed docs",
        "/doc add &lt;title&gt;\\n&lt;content&gt;",
        "/doc update &lt;title&gt;\\n&lt;content&gt;",
        "/doc delete &lt;title&gt;",
        "/git — list indexed GitHub repos",
        "/git add &lt;owner/repo&gt;",
        "/git sync — re-sync all repos",
        "/git sync &lt;owner/repo&gt;",
        "/git remove &lt;owner/repo&gt;",
        "/vstats — vector index stats",
        "",
        "<b>DMs</b>",
        "/dm — list active DM conversations",
        "/dm view @user|&lt;userId&gt; — show transcript",
        "/dm clear @user|&lt;userId&gt; — wipe transcript",
        "",
        "<b>Engagement</b>",
        "/quiz [topic] — post an MC question",
        "/reveal — end active quiz early",
        "/joke [theme] — post a short joke (e.g. /joke about python)",
        "/roll &lt;min&gt; &lt;max&gt; — pick a random integer in [min, max]",
        "/stats — message counts + quiz scores",
        "/stats reset — clear stats for active group",
        "/grade — engagement scores",
        "/grade @user — single-student breakdown",
        "",
        "<b>Broadcast</b>",
        "/announce &lt;message&gt; — preview, then reply <b>send it</b> or <b>cancel</b>",
        "",
        "<b>Feedback</b>",
        "/feedback &lt;text&gt; — submit anonymous feedback (students too)",
        "/feedback list — view all feedback (admin)",
        "/feedback clear — clear all feedback (admin)",
        "",
        "<b>Cleanup</b>",
        "/purge — bulk delete messages + reset group state",
        "",
        "<b>Self-upgrade</b> (instructor only)",
        "/upgrade &lt;instructions&gt; — fire the Claude Code routine to open a PR",
    ]
    send_message(p.user_id, "\n".join(lines), parse_mode="HTML")


# ── /info ─────────────────────────────────────────────────────────────────
@_register("info")
def _cmd_info(p: Prepared) -> None:
    active_group = get_active_group_id() or "(none)"
    group_key = p.group_key
    model = get_active_model(group_key) or DEFAULT_MODEL
    lines = [
        "<b>Workspace</b>",
        f"Environment:   <code>{BOT_ENV}</code>",
        f"Active group:  <code>{active_group}</code>",
        f"Context key:   <code>{group_key}</code>",
        f"Model:         <code>{model}</code>",
        f"Permanent admin: @{PERMANENT_ADMIN}",
    ]
    send_message(p.user_id, "\n".join(lines), parse_mode="HTML")


# ── /admin [add|remove] [@user] ───────────────────────────────────────────
@_register("admin")
def _cmd_admin(p: Prepared) -> None:
    tokens = p.command_args.split()
    sub = tokens[0].lower() if tokens else ""

    if not sub:
        _admin_list(p)
        return
    if sub == "list":
        _admin_list(p)
        return
    if sub == "add":
        _admin_add(p, tokens[1] if len(tokens) > 1 else "")
        return
    if sub == "remove":
        _admin_remove(p, tokens[1] if len(tokens) > 1 else "")
        return
    send_message(p.user_id, "Usage: /admin [list] | /admin add @user | /admin remove @user")


def _admin_list(p: Prepared) -> None:
    admins = list_admins()
    body = "\n".join(f"• @{u}" for u in admins) or "(none)"
    send_message(p.user_id, f"<b>Admins</b>\n{body}", parse_mode="HTML")


def _admin_add(p: Prepared, raw_target: str) -> None:
    target = _first_username(raw_target)
    if not target:
        send_message(p.user_id, "Usage: /admin add @username")
        return
    if not add_admin(target):
        send_message(p.user_id, f"Could not add @{target}.")
        return
    send_message(p.user_id, f"✅ @{target} is now an admin.")

    # Best-effort DM to the new admin so they know they have access.
    target_chat = get_user_chat(target)
    if target_chat:
        send_message(
            target_chat,
            f"You were granted admin access by @{p.username or 'instructor'}.\n"
            "Use /help to see the commands available to you.",
        )


def _admin_remove(p: Prepared, raw_target: str) -> None:
    target = _first_username(raw_target)
    if not target:
        send_message(p.user_id, "Usage: /admin remove @username")
        return
    if target == PERMANENT_ADMIN:
        send_message(p.user_id, f"Cannot remove the permanent admin (@{PERMANENT_ADMIN}).")
        return
    if p.username and target == p.username:
        send_message(p.user_id, "You cannot remove yourself.")
        return
    if not remove_admin(target):
        send_message(p.user_id, f"Could not remove @{target}.")
        return
    send_message(p.user_id, f"✅ @{target} removed from admins.")


# ── /reset ────────────────────────────────────────────────────────────────
@_register("reset")
def _cmd_reset(p: Prepared) -> None:
    clear_history(p.group_key)
    clear_active_model(p.group_key)
    send_message(
        p.user_id,
        f"✅ Cleared history and reset model to default (<code>{DEFAULT_MODEL}</code>) "
        f"for context <code>{p.group_key}</code>.",
        parse_mode="HTML",
    )


# ── /model ────────────────────────────────────────────────────────────────
@_register("model")
def _cmd_model(p: Prepared) -> None:
    args = p.command_args.strip()
    if not args:
        current = get_active_model(p.group_key) or DEFAULT_MODEL
        lines = ["<b>Available models</b>"]
        for m in VALID_MODELS:
            if m == current:
                lines.append(f"• <code>{m}</code> (active)")
            else:
                lines.append(f"• <code>{m}</code>")
        lines.append("")
        lines.append("Switch: /model &lt;name&gt;")
        send_message(p.user_id, "\n".join(lines), parse_mode="HTML")
        return
    choice = args.split()[0]
    if choice not in VALID_MODELS:
        send_message(
            p.user_id,
            f"Invalid model: <code>{html.escape(choice)}</code>\n"
            f"Valid options: {', '.join(VALID_MODELS)}",
            parse_mode="HTML",
        )
        return
    set_active_model(p.group_key, choice)
    send_message(
        p.user_id,
        f"✅ Model switched to <code>{choice}</code> for context "
        f"<code>{p.group_key}</code>.",
        parse_mode="HTML",
    )


# ── /group [N|chatId|list] ────────────────────────────────────────────────
@_register("group")
def _cmd_group(p: Prepared) -> None:
    args = p.command_args.strip()
    groups = list_groups()
    # Explicit "list" alias — same behavior as no-arg.
    if args.lower() == "list":
        args = ""
    if not args:
        active = get_active_group_id() or "(none)"
        if not groups:
            send_message(p.user_id, "No groups linked yet. Add me to a group first.")
            return
        lines = [f"<b>Linked groups</b> (active: <code>{active}</code>)"]
        for i, g in enumerate(groups, start=1):
            chat_id = g.get("chatId")
            title = g.get("title", "(untitled)")
            marker = "✅ " if str(chat_id) == str(active) else "   "
            lines.append(f"{marker}{i}. <code>{chat_id}</code> — {html.escape(title)}")
        lines.append("")
        lines.append("Switch: /group &lt;N&gt; or /group &lt;chatId&gt;")
        send_message(p.user_id, "\n".join(lines), parse_mode="HTML")
        return

    choice = args.split()[0]
    target: str | None = None
    # Index into the list?
    if choice.isdigit() and 1 <= int(choice) <= len(groups):
        target = str(groups[int(choice) - 1]["chatId"])
    # Direct chat id?
    elif any(str(g.get("chatId")) == choice for g in groups):
        target = choice

    if target is None:
        send_message(p.user_id, f"No linked group matches <code>{html.escape(choice)}</code>.", parse_mode="HTML")
        return
    set_active_group_id(target)
    send_message(p.user_id, f"✅ Active group switched to <code>{target}</code>.", parse_mode="HTML")


# ── /doc list|add|update|delete ───────────────────────────────────────────
@_register("doc")
def _cmd_doc(p: Prepared) -> None:
    docs_mod.dispatch(p)


# ── /quiz [topic] ─────────────────────────────────────────────────────────
@_register("quiz")
def _cmd_quiz(p: Prepared) -> None:
    # Quizzes run in a group chat. If the admin triggers /quiz from DM,
    # use the active group as the target; otherwise reply with guidance.
    target_chat = p.chat_id if not p.is_dm else get_active_group_id()
    if not target_chat:
        send_message(p.user_id, "No active group. Use /group first or run /quiz in a group.")
        return
    topic = (p.command_args or "").strip()
    quiz_mod.start_quiz(p, topic, target_chat)


# ── /reveal ───────────────────────────────────────────────────────────────
@_register("reveal")
def _cmd_reveal(p: Prepared) -> None:
    target_chat = p.chat_id if not p.is_dm else get_active_group_id()
    if not target_chat:
        send_message(p.user_id, "No active group. Use /group first or run /reveal in a group.")
        return
    if not quiz_mod.reveal_now(target_chat):
        send_message(p.user_id, "No active quiz to reveal in that chat.")


# ── /joke [theme] ─────────────────────────────────────────────────────────
@_register("joke")
def _cmd_joke(p: Prepared) -> None:
    """Post a short LLM-generated joke about the given theme.

    In a group: the joke is posted to that group. In DM: posted to the DM
    if there's no active group, otherwise to the active group so the class
    can see it. Theme is optional; without one the LLM picks a subject.
    """
    theme = (p.command_args or "").strip()
    if p.is_dm:
        active_group = get_active_group_id()
        target_chat = active_group if active_group is not None else p.chat_id
        model_group_key = str(active_group) if active_group is not None else p.group_key
    else:
        target_chat = p.chat_id
        model_group_key = p.group_key

    if not joke_mod.tell_joke(theme, model_group_key, target_chat):
        send_message(p.user_id, "Couldn't generate a joke — see logs.")


# ── /roll <min> <max> ─────────────────────────────────────────────────────
@_register("roll")
def _cmd_roll(p: Prepared) -> None:
    """Pick a random integer between two inclusive bounds.

    Examples: ``/roll 1 15``, ``/roll -3 3``, ``/roll 15 1`` (reversed is fine).
    All replies — result, usage, and errors — go to the originating chat
    (DM or group). Routing to ``p.user_id`` for the error paths would
    break for admins who triggered ``/roll`` in a group without first
    starting a private chat with the bot.
    """
    target_chat = p.chat_id
    tokens = (p.command_args or "").split()
    if len(tokens) != 2:
        send_message(
            target_chat,
            "Usage: <code>/roll &lt;min&gt; &lt;max&gt;</code> — e.g. <code>/roll 1 15</code>",
            parse_mode="HTML",
        )
        return
    try:
        a = int(tokens[0])
        b = int(tokens[1])
    except ValueError:
        send_message(
            target_chat,
            "Both arguments must be integers. Usage: "
            "<code>/roll &lt;min&gt; &lt;max&gt;</code>",
            parse_mode="HTML",
        )
        return
    low, high = (a, b) if a <= b else (b, a)
    n = random.randint(low, high)
    send_message(target_chat, f"🎲 <b>{n}</b> (from {low}–{high})", parse_mode="HTML")


# ── /stats [reset] ────────────────────────────────────────────────────────
@_register("stats")
def _cmd_stats(p: Prepared) -> None:
    sub = (p.command_args or "").strip().lower()
    if sub == "reset":
        gk = p.group_key
        reset_group_stats(gk)
        send_message(p.user_id, f"✅ Cleared stats for <code>{gk}</code>.\n"
                     "(messages, scores, quiz history, conversation history)",
                     parse_mode="HTML")
        return

    stats_map  = get_group_stats(p.group_key)
    scores_map = get_quiz_scores(p.group_key)
    total_q    = get_total_quizzes(p.group_key)

    if not stats_map and not scores_map:
        send_message(p.user_id, "No stats yet for this context.")
        return

    # Message activity (sorted by messageCount desc).
    lines = [f"<b>Stats</b> — <code>{p.group_key}</code> (quizzes posted: {total_q})"]
    lines.append("")
    lines.append("<b>Messages</b>")
    by_msgs = sorted(
        stats_map.items(),
        key=lambda kv: int(kv[1].get("messageCount", 0)),
        reverse=True,
    )[:15]
    for _uid, data in by_msgs:
        name = html.escape(data.get("firstName") or data.get("username") or "(unknown)")
        lines.append(f"• {name} — {int(data.get('messageCount', 0))}")

    # Quiz scores (sorted by accuracy desc).
    if scores_map:
        lines.append("")
        lines.append("<b>Quiz scores</b>")
        def _accuracy(kv):
            data = kv[1]
            t = int(data.get("total", 0))
            return (int(data.get("correct", 0)) / t) if t else 0.0
        by_acc = sorted(scores_map.items(), key=_accuracy, reverse=True)[:15]
        for _uid, data in by_acc:
            name = html.escape(data.get("firstName") or data.get("username") or "(unknown)")
            c, t = int(data.get("correct", 0)), int(data.get("total", 0))
            pct = 100 * c / t if t else 0
            lines.append(f"• {name} — {c}/{t} ({pct:.0f}%)")

    send_message(p.user_id, "\n".join(lines), parse_mode="HTML")


# ── /grade [@user] ────────────────────────────────────────────────────────
@_register("grade")
def _cmd_grade(p: Prepared) -> None:
    target_username = _first_username(p.command_args)
    stats_map  = get_group_stats(p.group_key)
    scores_map = get_quiz_scores(p.group_key)
    total_q    = get_total_quizzes(p.group_key)
    engagement = stats_mod.compute_all(stats_map, scores_map, total_q)

    if target_username:
        match = next(
            (e for e in engagement if (e.username or "").lower() == target_username),
            None,
        )
        if match is None:
            send_message(p.user_id, f"No data for @{html.escape(target_username)} in <code>{p.group_key}</code>.",
                         parse_mode="HTML")
            return
        send_message(p.user_id, _render_grade_detail(match, p.group_key), parse_mode="HTML")
        return

    if not engagement:
        send_message(p.user_id, "No data yet for this context.")
        return

    engagement.sort(key=lambda e: e.total_pts, reverse=True)
    lines = [
        f"<b>Engagement</b> — <code>{p.group_key}</code>",
        f"Quizzes posted: {total_q}",
        "",
        "<b>Scoring formula (out of 100):</b>",
        f"  30% messages (capped at 20)",
        f"  40% quiz participation (attempted / {total_q})",
        f"  30% quiz accuracy (correct / attempted)",
        "",
    ]
    for e in engagement[:25]:
        flag = " \u26a0\ufe0f" if e.inactive else ""
        streak = get_streak(p.group_key, e.user_id)
        streak_badge = f" \U0001f525{streak}" if streak >= 2 else ""
        pct = f"{e.accuracy_pct:.0f}%" if e.attempts else "n/a"
        lines.append(
            f"\u2022 {html.escape(e.display_name)}{streak_badge}{flag} \u2014 <b>{e.total_pts:.0f}</b>  "
            f"({e.messages} msgs, {e.attempts}/{total_q} quizzes, {e.correct}/{e.attempts} correct [{pct}])"
        )
    send_message(p.user_id, "\n".join(lines), parse_mode="HTML")


def _render_grade_detail(e: "stats_mod.Engagement", group_key: str) -> str:
    flag = " \u26a0\ufe0f (inactive >7d)" if e.inactive else ""
    streak = get_streak(group_key, e.user_id)
    streak_line = f"\n  \u2022 Streak: \U0001f525{streak} consecutive correct" if streak >= 2 else "\n  \u2022 Streak: 0"
    return (
        f"<b>{html.escape(e.display_name)}</b>{flag}\n"
        f"Total: <b>{e.total_pts:.0f}/100</b>\n"
        f"  \u2022 Messages: {e.messages} sent (max 20 counted) \u2192 {e.messages_pts:.0f}/{stats_mod.W_MESSAGES}\n"
        f"  \u2022 Participation: {e.attempts}/{e.total_quizzes} quizzes attempted "
        f"({e.participation_pct:.0f}%) \u2192 {e.particip_pts:.0f}/{stats_mod.W_PARTICIPATION}\n"
        f"  \u2022 Accuracy: {e.correct}/{e.attempts} correct "
        f"({e.accuracy_pct:.0f}%) \u2192 {e.accuracy_pts:.0f}/{stats_mod.W_ACCURACY}"
        f"{streak_line}"
    )


# ── /announce ─────────────────────────────────────────────────────────────
@_register("announce")
def _cmd_announce(p: Prepared) -> None:
    ann_mod.start(p)


# ── /git list|add|remove|sync ─────────────────────────────────────────────
@_register("git")
def _cmd_git(p: Prepared) -> None:
    from bot.ta.state import list_git_repos
    tokens = (p.command_args or "").split()
    sub = tokens[0].lower() if tokens else ""
    arg = tokens[1] if len(tokens) > 1 else ""

    if not sub or sub == "list":
        repos = list_git_repos()
        if not repos:
            send_message(p.user_id, "No GitHub repos indexed. Use /git add <url>.")
            return
        lines = ["<b>Indexed GitHub repos</b>"]
        for r in repos:
            last = r.get("lastSync", 0)
            lines.append(
                f"• <code>{r.get('owner')}/{r.get('repo')}</code> @ "
                f"<code>{r.get('branch', '?')}</code> — by @{r.get('addedBy') or '?'}"
            )
        send_message(p.user_id, "\n".join(lines), parse_mode="HTML")
        return

    if sub == "add":
        parsed = gh.parse_repo_url(arg)
        if not parsed:
            send_message(p.user_id, "Usage: /git add <owner/repo> or a GitHub URL")
            return
        owner, repo, branch = parsed
        from bot.ta.state import get_git_repo
        if get_git_repo(owner, repo):
            send_message(
                p.user_id,
                f"<code>{owner}/{repo}</code> is already indexed. Use "
                f"<code>/git sync</code> to re-ingest or <code>/git remove</code> first.",
                parse_mode="HTML",
            )
            return
        result = git_mod.sync_repo_async(
            owner, repo, branch, added_by=p.username, notify_chat_id=p.user_id,
        )
        if not result.get("ok"):
            send_message(p.user_id, f"❌ Failed: {result.get('reason', 'unknown')}")
            return
        send_message(
            p.user_id,
            f"✅ <b>{owner}/{repo}</b> @ <code>{result['branch']}</code>\n"
            f"queued {result['files_total']} files in {result['batches']} batches.\n"
            f"You'll get a DM when this repo finishes.",
            parse_mode="HTML",
        )
        return

    if sub == "remove":
        parsed = gh.parse_repo_url(arg)
        if not parsed:
            send_message(p.user_id, "Usage: /git remove <owner/repo>")
            return
        owner, repo, _branch = parsed
        count = git_mod.remove_all(owner, repo)
        if count == 0:
            send_message(p.user_id, f"No indexed files for {owner}/{repo}.")
        else:
            send_message(p.user_id, f"✅ Removed {count} files for {owner}/{repo}.")
        return

    if sub == "sync":
        from bot.ta.state import get_git_repo, list_git_repos
        # No arg → re-sync every tracked repo. Useful after schema/embedding changes.
        if not arg:
            repos = list_git_repos()
            if not repos:
                send_message(p.user_id, "No repos indexed. Use /git add first.")
                return
            lines = ["<b>Re-sync queued</b>"]
            total = 0
            for r in repos:
                owner, repo = r.get("owner", ""), r.get("repo", "")
                branch = r.get("branch") or None
                result = git_mod.sync_repo_async(
                    owner, repo, branch, added_by=p.username, notify_chat_id=p.user_id,
                )
                if result.get("ok"):
                    n = result["files_total"]
                    total += n
                    lines.append(f"• <code>{owner}/{repo}</code> — {n} files")
                else:
                    lines.append(f"• <code>{owner}/{repo}</code> — ❌ {result.get('reason', '?')}")
            lines.append("")
            lines.append(f"Total: <b>{total}</b> files. You'll get a DM per repo as it finishes.")
            send_message(p.user_id, "\n".join(lines), parse_mode="HTML")
            return

        parsed = gh.parse_repo_url(arg)
        if not parsed:
            send_message(p.user_id, "Usage: /git sync [<owner/repo>] (no arg = sync all)")
            return
        owner, repo, branch = parsed
        if not get_git_repo(owner, repo):
            send_message(
                p.user_id,
                f"<code>{owner}/{repo}</code> is not indexed. Use "
                f"<code>/git add</code> to add it first.",
                parse_mode="HTML",
            )
            return
        result = git_mod.sync_repo_async(
            owner, repo, branch, added_by=p.username, notify_chat_id=p.user_id,
        )
        if not result.get("ok"):
            send_message(p.user_id, f"❌ Failed: {result.get('reason', 'unknown')}")
            return
        send_message(
            p.user_id,
            f"✅ Re-syncing <code>{owner}/{repo}</code> — "
            f"queued {result['files_total']} files. DM on completion.",
            parse_mode="HTML",
        )
        return

    send_message(p.user_id, "Usage: /git list | add <repo> | remove <repo> | sync <repo>")


# ── /dm list|view|clear ───────────────────────────────────────────────────
_DM_VIEW_LIMIT = 40          # last N turns rendered per /dm view
_DM_CHUNK_SIZE = 3500        # safe under Telegram's 4096-char HTML limit


def _resolve_dm_target(raw_arg: str) -> str | None:
    """Accept either @username or a numeric user id. Returns the user id
    as a string, or None if we can't find a match."""
    token = raw_arg.strip().lstrip("@").lower()
    if not token:
        return None
    if token.isdigit() or (token.startswith("-") and token[1:].isdigit()):
        return token
    chat_id = get_user_chat(token)
    return str(chat_id) if chat_id else None


def _format_dm_turn(turn: dict) -> str:
    ts = int(turn.get("ts") or 0)
    role = turn.get("role") or "?"
    content = html.escape((turn.get("content") or "").strip())
    when = time.strftime("%m-%d %H:%M", time.gmtime(ts)) if ts else "?"
    tag = "👤 <b>user</b>" if role == "user" else "🤖 <b>bot</b>"
    return f"[{when} UTC] {tag}\n{content}"


def _send_chunks(chat_id: int | str, header: str, lines: list[str]) -> None:
    """Send ``header`` + ``lines`` as one or more HTML messages under the
    Telegram character cap. Splits on turn boundaries, never mid-line."""
    buf = header
    for ln in lines:
        prospective = f"{buf}\n\n{ln}" if buf else ln
        if len(prospective) > _DM_CHUNK_SIZE and buf:
            send_message(chat_id, buf, parse_mode="HTML")
            buf = ln
        else:
            buf = prospective
    if buf:
        send_message(chat_id, buf, parse_mode="HTML")


@_register("dm")
def _cmd_dm(p: Prepared) -> None:
    tokens = (p.command_args or "").split()
    sub = tokens[0].lower() if tokens else ""
    arg = tokens[1] if len(tokens) > 1 else ""

    if not sub or sub == "list":
        _dm_cmd_list(p)
        return
    if sub == "view":
        _dm_cmd_view(p, arg)
        return
    if sub == "clear":
        _dm_cmd_clear(p, arg)
        return
    send_message(
        p.user_id,
        "Usage: /dm [list] | /dm view @user|&lt;userId&gt; | /dm clear @user|&lt;userId&gt;",
        parse_mode="HTML",
    )


def _dm_cmd_list(p: Prepared) -> None:
    users = list_dm_users()
    if not users:
        send_message(p.user_id, "No DM conversations yet.")
        return
    now = int(time.time())
    lines = [f"<b>Active DMs</b> ({len(users)})"]
    for u in users:
        uid       = str(u.get("userId", "?"))
        uname     = u.get("username") or ""
        fname     = u.get("firstName") or ""
        turns     = int(u.get("turns", 0))
        last      = int(u.get("lastActive") or 0)
        ago       = _human_ago(now - last) if last else "?"
        label     = html.escape(fname or uname or f"user:{uid}")
        handle    = f"@{html.escape(uname)}" if uname else ""
        lines.append(
            f"• <b>{label}</b> {handle} — <code>{html.escape(uid)}</code>, "
            f"{turns} turns, last {ago}"
        )
    lines.append("")
    lines.append("<b>Audit:</b> /dm view @user | /dm view &lt;userId&gt;")
    send_message(p.user_id, "\n".join(lines), parse_mode="HTML")


def _dm_cmd_view(p: Prepared, raw_arg: str) -> None:
    if not raw_arg:
        send_message(p.user_id, "Usage: /dm view @user or /dm view <userId>")
        return
    uid = _resolve_dm_target(raw_arg)
    if not uid:
        send_message(
            p.user_id,
            f"No user found for <code>{html.escape(raw_arg)}</code>. "
            f"Try /dm list to see known ids.",
            parse_mode="HTML",
        )
        return
    turns = get_dm_log(uid, limit=_DM_VIEW_LIMIT)
    if not turns:
        send_message(p.user_id, f"No DM transcript for user <code>{html.escape(uid)}</code>.",
                     parse_mode="HTML")
        return
    meta = get_dm_meta(uid) or {}
    label = meta.get("firstName") or meta.get("username") or f"user:{uid}"
    handle = f"@{meta.get('username')}" if meta.get("username") else ""
    header = (
        f"<b>DM transcript</b> — {html.escape(label)} {html.escape(handle)} "
        f"(<code>{html.escape(uid)}</code>)\n"
        f"Showing last {len(turns)} of {int(meta.get('turns', len(turns)))} turns."
    )
    _send_chunks(p.user_id, header, [_format_dm_turn(t) for t in turns])


def _dm_cmd_clear(p: Prepared, raw_arg: str) -> None:
    if not raw_arg:
        send_message(p.user_id, "Usage: /dm clear @user or /dm clear <userId>")
        return
    uid = _resolve_dm_target(raw_arg)
    if not uid:
        send_message(
            p.user_id,
            f"No user found for <code>{html.escape(raw_arg)}</code>.",
            parse_mode="HTML",
        )
        return
    if clear_dm_log(uid):
        send_message(p.user_id, f"✅ Cleared DM transcript for <code>{html.escape(uid)}</code>.",
                     parse_mode="HTML")
    else:
        send_message(p.user_id, f"No DM transcript to clear for <code>{html.escape(uid)}</code>.",
                     parse_mode="HTML")


def _human_ago(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


# ── /vstats ───────────────────────────────────────────────────────────────
@_register("vstats")
def _cmd_vstats(p: Prepared) -> None:
    info = rag_mod.index_info()
    if info is None:
        send_message(p.user_id, "Vector index not configured or unreachable.")
        return

    size_mb = info["index_size"] / (1024 * 1024)
    active_ns = VECTOR_NAMESPACE or "(default)"
    lines = [
        "<b>Vector index</b>",
        f"Total vectors:  <b>{info['vector_count']:,}</b>",
        f"Pending:        {info['pending_vector_count']:,}",
        f"Size:           {size_mb:.2f} MB",
        f"Dimension:      {info['dimension']}",
        f"Similarity:     <code>{html.escape(str(info['similarity_function']))}</code>",
        f"Active ns:      <code>{html.escape(active_ns)}</code>",
    ]
    namespaces = info.get("namespaces") or {}
    if namespaces:
        lines.append("")
        lines.append("<b>Namespaces</b>")
        for name, ns in sorted(namespaces.items(), key=lambda kv: -int(kv[1].get("vector_count", 0))):
            label = name or "(default)"
            marker = "✅ " if (name or "") == (VECTOR_NAMESPACE or "") else "   "
            pending = int(ns.get("pending_vector_count", 0))
            pending_suffix = f" (+{pending:,} pending)" if pending else ""
            lines.append(
                f"{marker}<code>{html.escape(label)}</code> — "
                f"{int(ns.get('vector_count', 0)):,}{pending_suffix}"
            )
    send_message(p.user_id, "\n".join(lines), parse_mode="HTML")


# ── /purge ────────────────────────────────────────────────────────────────
@_register("purge")
def _cmd_purge(p: Prepared) -> None:
    """Delete all group messages from id 2 up to current, then reset state."""
    target_chat = p.chat_id if not p.is_dm else get_active_group_id()
    if not target_chat:
        send_message(p.user_id, "No active group to purge.")
        return
    current_id = getattr(p.message, "message_id", None) or 0
    if current_id <= 2:
        send_message(p.user_id, "Nothing to purge (current message id ≤ 2).")
        return

    purged = 0
    migrated_to: str | None = None
    start = max(2, current_id - 499)
    for mid in range(start, current_id + 1):
        try:
            _bot.delete_message(target_chat, mid)
            purged += 1
        except Exception as e:
            err = str(e)
            # Supergroup migration: the chat id changes sign, so retry with the new one.
            if "migrate_to_chat_id" in err and migrated_to is None:
                # Extract new chat id — telebot surfaces it inside the
                # Telegram error. Format: migrate_to_chat_id=-100...
                import re as _re
                m = _re.search(r"migrate_to_chat_id[^0-9\-]*(-?\d+)", err)
                if m:
                    migrated_to = m.group(1)
                    target_chat = migrated_to
            # Most errors are "message can't be deleted" (>48h old) — ignore.

    reset_group_stats(p.group_key)
    extra = f" Chat migrated to <code>{migrated_to}</code>." if migrated_to else ""
    send_message(
        p.user_id,
        f"✅ Purged {purged} messages and cleared state for <code>{p.group_key}</code>.{extra}",
        parse_mode="HTML",
    )


# ── /upgrade ──────────────────────────────────────────────────────────────
@_register("upgrade")
def _cmd_upgrade(p: Prepared) -> None:
    """Fire the self-upgrade Claude Code routine. Instructor only.

    The routine is configured in the claude.ai/code/routines UI; it knows
    which repo to clone, which branch to base off, and how to open the PR.
    We just hand it the instruction text and report the session URL back.
    """
    # Stricter than the normal admin gate: only the permanent admin
    # (PERMANENT_ADMIN) can modify the codebase remotely.
    if not p.is_instructor:
        send_message(
            p.user_id,
            f"Only the instructor (@{PERMANENT_ADMIN}) can run /upgrade.",
        )
        return

    instructions = (p.command_args or "").strip()
    if not instructions:
        send_message(
            p.user_id,
            "Usage: <code>/upgrade &lt;instructions&gt;</code>\n"
            "Example: <code>/upgrade add a /ping command that replies 'pong'</code>",
            parse_mode="HTML",
        )
        return

    try:
        result = upgrade_mod.fire(instructions)
    except upgrade_mod.UpgradeError as e:
        send_message(p.user_id, f"❌ Could not fire routine: {html.escape(str(e))}",
                     parse_mode="HTML")
        return

    send_message(
        p.user_id,
        "✅ <b>Upgrade routine triggered.</b>\n"
        "Claude is now editing the repo, writing tests, and opening a PR.\n\n"
        f"Session: <a href=\"{html.escape(result.session_url)}\">"
        f"{html.escape(result.session_id)}</a>\n"
        "You'll see the PR appear on the <code>test</code> branch when it's done.",
        parse_mode="HTML",
    )


# ── /feedback ─────────────────────────────────────────────────────────────
@_register("feedback")
def _cmd_feedback(p: Prepared) -> None:
    """Admin sub-commands: list / clear.  Student usage is handled by the
    router in admin.py before this dispatcher is ever called."""
    args = (p.command_args or "").strip()
    tokens = args.split()
    sub = tokens[0].lower() if tokens else ""

    if sub == "list":
        entries = list_feedback()
        if not entries:
            send_message(p.user_id, "No feedback yet.")
            return
        lines = [f"<b>Feedback</b> ({len(entries)} entries)"]
        for i, fb in enumerate(entries, 1):
            who = f"@{fb['username']}" if fb.get("username") else "(anon)"
            lines.append(f"{i}. {html.escape(fb.get('text', ''))} — {who}")
        send_message(p.user_id, "\n".join(lines), parse_mode="HTML")
        return

    if sub == "clear":
        clear_feedback()
        send_message(p.user_id, "✅ All feedback cleared.")
        return

    # Admin submitting their own feedback — same path as students.
    if not args:
        send_message(p.user_id, "Usage: /feedback <text>")
        return
    add_feedback(args, p.username)
    send_message(p.user_id, "✅ Feedback received. Thank you!")


# ── Helpers ───────────────────────────────────────────────────────────────
def _first_username(raw: str) -> str:
    """Extract the first @username (or bare username) from the argument string."""
    for tok in raw.split():
        clean = tok.lstrip("@").lower().strip()
        if clean:
            return clean
    return ""
