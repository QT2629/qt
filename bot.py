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
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

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

import card
import catalog
import config
import stats
import universities
from claude_client import NoApiKey, Refused, ask_claude
from knowledge import build_knowledge_text
from prompts import with_details
from texts import LEGACY_BUTTONS, MENU_BUTTONS, TEXTS, t

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
BUTTON_KEYS = {TEXTS[lang][key]: key for lang in TEXTS for key in MENU_BUTTONS} | LEGACY_BUTTONS


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
            [t(lang, "btn_pick"), t(lang, "btn_chance")],
            [t(lang, "btn_ent"), t(lang, "btn_prices")],
            [t(lang, "btn_docs"), t(lang, "btn_dates")],
            [t(lang, "btn_contacts"), t(lang, "btn_share")],
        ],
        resize_keyboard=True,
    )


def ent_keyboard(lang: str, prefix: str, with_unknown: bool) -> InlineKeyboardMarkup:
    labels = universities.ENT_LABELS
    rows = [[InlineKeyboardButton(labels[g][lang], callback_data=f"{prefix}{g}")] for g in universities.all_groups()]
    if with_unknown:
        rows.append([InlineKeyboardButton(t(lang, "ent_unknown"), callback_data=f"{prefix}unknown")])
    return InlineKeyboardMarkup(rows)


def ent_unis_keyboard(group: str, lang: str) -> InlineKeyboardMarkup:
    """Предметы ЕНТ выбраны → в каких вузах есть программы."""
    rows = [[InlineKeyboardButton(universities.uni_name(slug, lang), callback_data=f"ug:{slug}:{group}")]
            for slug in universities.unis_with(group)]
    rows.append([InlineKeyboardButton(t(lang, "btn_help_choose"), callback_data=f"qg:{group}")])
    return InlineKeyboardMarkup(rows)


def unis_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(universities.uni_name(slug, lang), callback_data=f"u:{slug}")]
                                 for slug in universities.UNIS])


def uni_groups_keyboard(slug: str, lang: str) -> InlineKeyboardMarkup:
    labels = universities.ENT_LABELS
    return InlineKeyboardMarkup([[InlineKeyboardButton(labels[g][lang], callback_data=f"ug:{slug}:{g}")]
                                 for g in universities.groups_in(slug)])


