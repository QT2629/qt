# Все настройки бота в одном месте. Секреты читаются из файла .env.
import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# Строка-пример из .env.example («sk-ant-вставь-сюда-свой-ключ») — это не ключ.
if ANTHROPIC_API_KEY and "вставь" in ANTHROPIC_API_KEY:
    ANTHROPIC_API_KEY = None

# Самая дешёвая модель Claude. Если качества не хватит — claude-sonnet-5 или claude-opus-5.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")

# Контакты приёмной комиссии — показываются по кнопке «Приёмная комиссия».
ADMISSIONS_CONTACTS = os.getenv(
    "ADMISSIONS_CONTACTS",
    "Контакты приёмной комиссии нужного вуза — на его официальном сайте.\nСписок всех вузов с контактами — кнопка «☎️ Приёмные комиссии» в меню.",
).replace("\\n", "\n")  # на сервере (Railway) \n приходит как два символа — превращаем в перенос строки

# На какую дату собраны данные о вузах, ценах и грантах — показывается в карточках и в «Шансе на грант».
DATA_AS_OF = os.getenv("DATA_AS_OF", "октябрь 2026")
DATA_AS_OF_KZ = os.getenv("DATA_AS_OF_KZ", "2026 жылғы қазан")

# Оповещения администраторам о сбоях в боте (сообщение в Telegram). По умолчанию выключены:
# чтобы включить, на сервере задай переменную ERROR_ALERTS=1. Ошибки в любом случае пишутся в лог.
ERROR_ALERTS = os.getenv("ERROR_ALERTS", "0") == "1"

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
