# Pro4U — ИИ-консультант для абитуриентов AlmaU в Telegram.
#
# Как это работает:
#   • кнопки меню (специальности по ЕНТ, цены, документы, даты, контакты) отвечают сами, без ИИ — бесплатно;
#   • анкета «Подобрать специальность» собирает ответы кнопками и делает один запрос к ИИ;
#   • на свободные вопросы отвечает Claude: бот отправляет ему только нужные программы;
#   • на каждого человека действует дневной лимит вопросов к ИИ.
#
# Запуск: python bot.py

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

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

import catalog
import config
from claude_client import Refused, ask_claude
from knowledge import build_knowledge_text
from prompts import with_details
from texts import MENU_BUTTONS, TEXTS, t

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
# HTTP-библиотеки пишут в лог каждый запрос — это шумно, приглушаем.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logger = logging.getLogger("pro4u")

# Постоянная часть базы знаний загружается один раз при запуске.
KNOWLEDGE_TEXT = build_knowledge_text()
STATIC_DIR = Path(__file__).parent / "knowledge" / "static"

# Telegram не даёт отправить сообщение длиннее 4096 символов.
TELEGRAM_MESSAGE_LIMIT = 4096
# Казахстан живёт по UTC+5 — по этому времени обнуляется дневной лимит.
ALMATY_TZ = timezone(timedelta(hours=5))
MAX_INTERESTS = 3

# Для каждого текста кнопки меню (на обоих языках) запоминаем, что это за кнопка.
BUTTON_KEYS = {TEXTS[lang][key]: key for lang in TEXTS for key in MENU_BUTTONS}


def static_text(name: str, lang: str) -> str:
    return (STATIC_DIR / f"{name}_{lang}.md").read_text(encoding="utf-8").strip()


def get_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("lang", "ru")


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
            [t(lang, "btn_ent"), t(lang, "btn_prices")],
            [t(lang, "btn_docs"), t(lang, "btn_dates")],
            [t(lang, "btn_contacts")],
        ],
        resize_keyboard=True,
    )


def ent_keyboard(lang: str, prefix: str, with_unknown: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(v[lang], callback_data=f"{prefix}{k}")] for k, v in catalog.ENT_GROUPS.items()]
    if with_unknown:
        rows.append([InlineKeyboardButton(t(lang, "ent_unknown"), callback_data=f"{prefix}unknown")])
    return InlineKeyboardMarkup(rows)


def group_keyboard(group: str, lang: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(catalog.name(p, lang), callback_data=f"p:{p['code']}")]
            for p in catalog.programs_in_group(group)]
    if len(rows) > 1:
        rows.append([InlineKeyboardButton(t(lang, "btn_help_choose"), callback_data=f"qg:{group}")])
    return InlineKeyboardMarkup(rows)


def interests_keyboard(lang: str, selected: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(("✅ " if tag in selected else "") + info[lang], callback_data=f"q:int:{tag}")
        for tag, info in catalog.INTERESTS.items()
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(t(lang, "q_done"), callback_data="q:done")])
    return InlineKeyboardMarkup(rows)


def values_keyboard(lang: str) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(v[lang], callback_data=f"q:val:{k}") for k, v in catalog.VALUES.items()]
    return InlineKeyboardMarkup([buttons[i:i + 2] for i in range(0, len(buttons), 2)])


# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — выбор языка и новый разговор."""
    context.user_data["history"] = []
    context.user_data["recent"] = []
    await update.message.reply_text(t("ru", "choose_lang"), reply_markup=language_keyboard())


async def change_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/lang — сменить язык."""
    await update.message.reply_text(t("ru", "choose_lang"), reply_markup=language_keyboard())


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/reset — забыть историю диалога."""
    context.user_data["history"] = []
    context.user_data["recent"] = []
    lang = get_lang(context)
    await update.message.reply_text(t(lang, "reset_done"), reply_markup=menu_keyboard(lang))


# ---------------------------------------------------------------------------
# Кнопки под сообщениями (inline)
# ---------------------------------------------------------------------------
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    lang = get_lang(context)
    chat_id = update.effective_chat.id

    if data.startswith("lang:"):
        lang = data.split(":")[1]
        context.user_data["lang"] = lang
        await query.edit_message_text(t(lang, "lang_set"))
        await context.bot.send_message(chat_id, t(lang, "welcome"), reply_markup=menu_keyboard(lang))

    elif data.startswith("ent:"):  # «Мои предметы ЕНТ» → список программ группы
        group = data.split(":")[1]
        await query.edit_message_text(catalog.group_text(group, lang), reply_markup=group_keyboard(group, lang))

    elif data.startswith("p:"):  # карточка программы
        code = data.split(":")[1]
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "btn_ask_ai"), callback_data=f"a:{code}")]])
        await context.bot.send_message(chat_id, catalog.program_card(code, lang), reply_markup=keyboard)

    elif data.startswith("a:"):  # следующий вопрос будет про эту программу
        code = data.split(":")[1]
        remember_programs(context, [code])
        await context.bot.send_message(
            chat_id, t(lang, "ask_about").format(name=catalog.name(catalog.PROGRAMS[code], lang)))

    elif data.startswith("qg:"):  # анкета, когда группа ЕНТ уже известна
        context.user_data["quiz"] = {"ent": data.split(":")[1], "interests": []}
        await context.bot.send_message(chat_id, t(lang, "q_interests"), reply_markup=interests_keyboard(lang, []))

    elif data.startswith("q:ent:"):
        context.user_data["quiz"] = {"ent": data.split(":")[2], "interests": []}
        await query.edit_message_text(t(lang, "q_interests"), reply_markup=interests_keyboard(lang, []))

    elif data.startswith("q:int:"):
        quiz = context.user_data.setdefault("quiz", {"ent": "unknown", "interests": []})
        tag = data.split(":")[2]
        if tag in quiz["interests"]:
            quiz["interests"].remove(tag)
        elif len(quiz["interests"]) < MAX_INTERESTS:
            quiz["interests"].append(tag)
        await query.edit_message_reply_markup(reply_markup=interests_keyboard(lang, quiz["interests"]))

    elif data == "q:done":
        quiz = context.user_data.get("quiz")
        if not quiz or not quiz["interests"]:
            await context.bot.send_message(chat_id, t(lang, "q_need_interest"))
            return
        await query.edit_message_text(t(lang, "q_values"), reply_markup=values_keyboard(lang))

    elif data.startswith("q:val:"):
        quiz = context.user_data.pop("quiz", None)
        if not quiz:
            return
        await query.edit_message_text(t(lang, "q_thinking"))
        await finish_quiz(context, chat_id, lang, quiz, data.split(":")[2])


