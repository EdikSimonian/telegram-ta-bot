"""Admin command dispatcher + handlers.

Stage 3 ships the read-only and admin-list mutation commands. Later
stages add /doc, /quiz, /stats, /grade, /announce, /purge, /reveal.
"""
from __future__ import annotations

from typing import Callable

from bot.config import BOT_ENV, DEFAULT_MODEL, PERMANENT_ADMIN, VALID_MODELS
from bot.ta import docs as docs_mod
from bot.ta.prepare import Prepared
from bot.ta.state import (
    add_admin,
    clear_active_model,
    clear_history,
    get_active_group_id,
    get_active_model,
    get_user_chat,
    list_admins,
    list_groups,
    remove_admin,
    set_active_group_id,
    set_active_model,
)
from bot.ta.tg import send_message


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
        "",
        "<b>Coming later</b>",
        "/quiz, /reveal, /stats, /grade, /announce, /purge",
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


# ── Helpers ───────────────────────────────────────────────────────────────
def _first_username(raw: str) -> str:
    """Extract the first @username (or bare username) from the argument string."""
    for tok in raw.split():
        clean = tok.lstrip("@").lower().strip()
        if clean:
            return clean
    return ""