def uni_programs_keyboard(slug: str, group: str, lang: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(universities.prog_name(p, lang)[:60], callback_data=f"up:{p['key']}")]
            for p in universities.programs_in(slug, group)]
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
def invite_link(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    """Ссылка на бота с кодом пригласившего — так в /stats видно, сколько людей пришло по приглашениям."""
    return f"https://t.me/{context.bot.username}?start=ref_{stats.ref_code(user_id)}"


def share_keyboard(context: ContextTypes.DEFAULT_TYPE, lang: str, user_id: int, extra=()) -> InlineKeyboardMarkup:
    url = "https://t.me/share/url?" + urlencode({"url": invite_link(context, user_id), "text": t(lang, "share_text")})
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "share_btn"), url=url)], *extra])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — выбор языка и новый разговор. /start ref_XXXX — пришёл по приглашению."""
    payload = context.args[0] if context.args else ""
    is_new = not context.user_data.get("joined") and "lang" not in context.user_data
    if payload.startswith("ref_") and is_new:
        ref = payload[4:20]
        if ref != stats.ref_code(update.effective_user.id):  # сам себя не приглашает
            stats.log_event(update.effective_user.id, "ref_join", ref)
    context.user_data["joined"] = True
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
        await update.message.reply_text(
            f"Команда /stats только для администраторов. Ваш ID: {update.effective_user.id}\n"
            "Чтобы стать администратором, впишите его в .env строкой ADMIN_IDS=... и перезапустите бота."
        )
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

    if data in ("fb:up", "fb:down"):  # 👍/👎 под старыми ответами — оценки больше не собираем
        await query.edit_message_reply_markup(reply_markup=None)
        return

    if data.startswith("lang:"):
        lang = data.split(":")[1]
        context.user_data["lang"] = lang
        await query.edit_message_text(t(lang, "lang_set"))
        await context.bot.send_message(chat_id, t(lang, "welcome"), reply_markup=menu_keyboard(lang))

    elif data.startswith("ent:"):  # «Мои предметы ЕНТ» → в каких вузах есть программы
        group = data.split(":")[1]
        stats.log_event(user_id, "button", f"ЕНТ: {group}")
        await query.edit_message_text(universities.ent_text(group, lang), reply_markup=ent_unis_keyboard(group, lang))

    elif data.startswith("gc:"):  # «Шанс на грант» → предметы выбраны, ждём балл
        group = data.split(":")[1]
        context.user_data["await_score"] = group
        stats.log_event(user_id, "button", f"шанс: {group}")
        await query.edit_message_text(f"📝 {universities.ENT_LABELS[group][lang]}\n\n" + t(lang, "chance_score"))

    elif data.startswith("u:"):  # «Вузы и цены» → вуз
        slug = data.split(":")[1]
        stats.log_event(user_id, "button", f"вуз {slug}")
        await query.edit_message_text(universities.uni_text(slug, lang), reply_markup=uni_groups_keyboard(slug, lang))

    elif data.startswith("ug:"):  # вуз + предметы ЕНТ → список программ
        _, slug, group = data.split(":")
        await query.edit_message_text(universities.group_text(slug, group, lang),
                                      reply_markup=uni_programs_keyboard(slug, group, lang))

    elif data.startswith(("up:", "p:")):  # карточка программы («p:» — кнопки из старых сообщений, AlmaU)
        key = data[3:] if data.startswith("up:") else "almau:" + data[2:]
        stats.log_event(user_id, "button", f"карточка {key}")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "btn_ask_ai"), callback_data=f"ua:{key}")]])
        await context.bot.send_message(chat_id, universities.program_card(key, lang), reply_markup=keyboard)

    elif data.startswith(("ua:", "a:")):  # следующий вопрос будет про эту программу
        key = data[3:] if data.startswith("ua:") else "almau:" + data[2:]
        context.user_data["ask_uni"] = key
        await context.bot.send_message(
            chat_id, t(lang, "ask_about").format(name=universities.prog_name(universities.program(key), lang)))

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
    ent_text = universities.ENT_LABELS[group][lang] if group else t(lang, "ent_unknown_text")
    user_text = t(lang, "q_request").format(
        ent=ent_text,
        interests=", ".join(catalog.INTERESTS[tag][lang] for tag in quiz["interests"]),
        value=catalog.VALUES[value][lang],
    )
    keys = universities.for_quiz(quiz["interests"], group=group)
    await reply_with_claude(context, chat_id, lang, user_text, keys)


# Названия кнопок меню для статистики.
BUTTON_STATS_NAMES = {
    "btn_pick": "Подобрать специальность", "btn_chance": "Шанс на грант", "btn_ent": "Мои предметы ЕНТ", "btn_prices": "Вузы и цены",
    "btn_docs": "Документы", "btn_dates": "Важные даты", "btn_contacts": "Приёмные комиссии",
    "btn_share": "Поделиться ботом",
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

    # Ждём балл для «Шанс на грант»: число — считаем, нажали кнопку меню — забываем.
    group = context.user_data.pop("await_score", None)
    if group and not button:
        score = re.fullmatch(r"\s*(\d{1,3})\s*(балл\w*)?\s*", text or "")
        if score and 0 <= int(score.group(1)) <= universities.MAX_ENT_SCORE:
            await send_chances(context, chat_id, lang, group, int(score.group(1)))
            return
        if re.search(r"\d", text or "") and len(text) < 15:
            context.user_data["await_score"] = group
            await update.message.reply_text(t(lang, "chance_bad"))
            return

    # Кнопки меню, которые работают без ИИ.
    if button == "btn_pick":
        await update.message.reply_text(t(lang, "q_ent"), reply_markup=ent_keyboard(lang, "q:ent:", True))
    elif button == "btn_chance":
        await update.message.reply_text(t(lang, "chance_ent"), reply_markup=ent_keyboard(lang, "gc:", False))
    elif button == "btn_ent":
        await update.message.reply_text(t(lang, "choose_ent"), reply_markup=ent_keyboard(lang, "ent:", False))
    elif button == "btn_prices":
        await update.message.reply_text(t(lang, "choose_uni"), reply_markup=unis_keyboard(lang))
    elif button == "btn_docs":
        await update.message.reply_text(static_text("documents", lang))
    elif button == "btn_dates":
        await update.message.reply_text(static_text("dates", lang))
    elif button == "btn_share":
        await update.message.reply_text(t(lang, "share_intro"),
                                        reply_markup=share_keyboard(context, lang, update.effective_user.id))
    elif button == "btn_contacts":
        await update.message.reply_text(universities.contacts_text(lang),
                                        disable_web_page_preview=True)
    else:
        # Свободный вопрос → ИИ с программами, о которых идёт речь.
        await answer_question(context, chat_id, lang, text)


async def send_chances(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str, group: str, score: int) -> None:
    """Текст с подробностями, затем картинка с результатом и кнопкой «Отправить другу»."""
    stats.log_event(chat_id, "chance", f"{group}:{score}")
    more = [[InlineKeyboardButton(t(lang, "chance_again"), callback_data=f"gc:{group}")],
            [InlineKeyboardButton(t(lang, "chance_programs"), callback_data=f"ent:{group}")]]
    await send_long(context, chat_id, universities.grant_chances(group, score, lang), lang)
    try:
        png = card.chance_card(group, score, lang, context.bot.username)
    except Exception:  # картинка — приятное дополнение; если не вышло, ответ уже отправлен текстом
        logger.exception("Не получилось нарисовать картинку «Шанс на грант»")
        png = None
    if not png:
        await context.bot.send_message(chat_id, t(lang, "card_more"), reply_markup=InlineKeyboardMarkup(more))
        return
    link = invite_link(context, chat_id)
    await context.bot.send_photo(chat_id, png, caption=t(lang, "card_caption").format(link=link),
                                 reply_markup=share_keyboard(context, lang, chat_id, more))
    stats.log_event(chat_id, "card", f"{group}:{score}")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Голосовые не распознаём — просим написать вопрос текстом."""
    await update.message.reply_text(t(get_lang(context), "voice_off"))


