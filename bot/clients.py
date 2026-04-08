import telebot
from openai import OpenAI
from upstash_redis import Redis
from bot.config import (
    TELEGRAM_TOKEN, AI_API_KEY, AI_BASE_URL,
    ARMGPT_BASE_URL, ARMGPT_API_KEY,
    UPSTASH_URL, UPSTASH_TOKEN,
)

bot      = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
ai       = OpenAI(base_url=AI_BASE_URL, api_key=AI_API_KEY)
redis    = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)
BOT_INFO = bot.get_me()  # cached at startup for group mention detection

# Optional second OpenAI-compatible client for the ArmGPT Modal endpoint.
# None when ARMGPT_BASE_URL/ARMGPT_API_KEY are not configured.
armgpt = None
if ARMGPT_BASE_URL and ARMGPT_API_KEY:
    armgpt = OpenAI(base_url=ARMGPT_BASE_URL, api_key=ARMGPT_API_KEY)
