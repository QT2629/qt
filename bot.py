# Pro4U — ИИ-консультант для абитуриентов AlmaU в Telegram.
#
# Как это работает:
#   • кнопки меню (специальности по ЕНТ, цены, документы, даты, контакты) отвечают сами, без ИИ — бесплатно;
#   • анкета «Подобрать специальность» собирает ответы кнопками и делает один запрос к ИИ;
#   • на свободные вопросы отвечает Claude: бот отправляет ему только нужные программы;
#   • на каждого человека действует дневной лимит вопросов к ИИ;
#   • история, лимиты и статистика сохраняются в папке data/ и переживают перезапуск.
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
    PicklePersistence,
    filters,
)

import catalog
import config
import stats
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


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/myid — показать свой Telegram ID (нужен, чтобы стать администратором)."""
    await update.message.reply_text(f"Ваш Telegram ID: {update.effective_user.id}")


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats — статистика за сутки и за 7 дней (только для администраторов)."""
    if update.effective_user.id not in config.ADMIN_IDS:
        return
    await update.message.reply_text(stats.report(1) + "\n\n" + stats.report(7))


# ---------------------------------------------------------------------------
# Кнопки под сообщениями (inline)
# ---------------------------------------------------------------------------
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    lang = get_lang(context)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if data in ("fb:up", "fb:down"):  # оценка ответа ИИ
        stats.log_event(user_id, "feedback_up" if data == "fb:up" else "feedback_down")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.answer("Рахмет! 🙏" if lang == "kz" else "Спасибо за оценку! 🙏")
        return

    if data.startswith("lang:"):
        lang = data.split(":")[1]
        context.user_data["lang"] = lang
        await query.edit_message_text(t(lang, "lang_set"))
        await context.bot.send_message(chat_id, t(lang, "welcome"), reply_markup=menu_keyboard(lang))

    elif data.startswith("ent:"):  # «Мои предметы ЕНТ» → список программ группы
        group = data.split(":")[1]
        stats.log_event(user_id, "button", f"ЕНТ: {group}")
        await query.edit_message_text(catalog.group_text(group, lang), reply_markup=group_keyboard(group, lang))

    elif data.startswith("p:"):  # карточка программы
        code = data.split(":")[1]
        stats.log_event(user_id, "button", f"карточка {code}")
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
        stats.log_event(user_id, "quiz_done", ",".join(quiz["interests"]))
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


# Названия кнопок меню для статистики.
BUTTON_STATS_NAMES = {
    "btn_pick": "Подобрать специальность", "btn_ent": "Мои предметы ЕНТ", "btn_prices": "Специальности и цены",
    "btn_docs": "Документы", "btn_dates": "Важные даты", "btn_contacts": "Приёмная комиссия",
}


# ---------------------------------------------------------------------------
# Сообщения
# ---------------------------------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обычное сообщение или нажатие кнопки меню."""
    lang = get_lang(context)
    text = update.message.text
    chat_id = update.effective_chat.id
    button = BUTTON_KEYS.get(text)
    if button:
        stats.log_event(update.effective_user.id, "button", BUTTON_STATS_NAMES[button])

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
        stats.log_event(chat_id, "limit")
        await send_long(context, chat_id, t(lang, "limit").format(
            limit=config.DAILY_AI_LIMIT, contacts=config.ADMISSIONS_CONTACTS), lang)
        return

    history = context.user_data.setdefault("history", [])
    logger.info("Чат %s [%s] программы %s: %s", chat_id, lang, codes, user_text[:100])

    # Показываем «печатает...», пока Claude думает.
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    details = catalog.program_details(codes) if codes else None
    messages = history + [{"role": "user", "content": with_details(user_text, details)}]

    feedback = None
    try:
        answer, cost = await ask_claude(KNOWLEDGE_TEXT, lang, messages)
        stats.log_event(chat_id, "ai", ",".join(codes), cost)
        if answer:
            feedback = InlineKeyboardMarkup([[InlineKeyboardButton("👍", callback_data="fb:up"),
                                              InlineKeyboardButton("👎", callback_data="fb:down")]])
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
    except anthropic.AnthropicError as e:
        stats.log_event(chat_id, "error", type(e).__name__)
        answer = api_error_text(e, lang)
    except Exception:
        logger.exception("Неожиданная ошибка")
        stats.log_event(chat_id, "error", "unexpected")
        answer = t(lang, "err_generic")

    await send_long(context, chat_id, answer, lang, last_markup=feedback)


def api_error_text(err: Exception, lang: str) -> str:
    """Понятный текст для пользователя + подробности в лог."""
    if isinstance(err, anthropic.AuthenticationError):
        logger.error("Неверный ANTHROPIC_API_KEY — проверь файл .env")
        return t(lang, "err_config")
    if isinstance(err, anthropic.PermissionDeniedError):
        logger.error("Нет доступа к API (проверь права ключа): %s", err)
        return t(lang, "err_config")
    if isinstance(err, anthropic.RateLimitError):
        logger.warning("Слишком много запросов к Claude (rate limit)")
        return t(lang, "err_busy")
    if isinstance(err, anthropic.APITimeoutError):
        logger.warning("Claude не ответил вовремя (timeout)")
        return t(lang, "err_timeout")
    if isinstance(err, anthropic.APIConnectionError):
        logger.warning("Нет соединения с Claude API")
        return t(lang, "err_connection")
    if isinstance(err, anthropic.APIStatusError) and err.status_code == 402:
        logger.error("Закончились деньги на балансе Anthropic API — пополни в консоли")
        return t(lang, "err_config")
    logger.error("Ошибка Claude API: %s", err)
    return t(lang, "err_generic")


async def send_long(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, lang: str,
                    last_markup: InlineKeyboardMarkup | None = None) -> None:
    """Длинный текст режем на куски, чтобы Telegram его принял.
    К последнему куску можно прикрепить кнопки (например, 👍/👎)."""
    chunks = [text[i: i + TELEGRAM_MESSAGE_LIMIT] for i in range(0, len(text), TELEGRAM_MESSAGE_LIMIT)]
    for n, chunk in enumerate(chunks):
        is_last = n == len(chunks) - 1
        markup = last_markup if (is_last and last_markup) else menu_keyboard(lang)
        await context.bot.send_message(chat_id, chunk, reply_markup=markup)


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------
def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("Не найден TELEGRAM_BOT_TOKEN. Заполни его в файле .env.")
    Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)
    persistence = PicklePersistence(filepath=Path(config.DATA_DIR) / "bot_state.pickle")
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).persistence(persistence).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lang", change_language))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("myid", my_id))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Pro4U запущен (модель: %s, лимит %s вопросов к ИИ в день). Остановить: Ctrl+C",
                config.CLAUDE_MODEL, config.DAILY_AI_LIMIT)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
