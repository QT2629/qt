# Все настройки бота в одном месте. Секреты читаются из файла .env.
import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# Строка-пример из .env.example («sk-ant-вставь-сюда-свой-ключ») — это не ключ.
if ANTHROPIC_API_KEY and "вставь" in ANTHROPIC_API_KEY:
    ANTHROPIC_API_KEY = None

# Ключ OpenAI — только для распознавания голосовых сообщений. Без него бот просит писать текстом.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY and "вставь" in OPENAI_API_KEY:
    OPENAI_API_KEY = None
# Модель распознавания: gpt-4o-mini-transcribe (дешевле) или gpt-4o-transcribe (точнее).
VOICE_MODEL = os.getenv("VOICE_MODEL", "gpt-4o-mini-transcribe")
# Голосовые длиннее этого (в секундах) не распознаём — просим короче.
MAX_VOICE_SECONDS = int(os.getenv("MAX_VOICE_SECONDS", "90"))

# Самая дешёвая модель Claude. Если качества не хватит — claude-sonnet-5 или claude-opus-5.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")

# Контакты приёмной комиссии — показываются по кнопке «Приёмная комиссия».
ADMISSIONS_CONTACTS = os.getenv(
    "ADMISSIONS_CONTACTS",
    "admission@almau.edu.kz\nhttps://almau.edu.kz/ru/admission/",
).replace("\\n", "\n")  # на сервере (Railway) \n приходит как два символа — превращаем в перенос строки

# Сколько вопросов к ИИ один человек может задать за сутки. Кнопки без ИИ не считаются.
DAILY_AI_LIMIT = int(os.getenv("DAILY_AI_LIMIT", "30"))

# Папка, где бот хранит историю диалогов, лимиты и статистику (переживают перезапуск).
DATA_DIR = os.getenv("DATA_DIR", "data")

# Telegram ID администраторов через запятую — им доступна команда /stats.
# Свой ID можно узнать командой /myid в боте.
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

# Сколько последних сообщений диалога помнит бот.
MAX_HISTORY_MESSAGES = 12

# Без ANTHROPIC_API_KEY бот тоже запускается: кнопки меню работают, а на вопросы к ИИ
# он отвечает, что ИИ пока не подключён. Удобно, чтобы проверить бота до оплаты API.
