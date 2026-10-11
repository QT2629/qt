# Другие вузы (кроме AlmaU): загрузка данных, краткий каталог для ИИ, подбор программ под вопрос,
# тексты для кнопок «Другие вузы». Данные — в knowledge/universities/<вуз>/ (university.json + programs.json).
# AlmaU по-прежнему описан в catalog.py: по нему данных больше (траектории, практика, баллы на грант).
import json
import re
from pathlib import Path

import catalog
from catalog import _contains, _stem, find_groups, money

UNI_DIR = Path(__file__).parent / "knowledge" / "universities"

# Пары предметов ЕНТ, которые встречаются у других вузов (рус / қаз).
ENT_LABELS = {
    "geo_math": {"ru": "Математика + География", "kz": "Математика + География"},
    "math_inf": {"ru": "Математика + Информатика", "kz": "Математика + Информатика"},
    "math_phys": {"ru": "Математика + Физика", "kz": "Математика + Физика"},
    "geo_bio": {"ru": "Биология + География", "kz": "Биология + География"},
    "bio_chem": {"ru": "Биология + Химия", "kz": "Биология + Химия"},
    "chem_phys": {"ru": "Химия + Физика", "kz": "Химия + Физика"},
    "geo_eng": {"ru": "География + Иностранный язык", "kz": "География + Шет тілі"},
    "wh_eng": {"ru": "Иностранный язык + Всемирная история", "kz": "Шет тілі + Дүниежүзі тарихы"},
    "wh_geo": {"ru": "Всемирная история + География", "kz": "Дүниежүзі тарихы + География"},
    "wh_law": {"ru": "Всемирная история + Основы права", "kz": "Дүниежүзі тарихы + Құқық негіздері"},
    "kaz": {"ru": "Казахский язык + Казахская литература", "kz": "Қазақ тілі + Қазақ әдебиеті"},
    "rus": {"ru": "Русский язык + Русская литература", "kz": "Орыс тілі + Орыс әдебиеті"},
    "creative": {"ru": "Творческий экзамен", "kz": "Шығармашылық емтихан"},
}
_SUBJECTS = {"матем": "math", "информ": "inf", "физик": "phys", "биолог": "bio", "хими": "chem", "геогр": "geo",
             "иностр": "eng", "всемир": "wh", "прав": "law", "казах": "kaz", "русск": "rus"}
_PAIRS = {frozenset(k.split("_")): k for k in ENT_LABELS if "_" in k}
_PAIRS.update({frozenset({"kaz"}): "kaz", frozenset({"rus"}): "rus"})


def ent_group(subjects: str) -> str | None:
    low = subjects.lower()
    if "творческ" in low:
        return "creative"
    found = frozenset(v for k, v in _SUBJECTS.items() if k in low)
    return _PAIRS.get(found)


def _load() -> dict[str, dict]:
    unis = {}
    for path in sorted(UNI_DIR.glob("*/university.json")):
        info = json.loads(path.read_text(encoding="utf-8"))
        programs = json.loads((path.parent / "programs.json").read_text(encoding="utf-8"))
        for p in programs:
            p["ent_group"] = ent_group(p["ent_subjects"])
            p["key"] = f"{info['slug']}:{p['code']}"
        info["programs"] = {p["code"]: p for p in programs}
        unis[info["slug"]] = info
    return unis


UNIS = _load()
ALMAU_WORDS = ["almau", "алмау", "алмаю", "almaty management", "алматы менеджмент"]


def program(key: str) -> dict:
    slug, code = key.split(":")
    return UNIS[slug]["programs"][code]


def uni_name(slug: str, lang: str) -> str:
    return UNIS[slug]["name_kz" if lang == "kz" else "name_ru"]


def price_text(p: dict, lang: str) -> str:
    if p["price_kzt"]:
        return money(p["price_kzt"]) + (" жылына" if lang == "kz" else " в год")
    return "бағасы нақтыланады" if lang == "kz" else "цена уточняется"