async def answer_question(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str, text: str) -> None:
    """Свободный вопрос → ИИ с данными нужных программ AlmaU и других вузов."""
    keys = universities.select(text, context.user_data.get("recent", []), context.user_data.pop("ask_uni", None))
    await reply_with_claude(context, chat_id, lang, text, keys)


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
                            user_text: str, keys: list[str]) -> None:
    if not config.ANTHROPIC_API_KEY:  # ИИ не подключён — не тратим лимит человека
        await send_long(context, chat_id, t(lang, "no_ai"), lang)
        return
    if not take_ai_quota(context):
        stats.log_event(chat_id, "limit")
        await send_long(context, chat_id, t(lang, "limit").format(
            limit=config.DAILY_AI_LIMIT, contacts=config.ADMISSIONS_CONTACTS), lang)
        return

    history = context.user_data.setdefault("history", [])
    logger.info("Чат %s [%s] программы %s: %s", chat_id, lang, keys, user_text[:100])

    # Показываем «печатает...», пока Claude думает.
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    details = universities.details(keys)
    messages = history + [{"role": "user", "content": with_details(user_text, details)}]

    try:
        answer, cost = await ask_claude(KNOWLEDGE_TEXT, lang, messages)
        stats.log_event(chat_id, "ai", ",".join(keys), cost)
        if answer:
            # В историю кладём вопрос без подробных данных — они добавляются заново к каждому вопросу.
            history += [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": answer},
            ]
            while len(history) > config.MAX_HISTORY_MESSAGES:
                del history[:2]
            context.user_data["recent"] = keys[:4]  # для уточнений вроде «а сколько она стоит?»
        else:
            answer = t(lang, "empty")
    except Refused:
        answer = t(lang, "refusal")
    except NoApiKey:
        logger.warning("ANTHROPIC_API_KEY не задан — вопросы к ИИ отключены")
        answer = t(lang, "no_ai")
    except anthropic.AnthropicError as e:
        stats.log_event(chat_id, "error", type(e).__name__)
        answer = api_error_text(e, lang)
    except Exception:
        logger.exception("Неожиданная ошибка")
        stats.log_event(chat_id, "error", "unexpected")
        answer = t(lang, "err_generic")

    await send_long(context, chat_id, answer, lang)


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
    К последнему куску можно прикрепить кнопки (например, «Ещё раз»)."""
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
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    logger.info("Администраторы (ADMIN_IDS): %s", ", ".join(map(str, config.ADMIN_IDS)) or "не заданы")
    if not config.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY не задан: кнопки работают, вопросы к ИИ отключены")
    logger.info("Pro4U запущен (модель: %s, лимит %s вопросов к ИИ в день). Остановить: Ctrl+C",
                config.CLAUDE_MODEL, config.DAILY_AI_LIMIT)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
