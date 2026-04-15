"""Group + DM welcome messages. Text parameterized by env (§9 shape)."""
from __future__ import annotations

from bot.clients import bot
from bot.config import INSTRUCTOR_NAME, PERMANENT_ADMIN, TA_RATE_LIMIT
from bot.ta.state import mark_dm_welcomed, mark_group_welcomed, register_group


GROUP_WELCOME = (
    "\U0001F44B Welcome! I'm the AI Teaching Assistant for the Summer 2026 AI Bot "
    f"Workshop in Armenia, lead by {INSTRUCTOR_NAME} (@{PERMANENT_ADMIN}).\n\n"
    "I'm here to help with questions about programming, AI/ML, data science, and "
    "all course-related topics. Feel free to ask anything technical \u2014 send your "
    "question here or @mention me directly!\n\n"
    "A few notes:\n"
    "\u2022 I only answer course-related questions\n"
    f"\u2022 Each student has a limit of {TA_RATE_LIMIT} questions per hour\n"
    "\u2022 @mentions always get a reply\n\n"
    "Let the learning begin! \U0001F680"
)

DM_WELCOME = (
    "Hello! \U0001F44B I'm the AI Teaching Assistant for the Summer 2026 AI Bot "
    f"Workshop in Armenia, lead by {INSTRUCTOR_NAME} (@{PERMANENT_ADMIN}).\n\n"
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
    register_group(chat_id, title)
    if mark_group_welcomed(chat_id, title):
        try:
            bot.send_message(chat_id, GROUP_WELCOME)
        except Exception as e:
            print(f"[ta.welcome] send_group_welcome error: {e}")


def send_dm_welcome_once(chat_id: int | str, user_id: int) -> bool:
    if not mark_dm_welcomed(user_id):
        return False
    try:
        bot.send_message(chat_id, DM_WELCOME)
        return True
    except Exception as e:
        print(f"[ta.welcome] send_dm_welcome error: {e}")
        return False