# ---------------------------------------------------------------------------
# Данные для ИИ
# ---------------------------------------------------------------------------
def compact_catalog() -> str:
    """Короткий список программ других вузов — лежит в кэшируемом system prompt."""
    blocks = []
    for u in UNIS.values():
        lines = [f"{u['name_ru']} — {u['city']}, {u['type']}. {u['price_note']} {u['notes']}",
                 "(код | программа | предметы ЕНТ | цена в год)"]
        for p in u["programs"].values():
            price = f"{p['price_kzt']} тг" if p["price_kzt"] else "цена не объявлена"
            lines.append(f"{p['code']} | {p['name_ru']} | {p['ent_subjects']} | {price}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def details(keys: list[str]) -> list[dict]:
    """Подробные данные выбранных программ других вузов для блока <program_details>."""
    out = []
    for key in keys:
        p = program(key)
        u = UNIS[key.split(":")[0]]
        out.append({
            "university": u["name_ru"], "code": p["code"], "name_ru": p["name_ru"], "section": p["section"],
            "ent_subjects": p["ent_subjects"], "ent_note": p["ent_note"], "price_kzt": p["price_kzt"],
            "price_note": u["price_note"], "key_courses": p["key_courses"], "careers": p["careers"],
            "workplaces": p["workplaces"],
        })
    return out


def mentioned_unis(text: str) -> list[str]:
    low = text.lower()
    return [slug for slug, u in UNIS.items() if any(a in low for a in u["aliases"])]


def mentions_almau(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in ALMAU_WORDS)


_COMPARE = ["сравн", "другие вуз", "другом вуз", "других вуз", "в каком вуз", "где ещё", "где еще", "какой вуз",
            "салыстыр", "басқа"]
_STOP = {"бакалавр", "делового", "администрирования", "области", "программы", "программа", "двойной", "диплом",
         "университет", "университете", "лондона", "отраслям", "расскажи", "сколько", "стоит", "учиться", "хочу",
         "какие", "какой", "какая", "есть", "можно", "поступить", "мне", "для", "где", "что", "как", "или", "вузе",
         "вуза", "вузы", "лучше", "сравни", "про", "это", "специальность", "специальности", "предметы", "предмет"}
_SUBJECT_STEMS = list(_SUBJECTS) + ["ент", "ұбт", "экзамен", "творческ"]


_SYNONYMS = {"it": ["информ", "программ", "компьютер"], "айти": ["информ", "программ", "компьютер"],
             "ai": ["искусствен"], "ии": ["искусствен"], "юрис": ["юрисп", "прав"], "юрист": ["юрисп", "прав"],
             "дизайн": ["дизайн"], "програм": ["программ", "информ"]}


def _stems(text: str) -> list[str]:
    """Основы слов вопроса: без служебных слов, названий вузов и предметов ЕНТ."""
    aliases = [a for u in UNIS.values() for a in u["aliases"]] + ALMAU_WORDS
    out = []
    for w in re.findall(r"[\w-]+", text.lower()):
        if w in _STOP or any(a in w for a in aliases) or any(w.startswith(s) for s in _SUBJECT_STEMS):
            continue
        stem = w[: max(4, len(w) - 2)] if len(w) >= 4 else w if re.fullmatch(r"[a-z]{2,3}|ии", w) else ""
        if stem:  # короткие латинские: it, ai, hr, ux, pr
            out.append(stem)
            out += _SYNONYMS.get(stem, []) + _SYNONYMS.get(w, [])
    return list(dict.fromkeys(out))


def _score(p: dict, stems: list[str]) -> int:
    name = p["name_ru"].lower()
    rest = " ".join(p["key_courses"] + p["careers"]).lower()
    score = 0
    for st in stems:
        hit = (lambda t: _contains(t, st)) if len(st) <= 3 else (lambda t: st in t)
        score += 3 if hit(name) else 1 if hit(rest) else 0
    return score


def relevant(text: str, recent: list[str], limit: int = 6) -> list[str]:
    """Какие программы других вузов показать ИИ подробно.

    Только если вопрос про другие вузы: назван вуз или просят сравнить. Иначе — пусто
    (кроме коротких уточнений к недавно обсуждавшимся программам).
    """
    slugs = mentioned_unis(text)
    compare = any(w in text.lower() for w in _COMPARE)
    if not slugs and not compare:
        return [k for k in recent if k.split(":")[0] in UNIS][:2] if recent and len(text) < 60 else []
    pool = [p for s in (slugs or UNIS) for p in UNIS[s]["programs"].values()]
    groups = set(find_groups(text) + _extra_groups(text))
    if groups:
        pool = [p for p in pool if p["ent_group"] in groups] or pool
    stems = _stems(text)
    scored = sorted(((_score(p, stems), p["key"]) for p in pool), key=lambda x: -x[0])
    top = scored[0][0] if scored else 0
    result = [k for sc, k in scored if sc > 0 and sc * 2 >= top]  # отсекаем случайные совпадения
    if not result and groups and slugs:  # «у меня математика и физика, что есть в ЕНУ?»
        result = [p["key"] for p in pool]
    if not result and slugs:
        result = [k for k in recent if k.split(":")[0] in slugs]
    return result[:limit]


def select(text: str, recent: list[str], recent_uni: list[str], asked: str | None = None) -> tuple[list[str], list[str]]:
    """Какие программы AlmaU (коды) и других вузов (ключи «вуз:код») подробно показать ИИ для вопроса.
    asked — программа другого вуза, под карточкой которой нажали «Задать вопрос ИИ»."""
    other_uni = bool(mentioned_unis(text))
    almau = mentions_almau(text)
    uni_keys = relevant(text, recent_uni)
    if not other_uni and catalog.find_programs(text):
        uni_keys = []  # назвали программу, а вуз нет — значит, про AlmaU, а не про прошлый вуз
    if asked and asked not in uni_keys:
        uni_keys = [asked] + uni_keys[:5]
    codes = catalog.relevant_programs(text, recent)
    if (other_uni or asked) and not almau:
        codes = []  # вопрос про другой вуз — программы AlmaU не подмешиваем
    return codes, uni_keys


def _extra_groups(text: str) -> list[str]:
    """Пары предметов, которых нет у AlmaU (find_groups их не знает)."""
    low = text.lower()
    found = frozenset(v for k, v in _SUBJECTS.items() if k in low)
    return [g for pair, g in _PAIRS.items()
            if len(pair) == 2 and pair <= found and g in ("math_phys", "bio_chem", "chem_phys", "wh_geo")]


# ---------------------------------------------------------------------------
# Тексты для кнопок (без ИИ)
# ---------------------------------------------------------------------------
def uni_text(slug: str, lang: str) -> str:
    u = UNIS[slug]
    kz = lang == "kz"
    return (f"🏛 {uni_name(slug, lang)}\n{u['city']} · {u['type']}\n\n{u['notes']}\n\n💰 {u['price_note']}\n\n"
            + ("ҰБТ пәндеріңді таңда — бағдарламаларды көрсетемін:" if kz
               else "Выбери свои предметы ЕНТ — покажу программы:"))


def groups_in(slug: str) -> list[str]:
    present = {p["ent_group"] for p in UNIS[slug]["programs"].values()}
    return [g for g in ENT_LABELS if g in present]


def programs_in(slug: str, group: str) -> list[dict]:
    return [p for p in UNIS[slug]["programs"].values() if p["ent_group"] == group]


def group_text(slug: str, group: str, lang: str) -> str:
    lines = [f"🏛 {UNIS[slug]['short']} · {ENT_LABELS[group][lang]}\n"]
    lines += [f"• {p['name_ru']} — {price_text(p, lang)}" for p in programs_in(slug, group)]
    lines.append("\nБағдарламаны басып, толығырақ біліңіз." if lang == "kz"
                 else "\nНажми на программу, чтобы узнать подробнее.")
    return "\n".join(lines)


def program_card(key: str, lang: str) -> str:
    p = program(key)
    slug = key.split(":")[0]
    kz = lang == "kz"
    lines = [f"🎓 {p['name_ru']} ({p['code']})", f"🏛 {uni_name(slug, lang)}", p["section"],
             ("ҰБТ: " if kz else "ЕНТ: ") + p["ent_subjects"], "💰 " + price_text(p, lang)]
    if p["ent_note"]:
        lines.append("⚠️ " + p["ent_note"])
    lines.append(("\nНегізгі пәндер:" if kz else "\nКлючевые предметы:"))
    lines += [f"• {c}" for c in p["key_courses"]]
    lines.append(("\nКім болып жұмыс істейді: " if kz else "\nКем работают: ") + ", ".join(p["careers"]))
    lines.append(("Қайда: " if kz else "Где: ") + ", ".join(p["workplaces"]))
    lines.append("\nℹ️ " + ("Деректер бағдар үшін — вуздың қабылдау комиссиясынан нақтылаңыз." if kz
                           else "Данные ориентировочные — уточняй в приёмной комиссии вуза."))
    return "\n".join(lines)
