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

import asyncio
import html
import logging
import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import anthropic
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    Defaults,
    MessageHandler,
    PicklePersistence,
    filters,
)

import catalog
import config
import formatting
import photos
import profile_bot
import profiles
import stats
import universities
from claude_client import NoApiKey, Refused, ask_claude
from knowledge import build_knowledge_text
from prompts import with_details
from texts import BOT_PROFILE, LEGACY_BUTTONS, MENU_BUTTONS, TEXTS, t

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
    """Тексты «Документы» и «Даты»: первая строка — заголовок, жирным."""
    title, _, body = (STATIC_DIR / f"{name}_{lang}.md").read_text(encoding="utf-8").strip().partition("\n")
    return formatting.b(title) + "\n" + formatting.esc(body)


def get_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("lang", "ru")


# Версия меню и возможностей бота. Увеличь число, когда меняешь меню или добавляешь важное, —
# бот сам пришлёт всем пользователям новое меню (без нажатия «Старт»).
MENU_VERSION = 3


async def ensure_fresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Перед любым ответом: язык не потерян, меню — последней версии. Возвращает язык."""
    if "lang" not in context.user_data:  # данные потерялись (например, после переезда сервера) — не заставляем жать «Старт»
        p = profiles.get(update.effective_chat.id)
        code = (update.effective_user.language_code or "") if update.effective_user else ""
        context.user_data["lang"] = (p or {}).get("lang") or ("kz" if code.startswith("kk") else "ru")
        context.user_data["joined"] = True
        context.user_data["menu_v"] = MENU_VERSION  # новое меню — без сообщения «обновился»
        await context.bot.send_message(update.effective_chat.id, "👋", reply_markup=menu_keyboard(get_lang(context)))
    lang = get_lang(context)
    if context.user_data.get("menu_v") != MENU_VERSION:
        context.user_data["menu_v"] = MENU_VERSION
        await context.bot.send_message(update.effective_chat.id, t(lang, "menu_updated"), reply_markup=menu_keyboard(lang))
    return lang


async def announce_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    """После обновления бота: всем, у кого старое меню, — короткое сообщение с новым меню (один раз на версию)."""
    sent = 0
    for user_id, data in list(context.application.user_data.items()):
        if not data.get("lang") or data.get("menu_v") == MENU_VERSION:
            continue
        try:
            await context.bot.send_message(user_id, t(data["lang"], "menu_updated"), reply_markup=menu_keyboard(data["lang"]))
            sent += 1
        except RetryAfter as e:  # Telegram просит подождать — ждём и пробуем ещё раз
            await asyncio.sleep(e.retry_after + 1)
            try:
                await context.bot.send_message(user_id, t(data["lang"], "menu_updated"), reply_markup=menu_keyboard(data["lang"]))
                sent += 1
            except TelegramError:
                continue
        except Forbidden:  # пользователь заблокировал бота
            pass
        except TelegramError as e:
            logger.warning("Не удалось отправить новое меню %s: %s", user_id, e)
            continue
        data["menu_v"] = MENU_VERSION
        context.application.mark_data_for_update_persistence(user_ids=[user_id])
        await asyncio.sleep(0.05)  # не больше ~20 сообщений в секунду
    logger.info("Новое меню (версия %s) разослано: %s пользователям", MENU_VERSION, sent)


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
    """Постоянное меню — только самое нужное. Остальные кнопки появляются по ходу разговора (под ответами)."""
    return ReplyKeyboardMarkup(
        [
            [t(lang, "btn_pick"), t(lang, "btn_chance")],
            [t(lang, "btn_profile")],
        ],
        resize_keyboard=True,
    )


def start_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Первый вопрос после приветствия: что сейчас нужно человеку."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, k), callback_data=f"st:{k[6:]}")]
                                 for k in ("start_unsure", "start_uni", "start_chance", "start_other")])


# Кнопки, которые ИИ может предложить под ответом: метка [[имя]] в тексте → кнопка «act:имя».
ACTIONS = ("chance", "pick", "ent", "prices", "profile", "mocks", "contacts", "docs", "dates", "share")
ACTION_TAG = re.compile(r"\[\[\s*(\w+)(?::([^\]]+))?\s*\]\]")


def extract_buttons(context: ContextTypes.DEFAULT_TYPE, lang: str, text: str) -> tuple[str, InlineKeyboardMarkup | None]:
    """Вынимает из ответа ИИ метки кнопок: [[chance]] — действие бота, [[program:вуз:код]] — карточка программы,
    [[opt:Вариант ответа]] — быстрый ответ на наводящий вопрос. Возвращает текст без меток и клавиатуру."""
    rows, opts, seen = [], [], set()
    for m in ACTION_TAG.finditer(text):
        name, arg = m.group(1).lower(), html.unescape((m.group(2) or "").strip())
        if name in ACTIONS and name not in seen:
            seen.add(name)
            rows.append([InlineKeyboardButton(t(lang, f"act_{name}"), callback_data=f"act:{name}")])
        elif name == "program" and arg.count(":") == 1 and len([r for r in rows if r[0].callback_data.startswith("up:")]) < 4:
            try:
                p = universities.program(arg)
            except KeyError:
                continue
            rows.append([InlineKeyboardButton(("🎓 " + p["name_ru"])[:60] + f" · {universities.UNIS[arg.split(':')[0]]['short']}",
                                              callback_data=f"up:{arg}")])
        elif name == "opt" and arg and len(opts) < 4:
            opts.append(arg[:60])
    clean = re.sub(r"[ \t]*" + ACTION_TAG.pattern + r"[ \t]*", " ", text)
    clean = re.sub(r"[ \t]+\n", "\n", clean).strip()
    if opts:  # быстрые ответы — в начало, по два в ряд
        context.user_data["opts"] = opts
        btns = [InlineKeyboardButton(o, callback_data=f"opt:{i}") for i, o in enumerate(opts)]
        rows = [btns[i:i + 2] for i in range(0, len(btns), 2)] + rows
    return clean, (InlineKeyboardMarkup(rows) if rows else None)


async def run_action(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, lang: str, action: str) -> None:
    """Одно и то же действие — из меню, из стартового вопроса или из кнопки под ответом ИИ."""
    send = context.bot.send_message
    if action == "pick":
        await send(chat_id, t(lang, "q_ent"), reply_markup=ent_keyboard(lang, "q:ent:", True))
    elif action == "chance":
        await send(chat_id, t(lang, "chance_ent"), reply_markup=ent_keyboard(lang, "gc:", False))
    elif action == "ent":
        await send(chat_id, t(lang, "choose_ent"), reply_markup=ent_keyboard(lang, "ent:", False))
    elif action == "prices":
        await send(chat_id, t(lang, "choose_uni"), reply_markup=unis_keyboard(lang, 0, home_region(chat_id)))
    elif action == "docs":
        await send(chat_id, static_text("documents", lang))
    elif action == "dates":
        await send(chat_id, static_text("dates", lang))
    elif action == "mocks":
        await profile_bot.show_mocks(context, chat_id, lang)
    elif action == "profile":
        await profile_bot.show_page(context, chat_id, lang, with_card=True)
    elif action == "share":
        await send(chat_id, t(lang, "share_intro"), reply_markup=share_keyboard(context, lang, user_id))
    elif action == "contacts":  # вузы, о которых шла речь, иначе — вузы города человека
        recent = [k.split(":")[0] for k in context.user_data.get("recent", []) if ":" in k]
        slugs = [s for s in dict.fromkeys(recent) if s in universities.UNIS]
        home = home_region(chat_id)
        if not slugs and home:
            slugs = [s for s in universities.UNIS if universities.uni_region(s) == home]
        await send(chat_id, universities.contacts_text(lang, slugs), disable_web_page_preview=True)


def ent_keyboard(lang: str, prefix: str, with_unknown: bool) -> InlineKeyboardMarkup:
    labels = universities.ENT_LABELS
    rows = [[InlineKeyboardButton(labels[g][lang], callback_data=f"{prefix}{g}")] for g in universities.all_groups()]
    if with_unknown:
        rows.append([InlineKeyboardButton(t(lang, "ent_unknown"), callback_data=f"{prefix}unknown")])
    return InlineKeyboardMarkup(rows)


def page_row(prefix: str, page: int, total: int, lang: str) -> list[InlineKeyboardButton]:
    """«◀ Назад / Ещё ▶» для длинных списков вузов (по 10 на странице)."""
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("◀ " + ("Артқа" if lang == "kz" else "Назад"), callback_data=f"{prefix}{page - 1}"))
    if (page + 1) * universities.PAGE < total:
        row.append(InlineKeyboardButton(("Тағы" if lang == "kz" else "Ещё") + " ▶", callback_data=f"{prefix}{page + 1}"))
    return row


def ent_unis_keyboard(group: str, lang: str, page: int = 0, home: str | None = None) -> InlineKeyboardMarkup:
    """Предметы ЕНТ выбраны → в каких вузах есть программы (сначала вузы города человека)."""
    slugs = universities.unis_with(group, home)
    rows = [[InlineKeyboardButton(f"{universities.UNIS[s]['short']} · {universities.UNIS[s]['city']}"[:60],
                                  callback_data=f"ug:{s}:{group}")]
            for s in slugs[page * universities.PAGE:(page + 1) * universities.PAGE]]
    nav = page_row(f"eu:{group}:", page, len(slugs), lang)
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(t(lang, "btn_help_choose"), callback_data=f"qg:{group}")])
    return InlineKeyboardMarkup(rows)


def unis_keyboard(lang: str, page: int = 0, home: str | None = None) -> InlineKeyboardMarkup:
    slugs = universities.ordered(list(universities.UNIS), home)
    rows = [[InlineKeyboardButton(f"{universities.UNIS[s]['short']} · {universities.UNIS[s]['city']}"[:60],
                                  callback_data=f"u:{s}")]
            for s in slugs[page * universities.PAGE:(page + 1) * universities.PAGE]]
    nav = page_row("ul:", page, len(slugs), lang)
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(rows)


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
    if payload.startswith("src_") and is_new:  # ссылка партнёра: учитель, школа, центр подготовки
        stats.log_event(update.effective_user.id, "src_join", payload[4:40])
    if payload.startswith("ref_") and is_new:
        ref = payload[4:20]
        if ref != stats.ref_code(update.effective_user.id):  # сам себя не приглашает
            stats.log_event(update.effective_user.id, "ref_join", ref)
    context.user_data["joined"] = True
    stats.log_event(update.effective_user.id, "start", "new" if is_new else "")
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
    context.user_data["menu_v"] = MENU_VERSION
    await update.message.reply_text(t(lang, "reset_done"), reply_markup=menu_keyboard(lang))


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/myid — показать свой Telegram ID (нужен, чтобы стать администратором)."""
    await update.message.reply_text(f"Ваш Telegram ID: {update.effective_user.id}")


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/profile — личная страница."""
    await profile_bot.show_page(context, update.effective_chat.id, get_lang(context))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — что умеет бот."""
    lang = get_lang(context)
    await update.message.reply_text(t(lang, "about"), reply_markup=start_keyboard(lang))


