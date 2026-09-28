# Каталог программ AlmaU: группы ЕНТ, карточки программ, списки цен
# и подбор программ, которые нужно показать ИИ под конкретный вопрос.
# Всё здесь работает без ИИ и ничего не стоит.
import json
import re
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

# Группы профильных предметов ЕНТ (порядок = порядок кнопок).
ENT_GROUPS = {
    "geo_math": {"ru": "География + Математика", "kz": "География + Математика"},
    "math_inf": {"ru": "Математика + Информатика", "kz": "Математика + Информатика"},
    "geo_bio": {"ru": "География + Биология", "kz": "География + Биология"},
    "geo_eng": {"ru": "География + Английский", "kz": "География + Ағылшын тілі"},
    "wh_eng": {"ru": "Всемирная история + Иностранный язык", "kz": "Дүниежүзі тарихы + Шет тілі"},
    "wh_law": {"ru": "Всемирная история + Основы права", "kz": "Дүниежүзі тарихы + Құқық негіздері"},
    "creative": {"ru": "Творческий экзамен", "kz": "Шығармашылық емтихан"},
}

# Интересы для анкеты и слова, по которым их узнаём в вопросах.
INTERESTS = {
    "it": {"ru": "💻 IT и программирование", "kz": "💻 IT және бағдарламалау",
           "words": ["айти", "it", "програм", "разработ", "код", "сайт", "приложен", "игр", "компьютер",
                     "ии", "ai", "искусствен", "бағдарлама", "ойын"]},
    "data": {"ru": "📊 Цифры и анализ данных", "kz": "📊 Сандар және деректер",
             "words": ["данн", "аналит", "математ", "статист", "цифр", "дерек", "сандар"]},
    "business": {"ru": "💼 Бизнес и свой проект", "kz": "💼 Бизнес және өз жобам",
                 "words": ["бизнес", "менеджм", "предприним", "стартап", "маркетинг", "продаж",
                           "управлен", "кәсіп", "басқару"]},
    "finance": {"ru": "💰 Финансы и экономика", "kz": "💰 Қаржы және экономика",
                "words": ["финанс", "финтех", "fintech", "бухгал", "банк", "эконом", "инвест", "аудит", "деньг", "қаржы", "есеп"]},
    "creative_media": {"ru": "🎬 Творчество, медиа, кино", "kz": "🎬 Шығармашылық, медиа, кино",
                       "words": ["кино", "видео", "фильм", "монтаж", "медиа", "блог", "журналист", "творч",
                                 "дизайн", "pr", "пиар", "контент", "smm", "фото", "шығармашы"]},
    "people_psych": {"ru": "🧠 Люди и психология", "kz": "🧠 Адамдар және психология",
                     "words": ["психол", "общени", "адамдар"]},
    "law_politics": {"ru": "⚖️ Право, политика, мир", "kz": "⚖️ Құқық, саясат, әлем",
                     "words": ["юрист", "юрид", "право", "правов", "закон", "полит", "дипломат",
                               "международн", "заң", "құқық", "саясат"]},
    "tourism": {"ru": "✈️ Туризм, сервис, ивенты", "kz": "✈️ Туризм, сервис, ивенттер",
                "words": ["туризм", "отел", "гостиниц", "ресторан", "ивент", "мероприят", "путешеств",
                          "қонақ", "мейрамхана"]},
    "city": {"ru": "🏙 Города, транспорт, логистика", "kz": "🏙 Қала, көлік, логистика",
             "words": ["город", "урбан", "транспорт", "логист", "қала", "көлік"]},
    "sport": {"ru": "⚽ Спорт", "kz": "⚽ Спорт", "words": ["спорт"]},
}

# Что важно в будущей работе (последний шаг анкеты).
VALUES = {
    "money": {"ru": "💸 Высокий доход", "kz": "💸 Жоғары табыс"},
    "creativity": {"ru": "🎨 Творчество", "kz": "🎨 Шығармашылық"},
    "help": {"ru": "🤝 Помогать людям", "kz": "🤝 Адамдарға көмектесу"},
    "own_business": {"ru": "🚀 Свой бизнес", "kz": "🚀 Өз бизнесім"},
    "international": {"ru": "🌍 Международная карьера", "kz": "🌍 Халықаралық мансап"},
    "stability": {"ru": "🛡 Стабильность", "kz": "🛡 Тұрақтылық"},
}


