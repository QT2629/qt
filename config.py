# Все настройки бота в одном месте. Секреты читаются из файла .env.
import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Самая дешёвая модель Claude. Если качества не хватит — claude-sonnet-5 или claude-opus-5.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")

# Контакты приёмной комиссии — показываются по кнопке «Приёмная комиссия».
ADMISSIONS_CONTACTS = os.getenv(
    "ADMISSIONS_CONTACTS",
    "admission@almau.edu.kz\nhttps://almau.edu.kz/ru/admission/",
)

# Сколько вопросов к ИИ один человек может задать за сутки. Кнопки без ИИ не считаются.
DAILY_AI_LIMIT = int(os.getenv("DAILY_AI_LIMIT", "30"))

# Сколько последних сообщений диалога помнит бот.
MAX_HISTORY_MESSAGES = 12

if not ANTHROPIC_API_KEY:
    raise SystemExit(
        "Не найден ANTHROPIC_API_KEY. Создай файл .env (скопируй .env.example) и заполни ключи."
    )
