# Все настройки бота в одном месте. Секреты читаются из файла .env.
import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5")

# Контакты приёмной комиссии — показываются по кнопке «Связаться с приёмной».
ADMISSIONS_CONTACTS = os.getenv(
    "ADMISSIONS_CONTACTS",
    "admission@almau.edu.kz\nhttps://almau.edu.kz/ru/admission/",
)

# Сколько последних сообщений диалога помнит бот.
MAX_HISTORY_MESSAGES = 20

if not ANTHROPIC_API_KEY:
    raise SystemExit(
        "Не найден ANTHROPIC_API_KEY. Создай файл .env (скопируй .env.example) и заполни ключи."
    )