def load_programs() -> dict[str, dict]:
    """Все программы бакалавриата: код -> данные."""
    programs = {}
    for path in sorted((KNOWLEDGE_DIR / "programs").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        programs[data["code"]] = data
    return programs


PROGRAMS = load_programs()


def is_open(program: dict) -> bool:
    """Есть ли набор в 2026 году (программа есть в прайсе приёмной)."""
    return "ent_group" in program


def name(program: dict, lang: str) -> str:
    return program["name_kz"] if lang == "kz" else program["name_ru"]


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₸"


def programs_in_group(group: str) -> list[dict]:
    return [p for p in PROGRAMS.values() if p.get("ent_group") == group]


# ---------------------------------------------------------------------------
# Тексты без ИИ
# ---------------------------------------------------------------------------
def group_text(group: str, lang: str) -> str:
    title = ENT_GROUPS[group][lang]
    per_year = "жылына" if lang == "kz" else "в год"
    lines = [f"📝 {title}\n"]
    for p in programs_in_group(group):
        lines.append(f"• {name(p, lang)} — {money(p['price_kzt'])} {per_year}")
    lines.append(
        "\nБағдарламаны басып, толығырақ біліңіз." if lang == "kz"
        else "\nНажмите на программу, чтобы узнать подробнее."
    )
    return "\n".join(lines)


def price_list_text(lang: str) -> str:
    kz = lang == "kz"
    lines = ["💰 AlmaU бакалавриатының оқу ақысы (2026, жылына):" if kz
             else "💰 Стоимость бакалавриата AlmaU (2026, за 1 год):"]
    for group in ENT_GROUPS:
        lines.append(f"\n{ENT_GROUPS[group][lang]}:")
        for p in programs_in_group(group):
            lines.append(f"• {name(p, lang)} — {money(p['price_kzt'])}")
    lines.append(
        "\nОқу 3 жыл. Барлық бағдарламалар орыс, қазақ және ағылшын тілдерінде. "
        "Магистратура — жылына шамамен 2 310 000 ₸. Жеңілдіктер мен гранттар туралы қабылдау комиссиясынан сұраңыз."
        if kz else
        "\nОбучение 3 года. Все программы — на русском, казахском и английском. "
        "Магистратура — около 2 310 000 ₸ в год. О скидках и грантах — в приёмной комиссии."
    )
    return "\n".join(lines)


def program_card(code: str, lang: str) -> str:
    p = PROGRAMS[code]
    kz = lang == "kz"
    lines = [f"🎓 {name(p, lang)} ({p['code']})", f"{p['school']}", f"{p['degree']} · {p['duration_years']} "
             + ("жыл" if kz else "года")]
    if is_open(p):
        per_year = "жылына" if kz else "в год"
        total = money(p["price_kzt"] * p["duration_years"])
        lines.append(("ҰБТ: " if kz else "ЕНТ: ") + ENT_GROUPS[p["ent_group"]][lang])
        lines.append(f"💰 {money(p['price_kzt'])} {per_year} (" + ("барлығы ~" if kz else "всего ~") + f"{total})")
    else:
        lines.append("⚠️ 2026 жылы бұл бағдарламаға қабылдау жоқ." if kz
                     else "⚠️ В 2026 году набора на эту программу нет.")
    if p.get("tracks"):
        lines.append(("\nТраекториялар:" if kz else "\nТраектории (специализации):"))
        lines += [f"• {t}" for t in p["tracks"]]
    lines.append(("\nНегізгі пәндер:" if kz else "\nКлючевые предметы:"))
    lines += [f"• {c}" for c in p["key_courses"][:8]]
    lines.append(("\nПрактика: " if kz else "\nПрактика: ") + p["practice"])
    if p.get("note"):
        lines.append(f"\nℹ️ {p['note']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Данные для ИИ
# ---------------------------------------------------------------------------
def compact_catalog() -> str:
    """Короткий список всех программ — всегда лежит в system prompt (кэшируется)."""
    lines = []
    for p in PROGRAMS.values():
        if is_open(p):
            status = f"ЕНТ: {' + '.join(p['ent_subjects'])}; {p['price_kzt']} тг/год"
        else:
            status = "НАБОРА В 2026 НЕТ"
        lines.append(f"{p['code']} | {p['name_ru']} | {p['name_kz']} | {p['duration_years']} г. | {status} | "
                     f"траектории: {'; '.join(p.get('tracks', [])) or '—'}")
    return "\n".join(lines)


def program_details(codes: list[str]) -> str:
    """Полные данные выбранных программ — добавляются к вопросу пользователя."""
    fields = ["code", "name_ru", "name_kz", "school", "degree", "duration_years", "tracks", "key_courses",
              "practice", "note", "ent_subjects", "ent_note", "price_kzt", "price_note", "availability_note",
              "languages"]
    data = [{k: PROGRAMS[c][k] for k in fields if k in PROGRAMS[c]} for c in codes]
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _stem(word: str) -> str:
    word = word.lower()
    return word[:-2] if len(word) > 6 else word


def _name_patterns(program: dict) -> list[list[str]]:
    patterns = []
    for field in ("name_ru", "name_kz", "name_en"):
        base = re.split(r"[(—]", program.get(field, ""))[0]
        words = [_stem(w) for w in re.findall(r"[\w-]+", base) if len(w) > 2]
        if words:
            patterns.append(words)
    return patterns


_NAME_PATTERNS = {code: _name_patterns(p) for code, p in PROGRAMS.items()}


def _contains(text: str, word: str) -> bool:
    if len(word) <= 3:  # короткие слова (ии, it, pr) — только целиком
        return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text) is not None
    return word in text


def find_programs(text: str) -> list[str]:
    """Программы, прямо названные в тексте."""
    low = text.lower()
    return [code for code, patterns in _NAME_PATTERNS.items()
            if any(all(_contains(low, w) for w in words) for words in patterns)]


def find_tags(text: str) -> list[str]:
    low = text.lower()
    return [tag for tag, info in INTERESTS.items() if any(_contains(low, w) for w in info["words"])]


def programs_for(tags: list[str], group: str | None = None, limit: int = 6) -> list[str]:
    """Программы с набором, подходящие под интересы (и группу ЕНТ, если известна)."""
    candidates = [p for p in PROGRAMS.values() if is_open(p) and (group is None or p["ent_group"] == group)]
    scored = sorted(candidates, key=lambda p: -len(set(p["tags"]) & set(tags)))
    return [p["code"] for p in scored if set(p["tags"]) & set(tags)][:limit] or \
        [p["code"] for p in candidates][:limit]


def relevant_programs(text: str, recent: list[str], limit: int = 6) -> list[str]:
    """Какие программы подробно показать ИИ для ответа на этот вопрос."""
    result: list[str] = []
    for code in find_programs(text) + recent:
        if code not in result:
            result.append(code)
    tags = find_tags(text)
    if tags and len(result) < limit:
        for code in programs_for(tags, limit=limit):
            if code not in result:
                result.append(code)
    return result[:limit]