async def finish_quiz(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str, quiz: dict, value: str) -> None:
    """Анкета заполнена — один запрос к ИИ с подходящими программами."""
    group = None if quiz["ent"] == "unknown" else quiz["ent"]
    ent_text = catalog.ENT_GROUPS[group][lang] if group else t(lang, "ent_unknown_text")
    user_text = t(lang, "q_request").format(
        ent=ent_text,
        interests=", ".join(catalog.INTERESTS[tag][lang] for tag in quiz["interests"]),
        value=catalog.VALUES[value][lang],
    )
    codes = catalog.programs_for(quiz["interests"], group=group, limit=6)
    await reply_with_claude(context, chat_id, lang, user_text, codes)


# ---------------------------------------------------------------------------
# Сообщения
# ---------------------------------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обычное сообщение или нажатие кнопки меню."""
    lang = get_lang(context)
    text = update.message.text
    chat_id = update.effective_chat.id
    button = BUTTON_KEYS.get(text)

    # Кнопки меню, которые работают без ИИ.
    if button == "btn_pick":
        await update.message.reply_text(t(lang, "q_ent"), reply_markup=ent_keyboard(lang, "q:ent:", True))
    elif button == "btn_ent":
        await update.message.reply_text(t(lang, "choose_ent"), reply_markup=ent_keyboard(lang, "ent:", False))
    elif button == "btn_prices":
        await send_long(context, chat_id, catalog.price_list_text(lang), lang)
    elif button == "btn_docs":
        await update.message.reply_text(static_text("documents", lang))
    elif button == "btn_dates":
        await update.message.reply_text(static_text("dates", lang))
    elif button == "btn_contacts":
        await update.message.reply_text(t(lang, "contacts").format(contacts=config.ADMISSIONS_CONTACTS))
    else:
        # Свободный вопрос → ИИ с программами, о которых идёт речь.
        codes = catalog.relevant_programs(text, context.user_data.get("recent", []))
        await reply_with_claude(context, chat_id, lang, text, codes)


def remember_programs(context: ContextTypes.DEFAULT_TYPE, codes: list[str]) -> None:
    """Запоминаем последние обсуждаемые программы, чтобы понимать «а сколько она стоит?»."""
    recent = context.user_data.get("recent", [])
    context.user_data["recent"] = (codes + [c for c in recent if c not in codes])[:4]


def take_ai_quota(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет дневной лимит вопросов к ИИ и учитывает новый вопрос."""
    today = datetime.now(ALMATY_TZ).date().isoformat()
    usage = context.user_data.get("usage")
    if not usage or usage["date"] != today:
        usage = {"date": today, "count": 0}
    if usage["count"] >= config.DAILY_AI_LIMIT:
        context.user_data["usage"] = usage
        return False
    usage["count"] += 1
    context.user_data["usage"] = usage
    return True


async def reply_with_claude(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str,
                            user_text: str, codes: list[str]) -> None:
    if not take_ai_quota(context):
        await send_long(context, chat_id, t(lang, "limit").format(
            limit=config.DAILY_AI_LIMIT, contacts=config.ADMISSIONS_CONTACTS), lang)
        return

    history = context.user_data.setdefault("history", [])
    logger.info("Чат %s [%s] программы %s: %s", chat_id, lang, codes, user_text[:100])

    # Показываем «печатает...», пока Claude думает.
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    details = catalog.program_details(codes) if codes else None
    messages = history + [{"role": "user", "content": with_details(user_text, details)}]

    try:
        answer = await ask_claude(KNOWLEDGE_TEXT, lang, messages)
        if answer:
            # В историю кладём вопрос без подробных данных — они добавляются заново к каждому вопросу.
            history += [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": answer},
            ]
            while len(history) > config.MAX_HISTORY_MESSAGES:
                del history[:2]
            remember_programs(context, catalog.find_programs(answer) or codes[:2])
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

    await send_long(context, chat_id, answer, lang)


async def send_long(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, lang: str) -> None:
    """Длинный текст режем на куски, чтобы Telegram его принял."""
    for i in range(0, len(text), TELEGRAM_MESSAGE_LIMIT):
        await context.bot.send_message(chat_id, text[i: i + TELEGRAM_MESSAGE_LIMIT],
                                       reply_markup=menu_keyboard(lang))


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------
def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("Не найден TELEGRAM_BOT_TOKEN. Заполни его в файле .env.")
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lang", change_language))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Pro4U запущен (модель: %s, лимит %s вопросов к ИИ в день). Остановить: Ctrl+C",
                config.CLAUDE_MODEL, config.DAILY_AI_LIMIT)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
