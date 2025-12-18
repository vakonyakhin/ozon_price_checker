import os

# --- Telegram Bot ---
# ВАЖНО: Получите токен у @BotFather в Telegram и вставьте его сюда
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8452812329:AAHOKCmBWuaxAvDq_X_jsZimdJI7mgYIMAw")

# --- Redis ---
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))

# --- Scheduler ---
# Интервал проверки цен в секундах (5 минут = 300 секунд)
PRICE_CHECK_INTERVAL = 300
