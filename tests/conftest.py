"""
Mocks all external dependencies before any bot module is imported.
This lets tests run without real API keys or network connections.
"""
import os
import sys
from unittest.mock import MagicMock

# ── Fake environment variables ─────────────────────────────────────────────────
os.environ["TELEGRAM_BOT_TOKEN"] = "1234567890:fake_token"
os.environ["AI_API_KEY"]         = "fake_api_key"
os.environ["UPSTASH_REDIS_REST_URL"]   = "https://fake.upstash.io"
os.environ["UPSTASH_REDIS_REST_TOKEN"] = "fake_redis_token"
os.environ["UPSTASH_VECTOR_REST_URL"]   = "https://fake-vector.upstash.io"
os.environ["UPSTASH_VECTOR_REST_TOKEN"] = "fake_vector_token"
os.environ["QSTASH_TOKEN"]                  = "fake_qstash_token"
os.environ["QSTASH_CURRENT_SIGNING_KEY"]    = "fake_qstash_current_key"
os.environ["QSTASH_NEXT_SIGNING_KEY"]       = "fake_qstash_next_key"
os.environ["BLOB_READ_WRITE_TOKEN"]         = "fake_blob_token"
os.environ["PERMANENT_ADMIN"]               = "ediksimonian"
os.environ["PROD_URL"]                      = "https://ta-bot-test.vercel.app"

# ── Mock external packages ─────────────────────────────────────────────────────
mock_bot_instance = MagicMock()
mock_bot_instance.get_me.return_value = MagicMock(id=42, username="testbot")
# Decorators must pass through so handler functions remain callable
mock_bot_instance.message_handler.return_value = lambda f: f

mock_telebot = MagicMock()
mock_telebot.TeleBot.return_value = mock_bot_instance

# Flask mock: make @app.route() pass through too
mock_flask = MagicMock()
mock_flask_app = MagicMock()
mock_flask_app.route.return_value = lambda f: f
mock_flask.Flask.return_value = mock_flask_app

# Upstash Vector mock — exposes Index(url, token) returning a MagicMock
mock_upstash_vector = MagicMock()
mock_upstash_vector.Index.return_value = MagicMock()

sys.modules["telebot"]         = mock_telebot
sys.modules["telebot.types"]   = MagicMock()
sys.modules["openai"]          = MagicMock()
sys.modules["upstash_redis"]   = MagicMock()
sys.modules["upstash_vector"]  = mock_upstash_vector
sys.modules["flask"]           = mock_flask
sys.modules["gradio_client"]   = MagicMock()
