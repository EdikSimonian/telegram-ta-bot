"""Admin command dispatcher + handlers.

Stage 3 ships the read-only and admin-list mutation commands. Later
stages add /doc, /quiz, /stats, /grade, /announce, /purge, /reveal.
"""
from __future__ import annotations

from typing import Callable

from bot.clients import bot as _bot
from bot.config import BOT_ENV, DEFAULT_MODEL, PERMANENT_ADMIN, VALID_MODELS
from bot.ta import announcements as ann_mod
from bot.ta import docs as docs_mod
from bot.ta import quiz as quiz_mod
from bot.ta import stats as stats_mod
from bot.ta.prepare import Prepared
from bot.ta.state import (
    add_admin,
    clear_active_model,
    clear_history,
    get_active_group_id,
    get_active_model,
    get_group_stats,
    get_quiz_scores,
    get_total_quizzes,
    get_user_chat,
    list_admins,
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

    Replies are always DM'd to the admin. If the command was typed in a
    group, the router has already deleted the original message.
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
        "/help — this message",
        "/info — workspace config",
        "/admin — list admins",
        "/admin add @user — promote",
        "/admin remove @user — demote",
        "/group — list linked groups",
        "/group &lt;N|chatId&gt; — switch active group",
        "/model — show current model",
        "/model &lt;name&gt; — switch chat model",
        "/reset — clear history + default model for active group",
        "/doc — list docs",
        "/doc add &lt;title&gt;\\n&lt;content&gt; — index a doc",
        "/doc update &lt;title&gt;\\n&lt;content&gt; — replace a doc",
        "/doc delete &lt;title&gt; — remove a doc",
        "/quiz [topic] — post a multiple-choice question",
        "/reveal — end active quiz early",
        "/stats — message counts + quiz scores",
        "/stats reset — clear this context's stats",
        "/grade — engagement score per student",
        "/grade @user — single student breakdown",
        "/purge — bulk delete group messages + reset state",
        "/announce &lt;message&gt; — stage an announcement for the active group",
        "  (reply <b>send it</b> to post or <b>cancel</b> to discard)",
        "",
        f"<b>Valid models</b>: {', '.join(VALID_MODELS)}",
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
        options = ", ".join(f"<code>{m}</code>" for m in VALID_MODELS)
        send_message(
            p.user_id,
            f"Current model: <code>{current}</code>\n"
            f"Valid options: {options}\n"
            f"Usage: /model &lt;name&gt;",
            parse_mode="HTML",
        )
        return
    choice = args.split()[0]
    if choice not in VALID_MODELS:
        send_message(
            p.user_id,
            f"Invalid model: <code>{choice}</code>\n"
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
            lines.append(f"{marker}{i}. <code>{chat_id}</code> — {title}")
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
        send_message(p.user_id, f"No linked group matches <code>{choice}</code>.", parse_mode="HTML")
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


# ── /stats [reset] ────────────────────────────────────────────────────────
@_register("stats")
def _cmd_stats(p: Prepared) -> None:
    sub = (p.command_args or "").strip().lower()
    if sub == "reset":
        reset_group_stats(p.group_key)
        send_message(p.user_id, f"✅ Cleared stats for <code>{p.group_key}</code>.", parse_mode="HTML")
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
        name = data.get("firstName") or data.get("username") or "(unknown)"
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
            name = data.get("firstName") or data.get("username") or "(unknown)"
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
            send_message(p.user_id, f"No data for @{target_username} in <code>{p.group_key}</code>.",
                         parse_mode="HTML")
            return
        send_message(p.user_id, _render_grade_detail(match), parse_mode="HTML")
        return

    if not engagement:
        send_message(p.user_id, "No data yet for this context.")
        return

    engagement.sort(key=lambda e: e.total_pts, reverse=True)
    lines = [f"<b>Engagement</b> — <code>{p.group_key}</code> (quizzes posted: {total_q})", ""]
    for e in engagement[:25]:
        flag = " ⚠️" if e.inactive else ""
        lines.append(
            f"• {e.display_name}{flag} — <b>{e.total_pts:.0f}/100</b>  "
            f"(msgs {e.messages_pts:.0f} / part {e.particip_pts:.0f} / acc {e.accuracy_pts:.0f})"
        )
    send_message(p.user_id, "\n".join(lines), parse_mode="HTML")


def _render_grade_detail(e: "stats_mod.Engagement") -> str:
    flag = " ⚠️ (inactive >7d)" if e.inactive else ""
    return (
        f"<b>{e.display_name}</b>{flag}\n"
        f"Total: <b>{e.total_pts:.0f}/100</b>\n"
        f"  • Messages: {e.messages} → {e.messages_pts:.0f}/{stats_mod.W_MESSAGES}\n"
        f"  • Participation: {e.attempts}/{e.total_quizzes} "
        f"({e.participation_pct:.0f}%) → {e.particip_pts:.0f}/{stats_mod.W_PARTICIPATION}\n"
        f"  • Accuracy: {e.correct}/{e.attempts} "
        f"({e.accuracy_pct:.0f}%) → {e.accuracy_pts:.0f}/{stats_mod.W_ACCURACY}"
    )


# ── /announce ─────────────────────────────────────────────────────────────
@_register("announce")
def _cmd_announce(p: Prepared) -> None:
    ann_mod.start(p)


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
    for mid in range(2, current_id + 1):
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


# ── Helpers ───────────────────────────────────────────────────────────────
def _first_username(raw: str) -> str:
    """Extract the first @username (or bare username) from the argument string."""
    for tok in raw.split():
        clean = tok.lstrip("@").lower().strip()
        if clean:
            return clean
    return ""
