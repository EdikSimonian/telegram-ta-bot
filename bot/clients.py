import telebot
from openai import OpenAI
from upstash_redis import Redis
from bot.config import TELEGRAM_TOKEN, AI_API_KEY, AI_BASE_URL, UPSTASH_URL, UPSTASH_TOKEN

bot      = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
ai       = OpenAI(base_url=AI_BASE_URL, api_key=AI_API_KEY)
redis    = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)
BOT_INFO = bot.get_me()  # cached at startup for group mention detection
