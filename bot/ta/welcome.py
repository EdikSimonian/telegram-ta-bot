"""Group + DM welcome messages. Exact text from spec §9."""
from __future__ import annotations

from bot.clients import bot
from bot.ta.state import mark_dm_welcomed, mark_group_welcomed, register_group


GROUP_WELCOME = (
    "\U0001F44B Welcome! I'm the AI Teaching Assistant for the Summer 2026 AI Bot "
    "Workshop in Armenia, lead by Edik Simonian (@ediksimonian).\n\n"
    "I'm here to help with questions about programming, AI/ML, data science, and "
    "all course-related topics. Feel free to ask anything technical \u2014 send your "
    "question here or @mention me directly!\n\n"
    "A few notes:\n"
    "\u2022 I only answer course-related questions\n"
    "\u2022 Each student has a limit of 10 questions per hour\n"
    "\u2022 @mentions always get a reply\n\n"
    "Let the learning begin! \U0001F680"
)

DM_WELCOME = (
    "Hello! \U0001F44B I'm the AI Teaching Assistant for the Summer 2026 AI Bot "
    "Workshop in Armenia, lead by Edik Simonian (@ediksimonian).\n\n"
    "I can help with questions about:\n"
    "\u2022 Python & programming concepts\n"
    "\u2022 Data science (NumPy, Pandas, visualization)\n"
    "\u2022 Machine learning & AI/ML topics\n"
    "\u2022 Course material and assignments\n\n"
    "\u26A0\uFE0F Note: I don't have access to the group chat history \u2014 this DM is a "
    "separate conversation from the group.\n\n"
    "Ask away! \U0001F680"
)


def send_group_welcome_once(chat_id: int | str, title: str) -> None:
    """Register the group and send the welcome once.

    Idempotent: safe to call on every my_chat_member event.
    """
    register_group(chat_id, title)
    if mark_group_welcomed(chat_id, title):
        try:
            bot.send_message(chat_id, GROUP_WELCOME)
        except Exception as e:
            print(f"[ta.welcome] send_group_welcome error: {e}")


def send_dm_welcome_once(chat_id: int | str, user_id: int) -> bool:
    """Send DM welcome the first time a user DMs us. Returns True if sent."""
    if not mark_dm_welcomed(user_id):
        return False
    try:
        bot.send_message(chat_id, DM_WELCOME)
        return True
    except Exception as e:
        print(f"[ta.welcome] send_dm_welcome error: {e}")
        return False