async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/progress — статистика пробных тестов."""
    await profile_bot.show_mocks(context, update.effective_chat.id, get_lang(context))


async def set_commands(app: Application) -> None:
    """Список команд в меню Telegram (кнопка «/» рядом с полем ввода) — чтобы функции было видно."""
    from telegram import BotCommand
    me = await app.bot.get_me()
    logger.info("Бот в Telegram: @%s — ссылка https://t.me/%s", me.username, me.username)
    await app.bot.set_my_commands([
        BotCommand("start", "Начать / выбрать язык"),
        BotCommand("help", "Что умеет бот"),
        BotCommand("profile", "Моя страница: цель, сроки ЕНТ, напоминания"),
        BotCommand("progress", "Мои пробники: баллы и график роста"),
        BotCommand("lang", "Сменить язык"),
        BotCommand("reset", "Начать разговор заново"),
        BotCommand("delete_me", "Удалить мои данные"),
    ])
    # Описание бота (экран до «Старт») и короткое «О боте» (профиль и превью ссылки) — с главной ценностью.
    for code in (None, "ru", "kk"):
        texts = BOT_PROFILE["kk" if code == "kk" else "ru"]
        try:
            await app.bot.set_my_description(texts["description"], language_code=code)
            await app.bot.set_my_short_description(texts["short"], language_code=code)
        except Exception as e:  # не критично: бот работает и без описания
            logger.warning("Не удалось обновить описание бота (%s): %s", code, e)


async def delete_me_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/delete_me — удалить профиль и все баллы."""
    await profile_bot.delete_me(context, update.effective_chat.id, get_lang(context))


