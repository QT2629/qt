# Pro4U — ИИ-консультант для абитуриентов AlmaU в Telegram.
#
# Как это работает:
#   пользователь пишет боту -> бот добавляет базу знаний AlmaU и историю диалога ->
#   отправляет в Claude -> пересылает ответ пользователю.
#
# Запуск: python bot.py

import logging

import anthropic
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from claude_client import Refused, ask_claude
from knowledge import build_knowledge_text
from texts import MENU_PROMPTS, TEXTS, t

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
# HTTP-библиотеки пишут в лог каждый запрос — это шумно, приглушаем.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logger = logging.getLogger("pro4u")

# База знаний загружается один раз при запуске.
KNOWLEDGE_TEXT = build_knowledge_text()

# Telegram не даёт отправить сообщение длиннее 4096 символов.
TELEGRAM_MESSAGE_LIMIT = 4096

# Для каждого текста кнопки (на обоих языках) запоминаем, что это за кнопка.
BUTTON_KEYS = {
    TEXTS[lang][key]: key
    for lang in TEXTS
    for key in ("btn_pick", "btn_programs", "btn_ent", "btn_money", "btn_admission", "btn_contacts")
}


# ---------------------------------------------------------------------------
# Клавиатуры
# ---------------------------------------------------------------------------
def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru"),
            InlineKeyboardButton("🇰🇿 Қазақша", callback_data="lang:kz"),
        ]]
    )


def menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [t(lang, "btn_pick")],
            [t(lang, "btn_programs"), t(lang, "btn_ent")],
            [t(lang, "btn_money"), t(lang, "btn_admission")],
            [t(lang, "btn_contacts")],
        ],
        resize_keyboard=True,
    )


# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — выбор языка и новый разговор."""
    context.user_data["history"] = []
    await update.message.reply_text(t("ru", "choose_lang"), reply_markup=language_keyboard())


async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пользователь нажал кнопку с языком."""
    query = update.callback_query
    await query.answer()
    lang = query.data.split(":")[1]
    context.user_data["lang"] = lang
    await query.edit_message_text(t(lang, "lang_set"))
    await query.message.reply_text(t(lang, "welcome"), reply_markup=menu_keyboard(lang))


async def change_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/lang — сменить язык."""
    await update.message.reply_text(t("ru", "choose_lang"), reply_markup=language_keyboard())


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/reset — забыть историю диалога."""
    context.user_data["history"] = []
    lang = context.user_data.get("lang", "ru")
    await update.message.reply_text(t(lang, "reset_done"), reply_markup=menu_keyboard(lang))


# ---------------------------------------------------------------------------
# Сообщения
# ---------------------------------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обычное сообщение или нажатие кнопки меню."""
    lang = context.user_data.get("lang", "ru")
    text = update.message.text
    button = BUTTON_KEYS.get(text)

    # Кнопка «Приёмная комиссия» — отвечаем сами, без ИИ.
    if button == "btn_contacts":
        await update.message.reply_text(t(lang, "contacts").format(contacts=config.ADMISSIONS_CONTACTS))
        return

    # Остальные кнопки превращаем в готовый вопрос для ИИ.
    user_text = t(lang, MENU_PROMPTS[button]) if button else text
    await reply_with_claude(update, context, lang, user_text)


async def reply_with_claude(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str, user_text: str) -> None:
    chat_id = update.effective_chat.id
    history = context.user_data.setdefault("history", [])
    logger.info("Чат %s [%s]: %s", chat_id, lang, user_text[:100])

    # Показываем «печатает...», пока Claude думает.
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        answer = await ask_claude(KNOWLEDGE_TEXT, lang, history + [{"role": "user", "content": user_text}])
        if answer:
            logger.info("Ответ Claude для чата %s получен (%d символов)", chat_id, len(answer))
            # Запоминаем вопрос и ответ, чтобы Claude помнил контекст.
            history += [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": answer},
            ]
            # Храним только последние сообщения (обрезаем парами).
            while len(history) > config.MAX_HISTORY_MESSAGES:
                del history[:2]
        else:
            answer = t(lang, "empty")
    except Refused:
        answer = t(lang, "refusal")
    except anthropic.AuthenticationError:
        logger.error("Неверный ANTHROPIC_API_KEY — проверь файл .env")
        answer = t(lang, "err_config")
    except anthropic.PermissionDeniedError as e:
        logger.error("Нет доступа к API (проверь права ключа): %s", e)
        answer = t(lang, "err_config")
    except anthropic.RateLimitError:
        logger.warning("Слишком много запросов к Claude (rate limit)")
        answer = t(lang, "err_busy")
    except anthropic.APITimeoutError:
        logger.warning("Claude не ответил вовремя (timeout)")
        answer = t(lang, "err_timeout")
    except anthropic.APIConnectionError:
        logger.warning("Нет соединения с Claude API")
        answer = t(lang, "err_connection")
    except anthropic.APIStatusError as e:
        if e.status_code == 402:
            logger.error("Закончились деньги на балансе Anthropic API — пополни в консоли")
            answer = t(lang, "err_config")
        else:
            logger.error("Ошибка Claude API %s: %s", e.status_code, e)
            answer = t(lang, "err_generic")
    except Exception:
        logger.exception("Неожиданная ошибка")
        answer = t(lang, "err_generic")

    # Длинный ответ режем на куски, чтобы Telegram его принял.
    for i in range(0, len(answer), TELEGRAM_MESSAGE_LIMIT):
        await update.message.reply_text(
            answer[i : i + TELEGRAM_MESSAGE_LIMIT], reply_markup=menu_keyboard(lang)
        )


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------
def main() -> None:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lang", change_language))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CallbackQueryHandler(choose_language, pattern=r"^lang:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Pro4U запущен (модель: %s). Остановить: Ctrl+C", config.CLAUDE_MODEL)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
