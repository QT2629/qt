# Pro4U — Professional for you
# Telegram-бот-профориентолог на базе Claude (Anthropic API).
#
# Как это работает:
#   пользователь пишет боту -> бот отправляет текст в Claude -> Claude отвечает -> бот пересылает ответ в Telegram.

import logging
import os

import anthropic
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from prompts import SYSTEM_PROMPT

# ---------------------------------------------------------------------------
# 1. Настройки: читаем ключи из файла .env (а не пишем их прямо в коде)
# ---------------------------------------------------------------------------
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5")

if not TELEGRAM_BOT_TOKEN or not ANTHROPIC_API_KEY:
    raise SystemExit(
        "Не найдены ключи. Создай файл .env (скопируй .env.example) "
        "и заполни TELEGRAM_BOT_TOKEN и ANTHROPIC_API_KEY."
    )

# Сколько последних сообщений диалога помнить (чтобы Claude понимал контекст,
# но запрос не становился бесконечно большим и дорогим).
MAX_HISTORY_MESSAGES = 20

# Telegram не даёт отправить сообщение длиннее 4096 символов.
TELEGRAM_MESSAGE_LIMIT = 4096

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
# HTTP-библиотеки пишут в лог каждый запрос — это шумно, приглушаем.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logger = logging.getLogger("pro4u")

# ---------------------------------------------------------------------------
# 2. Клиент Claude. Async-версия, потому что python-telegram-bot тоже асинхронный.
# ---------------------------------------------------------------------------
claude = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY, timeout=60.0)

# История переписки: для каждого чата храним список сообщений.
# Хранится в памяти — после перезапуска бота история обнуляется (для начала это нормально).
chat_histories: dict[int, list[dict]] = {}


async def ask_claude(chat_id: int, user_text: str) -> str:
    """Отправляет сообщение пользователя в Claude и возвращает текст ответа."""
    history = chat_histories.setdefault(chat_id, [])
    messages = history + [{"role": "user", "content": user_text}]

    response = await claude.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=messages,
        # Если Claude Opus 5 откажется отвечать по правилам безопасности,
        # запрос автоматически повторится на запасной модели.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    if response.stop_reason == "refusal":
        return (
            "Извини, на такой вопрос я ответить не могу. "
            "Давай вернёмся к выбору профессии или университета 🙂"
        )

    # Ответ Claude состоит из "блоков". Нам нужны только текстовые.
    answer = "".join(block.text for block in response.content if block.type == "text").strip()
    if not answer:
        return "Хм, у меня не получилось сформулировать ответ. Попробуй задать вопрос чуть по-другому."

    # Запоминаем вопрос и ответ, чтобы Claude помнил контекст разговора.
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": answer})
    # Храним только последние сообщения. Обрезаем парами, чтобы история
    # всегда начиналась с сообщения пользователя.
    while len(history) > MAX_HISTORY_MESSAGES:
        del history[:2]

    return answer


# ---------------------------------------------------------------------------
# 3. Обработчики команд и сообщений Telegram
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /start — приветствие."""
    chat_histories.pop(update.effective_chat.id, None)
    await update.message.reply_text(
        "Привет! Я Pro4U — твой помощник в выборе профессии и университета 🎓\n\n"
        "Расскажи немного о себе: что тебе нравится делать, какие предметы "
        "в школе даются легче всего? А я помогу подобрать подходящие профессии.\n\n"
        "Команды:\n"
        "/start — начать заново\n"
        "/reset — очистить историю разговора"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /reset — забыть историю диалога."""
    chat_histories.pop(update.effective_chat.id, None)
    await update.message.reply_text("Готово, начинаем разговор с чистого листа ✨")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Любое обычное текстовое сообщение -> Claude -> ответ пользователю."""
    chat_id = update.effective_chat.id
    user_text = update.message.text
    logger.info("Сообщение от чата %s: %s", chat_id, user_text[:100])

    # Показываем "печатает...", пока Claude думает.
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        answer = await ask_claude(chat_id, user_text)
        logger.info("Ответ Claude для чата %s получен (%d символов)", chat_id, len(answer))
    except anthropic.AuthenticationError:
        logger.error("Неверный ANTHROPIC_API_KEY — проверь файл .env")
        answer = "Бот сейчас настраивается и временно не может ответить. Попробуй чуть позже 🙏"
    except anthropic.PermissionDeniedError as e:
        logger.error("Нет доступа к API (проверь права ключа): %s", e)
        answer = "Бот временно недоступен. Мы уже разбираемся — попробуй позже 🙏"
    except anthropic.RateLimitError:
        logger.warning("Слишком много запросов к Claude (rate limit)")
        answer = "Сейчас ко мне очень много вопросов 😅 Подожди минутку и напиши ещё раз."
    except anthropic.APITimeoutError:
        logger.warning("Claude не ответил вовремя (timeout)")
        answer = "Ответ занял слишком много времени ⏳ Попробуй ещё раз или сократи вопрос."
    except anthropic.APIConnectionError:
        logger.warning("Нет соединения с Claude API")
        answer = "Не получилось связаться с моим «мозгом» 🧠 Попробуй через пару минут."
    except anthropic.APIStatusError as e:
        # Любая другая ошибка от API (например, 500 или 529 "перегружен").
        if e.status_code == 402:
            logger.error("Закончились деньги на балансе Anthropic API — пополни в консоли")
        else:
            logger.error("Ошибка Claude API %s: %s", e.status_code, e)
        answer = "Что-то пошло не так на стороне ИИ. Попробуй ещё раз чуть позже 🙏"
    except Exception:
        logger.exception("Неожиданная ошибка")
        answer = "Упс, произошла ошибка. Попробуй ещё раз или напиши /reset."

    # Длинный ответ режем на куски, чтобы Telegram его принял.
    for i in range(0, len(answer), TELEGRAM_MESSAGE_LIMIT):
        await update.message.reply_text(answer[i : i + TELEGRAM_MESSAGE_LIMIT])


# ---------------------------------------------------------------------------
# 4. Запуск бота
# ---------------------------------------------------------------------------
def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    # Все текстовые сообщения, кроме команд (/что-то), отправляем в Claude.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Pro4U запущен (модель: %s). Остановить: Ctrl+C", CLAUDE_MODEL)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