async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/credits — авторы фотографий вузов (этого требуют свободные лицензии; под самими фото подписей нет)."""
    for chunk in formatting.split(formatting.esc(photos.credits_text()), TELEGRAM_MESSAGE_LIMIT - 100):
        await update.message.reply_text(chunk, disable_web_page_preview=True)


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats — пользователи по месяцам и статистика за 30 дней (только для администраторов)."""
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.message.reply_text(
            f"Команда /stats только для администраторов. Ваш ID: {update.effective_user.id}\n"
            "Чтобы стать администратором, впишите его в .env строкой ADMIN_IDS=... и перезапустите бота."
        )
        return
    c = profiles.counts()
    await update.message.reply_text(
        stats.overview() + f"\n\n👤 Личные страницы: {c['profiles']} (внесли баллы: {c['with_scores']}, "
        f"всего результатов: {c['scores']}; напоминания включены у {c['reminders']})\n\n" + profiles.score_stats())
    await update.message.reply_text(stats.report(30))


async def partner_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/link имя — ссылка для партнёра (только для администраторов); в /stats видно, сколько людей по ней пришло."""
    if update.effective_user.id not in config.ADMIN_IDS:
        return
    name = re.sub(r"[^A-Za-z0-9_]", "", "_".join(context.args or []))[:36]
    if not name:
        await update.message.reply_text("Напиши имя латиницей: /link geo_teacher")
        return
    await update.message.reply_text(
        f"Ссылка для партнёра «{name}»:\nhttps://t.me/{context.bot.username}?start=src_{name}\n\n"
        "Сколько людей пришло по ней — смотри в /stats, раздел «Пришли по ссылкам партнёров».")


# ---------------------------------------------------------------------------
# Кнопки под сообщениями (inline)
# ---------------------------------------------------------------------------
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    lang = get_lang(context) if data.startswith("lang:") else await ensure_fresh(update, context)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if data in ("fb:up", "fb:down"):  # 👍/👎 под старыми ответами — оценки больше не собираем
        await query.edit_message_reply_markup(reply_markup=None)
        return

    if data.startswith("pf:"):  # личная страница
        await profile_bot.on_callback(update, context, lang, send_chances)
        return

    if data.startswith("lang:"):
        lang = data.split(":")[1]
        context.user_data["lang"] = lang
        if profiles.get(chat_id):
            profiles.update(chat_id, lang=lang)
        await query.edit_message_text(t(lang, "lang_set"))
        context.user_data["menu_v"] = MENU_VERSION
        await context.bot.send_message(chat_id, "👋", reply_markup=menu_keyboard(lang))
        await context.bot.send_message(chat_id, t(lang, "welcome"), reply_markup=start_keyboard(lang))

    elif data.startswith("st:"):  # стартовый вопрос «С чего начнём?»
        choice = data[3:]
        stats.log_event(user_id, "button", "Старт: " + choice)
        await query.edit_message_reply_markup(reply_markup=None)
        if choice == "unsure":
            await run_action(context, chat_id, user_id, lang, "pick")
        elif choice == "chance":
            await run_action(context, chat_id, user_id, lang, "chance")
        else:
            await context.bot.send_message(chat_id, t(lang, "start_uni_q" if choice == "uni" else "start_other_q"))

    elif data.startswith("act:"):  # кнопка, которую предложил ИИ под ответом
        action = data[4:]
        if action in ACTIONS:
            stats.log_event(user_id, "button", "ИИ-кнопка: " + action)
            await run_action(context, chat_id, user_id, lang, action)

    elif data.startswith("opt:"):  # быстрый ответ на наводящий вопрос ИИ
        opts = context.user_data.get("opts") or []
        i = int(data[4:]) if data[4:].isdigit() else -1
        if 0 <= i < len(opts):
            await query.edit_message_reply_markup(reply_markup=None)
            await context.bot.send_message(chat_id, f"✍️ {formatting.esc(opts[i])}")
            await answer_question(context, chat_id, lang, opts[i])

    elif data.startswith("ent:"):  # «Мои предметы ЕНТ» → в каких вузах есть программы
        group = data.split(":")[1]
        stats.log_event(user_id, "button", f"ЕНТ: {group}")
        home = home_region(chat_id)
        await query.edit_message_text(universities.ent_text(group, lang, 0, home),
                                      reply_markup=ent_unis_keyboard(group, lang, 0, home))

    elif data.startswith("eu:"):  # следующая страница вузов по предметам ЕНТ
        _, group, page = data.split(":")
        home = home_region(chat_id)
        await query.edit_message_text(universities.ent_text(group, lang, int(page), home),
                                      reply_markup=ent_unis_keyboard(group, lang, int(page), home))

    elif data.startswith("ul:"):  # следующая страница «Вузы и цены»
        await query.edit_message_reply_markup(reply_markup=unis_keyboard(lang, int(data[3:]), home_region(chat_id)))

    elif data.startswith("gc:"):  # «Шанс на грант» → предметы выбраны, ждём балл
        group = data.split(":")[1]
        context.user_data["await_score"] = group
        stats.log_event(user_id, "button", f"шанс: {group}")
        await query.edit_message_text(f"📝 {universities.ENT_LABELS[group][lang]}\n\n" + t(lang, "chance_score"))

    elif data.startswith("u:"):  # «Вузы и цены» → вуз
        slug = data.split(":")[1]
        stats.log_event(user_id, "button", f"вуз {slug}")
        # Список вузов оставляем (можно выбрать другой), ниже — фото вуза и его карточка.
        await photos.send_uni_photo(context.bot, chat_id, slug, lang)
        await context.bot.send_message(chat_id, universities.uni_text(slug, lang), reply_markup=uni_groups_keyboard(slug, lang))

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
            chat_id, t(lang, "ask_about").format(name=formatting.esc(universities.prog_name(universities.program(key), lang))))

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
    keys = universities.for_quiz(quiz["interests"], group=group, home=home_region(chat_id))
    await reply_with_claude(context, chat_id, lang, user_text, keys)


# Названия кнопок меню для статистики.
BUTTON_STATS_NAMES = {
    "btn_pick": "Подобрать специальность", "btn_chance": "Шанс на грант", "btn_ent": "Мои предметы ЕНТ", "btn_prices": "Вузы и цены",
    "btn_docs": "Документы", "btn_dates": "Важные даты", "btn_contacts": "Приёмные комиссии",
    "btn_share": "Поделиться ботом", "btn_profile": "Мой профиль", "btn_mocks": "Мои пробники",
}


# ---------------------------------------------------------------------------
# Сообщения
# ---------------------------------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обычное сообщение или нажатие кнопки меню."""
    lang = await ensure_fresh(update, context)
    text = update.message.text
    chat_id = update.effective_chat.id
    button = BUTTON_KEYS.get(text)
    if button:
        stats.log_event(update.effective_user.id, "button", BUTTON_STATS_NAMES[button])

    # Ждём ответ для личной страницы (имя, город, баллы…). Нажали кнопку меню — забываем вопрос.
    if button:
        context.user_data.pop("pf_await", None)
        context.user_data.pop("pf_wizard", None)
    elif await profile_bot.on_text(context, chat_id, lang, text):
        return

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

    # Кнопки меню (в том числе из старых клавиатур, которые остались у пользователей) — без ИИ.
    if button:
        await run_action(context, chat_id, update.effective_user.id, lang, button[4:])
    else:
        # Свободный вопрос → ИИ с программами, о которых идёт речь.
        await answer_question(context, chat_id, lang, text)


async def send_chances(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str, group: str, score: int) -> None:
    """Полный список: все группы и все вузы базы. Под ним — «Отправить другу», «Другой балл», «Программы»."""
    stats.log_event(chat_id, "chance", f"{group}:{score}")
    more = [[InlineKeyboardButton(t(lang, "chance_again"), callback_data=f"gc:{group}")],
            [InlineKeyboardButton(t(lang, "chance_programs"), callback_data=f"ent:{group}")],
            [InlineKeyboardButton(t(lang, "act_mocks"), callback_data="act:mocks")]]
    await send_long(context, chat_id, universities.grant_chances(group, score, lang, home_region(chat_id)), lang,
                    last_markup=share_keyboard(context, lang, chat_id, more))


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Голосовые не распознаём — просим написать вопрос текстом."""
    await update.message.reply_text(t(get_lang(context), "voice_off"))


def home_region(chat_id: int) -> str | None:
    """Город из личной страницы — его вузы предлагаем первыми."""
    p = profiles.get(chat_id)
    return universities.region_of(p.get("city")) if p else None


async def answer_question(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str, text: str) -> None:
    """Свободный вопрос → ИИ с данными нужных программ AlmaU и других вузов."""
    keys = universities.select(text, context.user_data.get("recent", []), context.user_data.pop("ask_uni", None),
                               home=home_region(chat_id))
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
            limit=config.DAILY_AI_LIMIT, contacts=formatting.esc(config.ADMISSIONS_CONTACTS)), lang,
            last_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "act_contacts"), callback_data="act:contacts")],
                                              [InlineKeyboardButton(t(lang, "act_prices"), callback_data="act:prices")]]))
        return

    history = context.user_data.setdefault("history", [])
    logger.info("Чат %s [%s] программы %s: %s", chat_id, lang, keys, user_text[:100])

    # Показываем «печатает...», пока Claude думает.
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    details = universities.details(keys, user_text)
    profile = profile_bot.ai_context(chat_id)
    messages = history + [{"role": "user", "content": with_details(user_text, details, profile)}]

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
            # Адрес бота ИИ не пишет: если всё же написал — убираем и показываем кнопку «Поделиться».
            bot_link = re.compile(r"(?:https?://)?t\.me/\w+bot\b\S*|@\w+bot\b", re.I)
            if bot_link.search(answer):
                answer = bot_link.sub("👇", answer)
                if "[[share]]" not in answer:
                    answer += "\n[[share]]"
            answer = formatting.from_ai(answer)  # ИИ выделяет важное <b>…</b>; остальное экранируем
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

    answer, buttons = extract_buttons(context, lang, answer)
    await send_long(context, chat_id, answer, lang, last_markup=buttons)


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
    chunks = formatting.split(text, TELEGRAM_MESSAGE_LIMIT)
    for n, chunk in enumerate(chunks):
        is_last = n == len(chunks) - 1
        markup = last_markup if (is_last and last_markup) else menu_keyboard(lang)
        try:
            await context.bot.send_message(chat_id, chunk, reply_markup=markup)
        except BadRequest as e:  # Telegram не принял разметку — отправляем тот же текст без неё
            logger.warning("Telegram не принял HTML (%s), отправляю без разметки", e)
            await context.bot.send_message(chat_id, formatting.strip_tags(chunk), reply_markup=markup, parse_mode=None)


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------
def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("Не найден TELEGRAM_BOT_TOKEN. Заполни его в файле .env.")
    Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)
    persistence = PicklePersistence(filepath=Path(config.DATA_DIR) / "bot_state.pickle")
    # Все сообщения — в HTML-режиме Telegram: так можно выделять важное жирным (<b>…</b>).
    app = (Application.builder().token(config.TELEGRAM_BOT_TOKEN).persistence(persistence)
           .defaults(Defaults(parse_mode=ParseMode.HTML)).post_init(set_commands).build())

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lang", change_language))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("myid", my_id))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("link", partner_link))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("delete_me", delete_me_command))
    app.add_handler(CommandHandler("progress", progress_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("credits", credits_command))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    logger.info("Администраторы (ADMIN_IDS): %s", ", ".join(map(str, config.ADMIN_IDS)) or "не заданы")
    if universities.UNTRANSLATED:
        logger.warning("Названия программ без перевода (добавь в knowledge/catalog/name_translations.py): %s",
                       "; ".join(universities.UNTRANSLATED))
    if not config.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY не задан: кнопки работают, вопросы к ИИ отключены")
    logger.info("Pro4U запущен (модель: %s, лимит %s вопросов к ИИ в день). Остановить: Ctrl+C",
                config.CLAUDE_MODEL, config.DAILY_AI_LIMIT)
    # Напоминания о сроках ЕНТ и просьбы внести баллы — каждый день в 10:00 по Алматы.
    app.job_queue.run_daily(profile_bot.daily_reminders, time=time(10, 0, tzinfo=timezone(timedelta(hours=5))))
    # Через минуту после запуска — новое меню всем, у кого оно устарело.
    app.job_queue.run_once(announce_update, 60)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
