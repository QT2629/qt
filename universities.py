# Все вузы бота на равных: AITU, AlmaU, ЕНУ, КазАТУ, КБТУ, MNU, Нархоз, Satbayev, SDU (и любые новые из knowledge/universities/).
# Здесь — загрузка данных, краткий каталог для ИИ, подбор программ под вопрос и анкету,
# тексты для кнопок. Всё работает без ИИ и ничего не стоит.
#
# Данные: knowledge/universities/<вуз>/university.json + programs.json.
# AlmaU хранится в своём старом формате (knowledge/programs/*.json, см. catalog.py) — здесь он
# приводится к общему виду, поэтому для бота это такой же вуз, как остальные.
import gzip
import json
import random
import re
import runpy
from pathlib import Path

import catalog
from formatting import b, esc
from catalog import INTERESTS, _contains, find_groups, money

UNI_DIR = Path(__file__).parent / "knowledge" / "universities"
# Каталог бакалавриата всех вузов страны (univision.kz + studyinkz.kz + реестр epvo.kz, гранты 2026).
# Собирается программой tools/build_catalog.py.
CATALOG_PATH = Path(__file__).parent / "knowledge" / "catalog" / "kz_bachelor.json.gz"
NAME_TR = runpy.run_path(str(CATALOG_PATH.parent / "name_translations.py"))["NAMES"]

# Записи каталога, которые не являются программами (факультеты, коды групп, пустые названия).
_NOT_PROGRAM = re.compile(r"^(-|–|b\d{3}|faculty\b.*|institute\b.*|humanities and social sciences|social sciences( and humanities)?|"
                          r"medicine and health sciences|engineering and technology)$", re.I)
# Казахская «І» вместо латинской I в аббревиатурах: «ІТ», «(ІР)», «ВІМ».
_FIX_ABBR = {"ІТ": "IT", "ІР": "IP", "ВІМ": "BIM", "ІоТ": "IoT"}
_YEARS_EN = re.compile(r"^(\d+)(?:\s*-\s*(\d+))?\s*years?$", re.I)
_LANGS = {"english": "английский", "russian": "русский", "kazakh": "казахский", "german": "немецкий",
          "chinese": "китайский", "turkish": "турецкий", "french": "французский"}
_LANGS_KZ = {"русский": "орыс", "казахский": "қазақ", "английский": "ағылшын", "немецкий": "неміс",
             "китайский": "қытай", "турецкий": "түрік", "французский": "француз"}


def _years_ru(a: int, b: int | None = None) -> str:
    n = b or a
    word = "год" if n % 10 == 1 and n % 100 != 11 else "года" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "лет"
    return f"{a}–{b} лет" if b else f"{a} {word}"


def clean_program(p: dict) -> bool:
    """Приводит программу к единому виду: название как у вуза (перевод — в name_translation для поиска), срок и языки по-русски.
    False — если это не программа (факультет, код группы)."""
    name = re.sub(r"^[–-]\s*", "", p["name_ru"]).strip(" «»\"")
    if not name or _NOT_PROGRAM.match(name):
        return False
    for bad, good in _FIX_ABBR.items():
        name = re.sub(rf"(?<![\w]){bad}(?![\w])", good, name)
    tr = NAME_TR.get(re.sub(r"\s+", " ", name.lower()).strip(" .«»\"'"))
    if tr:  # название остаётся как у вуза (на английском или казахском), перевод — для поиска и для ИИ
        p["name_translation"] = f"{tr[0]} / {tr[1]}"
    p["name_ru"] = name
    d = (p.get("duration") or "").strip()
    m = _YEARS_EN.match(d)
    if m:
        d = _years_ru(int(m.group(1)), int(m.group(2)) if m.group(2) else None)
    elif "then 3 years" in d:
        d = "1 год подготовительного курса + 3 года бакалавриата"
    elif not re.match(r"^\d", d):
        d = ""
    p["duration"] = d
    langs = [x.strip().lower() for x in (p.get("languages") or "").split(",") if x.strip() and x.strip().lower() != "язык"]
    p["languages"] = ", ".join(dict.fromkeys(_LANGS.get(x, x) for x in langs))
    return True


FORMAT_KZ = {"очно": "күндізгі", "смешанный (очно + онлайн)": "аралас (күндізгі + онлайн)", "очно или смешанный": "күндізгі немесе аралас"}


def duration_text(p: dict, lang: str) -> str:
    d = p.get("duration", "")
    if lang != "kz" or not d:
        return d
    if "подготовительного" in d:
        return "1 жыл дайындық курсы + 3 жыл бакалавриат"
    return re.sub(r"\s*(год|года|лет)\b", " жыл", d)


def languages_text(p: dict, lang: str) -> str:
    if not p.get("languages"):
        return ""
    if lang == "kz":
        return "оқу тілі: " + ", ".join(_LANGS_KZ.get(x, x) for x in p["languages"].split(", "))
    return "язык обучения: " + p["languages"]

# Пары профильных предметов ЕНТ (порядок = порядок кнопок).
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
    "lang_lit": {"ru": "Казахский/русский язык + литература", "kz": "Қазақ/орыс тілі + әдебиет"},
    "creative": {"ru": "Творческий экзамен", "kz": "Шығармашылық емтихан"},
}
_SUBJECTS = {"матем": "math", "информ": "inf", "физик": "phys", "биолог": "bio", "хими": "chem", "геогр": "geo",
             "иностр": "eng", "английск": "eng", "ағылшын": "eng", "шет тіл": "eng", "всемир": "wh",
             "дүниежүзі": "wh", "истори": "wh", "тарих": "wh", "прав": "law", "құқық": "law", "казах": "kaz", "қазақ": "kaz", "русск": "rus",
             "орыс": "rus"}
_PAIRS = {frozenset(k.split("_")): k for k in ENT_LABELS if "_" in k and k != "lang_lit"}
_PAIRS.update({frozenset({"kaz"}): "kaz", frozenset({"rus"}): "rus", frozenset({"kaz", "rus"}): "lang_lit"})


def ent_group(subjects: str) -> str | None:
    low = subjects.lower()
    if "творческ" in low:
        return "creative"
    return _PAIRS.get(frozenset(v for k, v in _SUBJECTS.items() if k in low))


# ---------------------------------------------------------------------------
# Загрузка
# ---------------------------------------------------------------------------
ALMAU_WORDS = ["almau", "алмау", "алмаю", "almaty management", "алматы менеджмент"]


def _almau() -> dict:
    """AlmaU в общем формате (из knowledge/programs/, см. catalog.py)."""
    info = {
        "slug": "almau", "short": "AlmaU", "name_ru": "Almaty Management University (AlmaU)",
        "name_kz": "Almaty Management University (AlmaU)", "aliases": ALMAU_WORDS, "city": "Алматы",
        "type": "частный университет", "website": "https://almau.edu.kz", "grant_list_code": "083",
        "admissions": {"phones": ["+7 (775) 006-16-06"], "email": "admission@almau.edu.kz",
                       "address": "Алматы, ул. Розыбакиева, 227", "hours": "пн–пт 9:00–18:00",
                       "url": "https://almau.edu.kz/ru/admission/", "checked_on": "2026-10-11"},
        "price_note": "Цены за 1 год по прайсу приёмной комиссии AlmaU, 2026.",
        "notes": "Программы по учебным планам 2026 года: траектории, практика, Minor. "
                 "По AlmaU в базе есть документы и даты приёма (раздел almau_admission).",
    }
    programs = {}
    for p in catalog.PROGRAMS.values():
        groups = catalog.ent_groups_of(p)
        grants = p.get("grant_2026")
        g = (grants[0] if isinstance(grants, list) else grants) or {}
        gen = g.get("almau_general") or {}
        programs[p["code"]] = {
            "code": p["code"], "name_ru": p["name_ru"], "name_kz": p.get("name_kz", ""), "section": p["school"],
            "ent_subjects": " или ".join(" + ".join(s) for s in [p["ent_subjects"]] + p.get("extra_ent_subjects", []))
            if catalog.is_open(p) else "", "ent_note": p.get("ent_note", ""),
            "tracks": p.get("tracks", []), "key_courses": p.get("key_courses", []), "careers": [], "workplaces": [],
            "price_kzt": p.get("price_kzt"), "open": catalog.is_open(p),
            "grant_2026": {"gop": g["gop"], "count": gen.get("count", 0), "min": gen.get("min"),
                           "kz_min": g.get("kz_general_min")} if g else None,
            "ent_groups": groups,
        }
    info["programs"] = programs
    return info


def _load() -> dict[str, dict]:
    unis = {"almau": _almau()}
    for path in sorted(UNI_DIR.glob("*/university.json")):
        info = json.loads(path.read_text(encoding="utf-8"))
        programs = json.loads((path.parent / "programs.json").read_text(encoding="utf-8"))
        for p in programs:
            # ent_groups_override — программа принимает любую пару предметов (например, AI + X в MNU)
            p["ent_groups"] = p.pop("ent_groups_override", None) or [g for g in [ent_group(p["ent_subjects"])] if g]
            p["open"] = True
        info["programs"] = {p["code"]: p for p in programs}
        unis[info["slug"]] = info
    for slug, u in unis.items():  # английские названия в справках вузов — тоже с переводом
        if slug != "almau":
            for p in u["programs"].values():
                clean_program(p)
    unis.update(_catalog_unis(unis))
    for slug, u in unis.items():
        for p in u["programs"].values():
            p["key"] = f"{slug}:{p['code']}"
    return dict(sorted(unis.items(), key=lambda kv: kv[1]["short"]))  # по алфавиту — никого не выделяем


_GENERIC = {"бакал", "делов", "админ", "облас", "бизне", "прогр", "образ", "подго", "специ", "техно", "основ"}


def _stems5(text: str) -> set[str]:
    """Основы значимых слов названия (первые 5 букв) — чтобы узнать ту же программу под другим названием."""
    stems = {w[:5] for w in re.findall(r"[а-яёa-z]+", text.lower()) if len(w) >= 5} - _GENERIC
    return {_SAME.get(x, x) for x in stems}


# Одно и то же разными словами: учёт = accounting = бухгалтерия, юриспруденция = право.
_SAME = {"accou": "аудит", "бухга": "аудит", "юрисп": "право", "lawye": "право"}


def _catalog_unis(unis: dict) -> dict[str, dict]:
    """Вузы из общего каталога. Для вузов с подробной справкой берём из каталога только
    предметы по курсам, цель программы и профессии — остальное остаётся из справки."""
    if not CATALOG_PATH.exists():
        return {}
    with gzip.open(CATALOG_PATH, "rt", encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for u in data["universities"]:
        progs = {p["code"]: p for p in u["programs"]}
        if u.get("existing") in unis:
            cur = unis[u["existing"]]
            for code, p in cur["programs"].items():
                c = progs.get(code)
                if not c:
                    continue
                if not p.get("track_courses") and c.get("study_path"):
                    p["study_path"] = c["study_path"]
                for field in ("about", "careers", "outcomes", "duration", "languages", "credits", "format", "direction"):
                    if not p.get(field) and c.get(field):
                        p[field] = c[field]
            for field in ("students", "region"):
                if u.get(field) and not cur.get(field):
                    cur[field] = u[field]
            # Программы, которых нет в справке вуза, — добавляем из каталога с пометкой (набор уточнять).
            known = set().union(*(_stems5(" ".join((x["name_ru"], x.get("name_translation", ""))))
                                  for x in cur["programs"].values()))
            for code, c in progs.items():
                if code in cur["programs"] or not clean_program(c):
                    continue
                stems = _stems5(c["name_ru"] + " " + c.get("name_translation", ""))
                if not stems or stems & known:  # похожая программа уже есть в справке — скорее всего, прежняя версия
                    continue
                c.update(ent_groups=[g for g in [ent_group(c.get("ent_subjects", ""))] if g], open=True,
                         not_in_reference=True)
                c.pop("url", None)
                for field in ("tracks", "key_courses", "careers", "workplaces"):
                    c.setdefault(field, [])
                c.setdefault("ent_subjects", "")
                c.setdefault("section", "")
                c.setdefault("price_kzt", None)
                cur["programs"][code] = c
            continue
        slug = f"u{u['id']}"
        names = [u["short"], u["name_ru"], u.get("name_en", "")]
        aliases = [a.lower() for a in names if a and len(a) >= 5]
        aliases += [a for a in u.get("aliases", []) if len(a) >= 4 or a.isascii() and len(a) >= 3]
        progs = {c: p for c, p in progs.items() if clean_program(p)}
        for p in progs.values():
            p["ent_groups"] = [g for g in [ent_group(p.get("ent_subjects", ""))] if g]
            if p["ent_groups"] and p["ent_groups"][0] not in ("kaz", "rus", "lang_lit"):  # «Математика и Физика» → «+»
                p["ent_subjects"] = p["ent_subjects"].replace(" и ", " + ")
            p["open"] = True
            p.pop("url", None)  # ссылки — только на сайты вузов, страницы каталога не показываем
            for field in ("tracks", "key_courses", "careers", "workplaces"):
                p.setdefault(field, [])
            p.setdefault("ent_subjects", "")
            p.setdefault("section", "")
            p.setdefault("price_kzt", None)
        out[slug] = {
            "slug": slug, "short": u["short"], "name_ru": u["name_ru"], "name_kz": u["name_ru"], "name_en": u.get("name_en", ""),
            "aliases": list(dict.fromkeys(aliases)), "city": u.get("city") or "город не указан", "type": u.get("type", ""),
            "students": u.get("students"), "region": u.get("region", ""), "rating": u.get("rating", ""),
            "website": u.get("website", ""),
            "admissions": {"phones": u.get("phones", []), "email": (u.get("emails") or [""])[0],
                           "address": u.get("contacts_raw", ""), "url": u.get("website", "")},
            "price_note": "Цены — по данным открытого каталога вузов, есть не у всех программ; "
                          "актуальную стоимость уточняй в приёмной комиссии.",
            "notes": "Данные открытого каталога вузов; коды программ сверены с официальным реестром образовательных программ.",
            "catalog": True, "programs": progs,
        }
    return out


UNIS = _load()
# Программы с названием без русских слов и без перевода — их не найдут по-русски; бот пишет их в лог при запуске.
UNTRANSLATED = [f"{slug}: {p['name_ru']}" for slug, u in UNIS.items() for p in u["programs"].values()
                if not p.get("name_translation") and not re.search(r"[а-яё]{3,}", p["name_ru"], re.I)]


def program(key: str) -> dict:
    slug, code = key.split(":")
    return UNIS[slug]["programs"][code]


def uni_name(slug: str, lang: str) -> str:
    return UNIS[slug]["name_kz" if lang == "kz" else "name_ru"]


def prog_name(p: dict, lang: str) -> str:
    return p.get("name_kz") or p["name_ru"] if lang == "kz" else p["name_ru"]


def price_text(p: dict, lang: str) -> str:
    if p["price_kzt"]:
        return money(p["price_kzt"]) + (" жылына" if lang == "kz" else " в год")
    if p.get("price_other"):
        return p["price_other"] + (" (каталог дерегі)" if lang == "kz" else " (по данным каталога)")
    return "бағасы нақтыланады" if lang == "kz" else "цена уточняется"


def grants_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "грант"
    return "гранта" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "грантов"


def grant_text(p: dict, lang: str) -> str:
    """Строка о госгрантах 2026 для карточки и списков."""
    g = p.get("grant_2026")
    if not g:
        return ""
    kz = lang == "kz"
    gop = g["gop"].split()[0]
    head = f"🏆 {'Мемлекеттік грант 2026' if kz else 'Госгрант 2026'} ({'топ' if kz else 'группа'} {gop}): "
    if g["count"]:
        return head + (f"ЖОО-ға {g['count']} грант, ең төменгі балл {g['min']} (ел бойынша {g['kz_min']} бастап)" if kz
                       else f"{g['count']} {grants_word(g['count'])} в этот вуз, мин. балл {g['min']} "
                            f"(по стране от {g['kz_min']})")
    return head + (f"ЖОО-ға грант берілмеді; ел бойынша ең төменгі балл {g['kz_min']}" if kz
                   else f"в этот вуз грантов не было; по стране мин. балл {g['kz_min']}")


# ---------------------------------------------------------------------------
# Данные для ИИ
# ---------------------------------------------------------------------------
def admissions_line(u: dict) -> str:
    a = u.get("admissions") or {}
    parts = [", ".join(a.get("phones", [])), a.get("email", ""), a.get("hours", ""), a.get("address", ""),
             a.get("url") or u.get("website", "")]
    return "; ".join(x for x in parts if x)


def links(slug: str, code: str | None = None) -> dict:
    """Официальные ссылки: сайт вуза, приёмная и страница программы (если её адрес есть в данных)."""
    u = UNIS[slug]
    out = {"site": u.get("website", ""), "admission": (u.get("admissions") or {}).get("url", ""),
           "bachelor_list": u.get("programs_url", "")}
    if code and u["programs"].get(code, {}).get("url"):
        out["program"] = u["programs"][code]["url"]
    return {k: v for k, v in out.items() if v}


def compact_catalog() -> str:
    """Список всех вузов (по одной строке) — лежит в кэшируемом system prompt.
    Программы и их подробности бот добавляет к каждому вопросу в <program_details>."""
    lines = ["(вуз | полное название | город | программ бакалавриата | официальный сайт | приёмная комиссия)"]
    for u in sorted(UNIS.values(), key=lambda u: (u["city"], u["short"])):
        n = sum(1 for p in u["programs"].values() if p["open"])
        lines.append(f"{u['short']} | {u['name_ru']} | {u['city']} | {n} | {u.get('website', '')} | {admissions_line(u)}")
    return "\n".join(lines)


def details(keys: list[str], text: str = "") -> str | None:
    """Подробные данные выбранных программ для блока <program_details> (JSON).
    Если в вопросе назван вуз (1–2) — ещё и полный список его программ, чтобы ИИ знал, что там есть."""
    out = []
    for slug in mentioned_unis(text)[:2] if text else []:
        u = UNIS[slug]
        out.append({"university": u["name_ru"], "city": u["city"], "website": u.get("website", ""),
                    "admissions": admissions_line(u), **{k: u[k] for k in ("type", "students", "rating") if u.get(k)},
                    "all_bachelor_programs": [f"{p['name_ru']} ({p['code']})" for p in u["programs"].values() if p["open"]]})
    for key in keys:
        slug, code = key.split(":")
        u = UNIS[slug]
        if slug == "almau" and code in catalog.PROGRAMS:  # у AlmaU полей больше: практика, оговорки, языки
            src = catalog.PROGRAMS[code]
            fields = ["code", "name_ru", "name_kz", "school", "degree", "duration_years", "tracks", "key_courses",
                      "practice", "note", "ent_subjects", "extra_ent_subjects", "ent_note", "price_kzt", "price_note",
                      "availability_note", "languages", "grant_2026"]
            out.append({"university": u["name_ru"], "city": u["city"], **{k: src[k] for k in fields if k in src},
                        "links": links(slug, code)})
            continue
        p = u["programs"][code]
        out.append({"university": u["name_ru"], "city": u["city"], "price_note": u["price_note"],
                    **({"data_source": u["notes"], "admissions": admissions_line(u)} if u.get("catalog") else {}),
                    **{k: u[k] for k in ("type", "students", "rating") if u.get(k)},
                    **{k: p[k] for k in ("code", "name_ru", "name_kz", "name_translation", "section", "ent_subjects", "ent_note", "price_kzt",
                                         "price_other", "duration", "credits", "languages", "format", "thesis", "direction",
                                         "tracks", "track_courses", "about", "outcomes", "study_path", "key_courses",
                                         "careers", "workplaces", "grant_2026", "inferred", "not_in_reference")
                       if p.get(k) not in (None, "", [], {})}, "links": links(slug, code)})
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")) if out else None


# ---------------------------------------------------------------------------
# Подбор программ под вопрос
# ---------------------------------------------------------------------------
# --- Распознавание вуза в тексте: падежи, сокращения, фамилии в названии, части названия ---
_TOKEN = re.compile(r"[a-zа-яёәғқңөұүһі0-9]+")
# Слова, которые есть в названиях многих вузов, — сами по себе вуз не определяют.
_GENERIC_STEMS = {"униве", "нацио", "госуд", "имени", "акаде", "инсти", "между", "казах", "высша", "школа", "филиа",
                  "респу", "иссле", "unive", "natio", "insti", "acade", "inter", "kazak", "techn", "and", "the", "of",
                  "колле", "корпо", "образ", "откры", "некомм", "акцио", "общес", "компа", "центр"}
# Слова-«профили» (технический, медицинский…): уточняют, но вуз не определяют.
_PROFILE_STEMS = {"техни", "педаг", "медиц", "аграр", "инжен", "гуман", "эконо", "техно", "иннов", "индус", "юриди",
                  "транс", "спорт", "искус", "финан", "языко", "отнош", "миров", "социа", "регио", "биз", "бизне",
                  "делов", "карье", "иност", "строи", "энерг", "связи", "путей", "сообщ", "дорож", "авиац", "граждa"}
_CITY_STEMS = {"алмат", "астан", "карег", "караг", "шымке", "актоб", "актюб", "атыра", "павло", "коста", "кызыл", "тараз",
               "турке", "ураль", "семей", "семип", "кокше", "талды", "петро", "актау", "темир", "экиба", "жезка",
               "рудне", "рудны", "аркал", "запад", "восто", "север", "южно", "центр", "евраз", "каспи"}


# Сокращения, которыми называют вузы (в том числе старые: КарГУ, ЮКГУ, ПГУ). Ключ — вуз в базе.
ABBR = {
    "almau": ["АлмаУ"], "enu": ["ЕНУ"], "kbtu": ["КБТУ"], "narxoz": ["КазЭУ"], "sdu": ["СДУ"], "mnu": ["МНУ", "КазГЮУ"],
    "aitu": ["АйТУ", "АИТУ"], "satbayev": ["КазНИТУ", "КазНТУ", "КазПТИ"], "kazatu": ["КазАТУ", "КАТУ", "КазАТИУ"],
    "u69": ["КазНУ", "КазГУ"], "u67": ["КазНПУ"], "u66": ["КазНМУ"], "u63": ["КазНАУ", "КазНАИУ"],
    "u71": ["КазУМОиМЯ", "КазУМО"], "u64": ["КазНацЖенПУ", "КазНЖПУ", "КазЖенПУ"], "u58": ["КазНАИ"], "u60": ["КазНК"],
    "u59": ["КазНАХ"], "u70": ["КазНУИ"], "u55": ["КазАДИ"], "u56": ["КазАСТ"], "u24": ["АЛТ"], "u30": ["АТУ"],
    "u31": ["АУЭС", "АИЭС"], "u23": ["АГА"], "u45": ["ЕТУ"], "u29": ["АГЭУ"], "u105": ["МУИТ"], "u128": ["КИМЭП"],
    "u99": ["МОК", "КазГАСА"], "u100": ["МИТУ"], "u102": ["МТГУ"], "u130": ["УМБ"], "u80": ["КНУ"], "u81": ["КРМУ"],
    "u76": ["ВШОЗ"], "u32": ["МИФИ"], "u97": ["МУА", "АМУ"], "u43": ["ЕГИ"], "u73": ["КазУТБ"], "u36": ["АтГУ"],
    "u37": ["АУНГ", "АИНГ"], "u35": ["АИГИ"], "u48": ["ЖезУ", "ЖезГУ"], "u84": ["КарТУ", "КарГТУ"], "u85": ["КарУ", "КарГУ"],
    "u83": ["КГМУ", "КарГМУ"], "u86": ["КЭУК"], "u137": ["ЦКА"], "u41": ["ГТА"], "u89": ["КУАМ"], "u91": ["КИнЭУ"],
    "u92": ["КРУ"], "u93": ["КСТУ"], "u94": ["КОУ"], "u54": ["ИнЕУ"], "u108": ["ППУ", "ПГПИ"], "u116": ["ПГУ"],
    "u112": ["СКУ", "СКГУ"], "u111": ["РИИ", "РИУ"], "u98": ["МУС", "ГМУС"], "u49": ["ЖУ", "ЖГУ"], "u115": ["ТарУ", "ТарГУ"],
    "u114": ["ТИГУ"], "u82": ["КГИУ"], "u101": ["МКТУ"], "u106": ["МУТиГ"], "u50": ["ЗКАТУ"], "u51": ["ЗКИТУ"],
    "u53": ["ЗКУ", "ЗКГУ"], "u77": ["КазУИТС"], "u39": ["ВКТУ", "ВКГТУ"], "u40": ["ВКУ", "ВКГУ"], "u78": ["КАСУ"],
    "u123": ["УДН"], "u135": ["ЦАИУ"], "u139": ["ЮКМА"], "u140": ["ЮКПУ", "ЮКГПУ"], "u141": ["ЮКУ", "ЮКГУ"],
    "u47": ["ЕИТИ"], "u28": ["АРУ", "АРГУ"], "u52": ["ЗКМУ", "ЗКГМУ"], "u88": ["КУТИ"], "u68": ["КазНУВХИ"],
    # Переименованные вузы: новое название по каталогу и сокращения по нему
    "u25": ["КНУС", "КазНУС", "КНАС", "КазНАС", "АФКиМС", "АФКМС"], "u56": ["КазАСТ", "КАСТ"],
    "u114": ["МТУ", "МТарУ"], "u129": ["ЕЮА"], "u100": ["МЕТУ", "METU"],
}
# Как ещё называют вуз (новые названия после переименования, имена в названии).
EXTRA_ALIASES = {
    "u25": ["национальный университет спорта", "национальная академия спорта", "university of sports"],
    "u24": ["тынышбаев", "alt university"], "u108": ["маргулан"], "u114": ["муртаз", "шерхан", "международный таразский"],
    "u119": ["ташенов"], "u129": ["евразийская юридическая академия"], "u140": ["жанибеков"], "u70": ["байсеитов"],
    "u88": ["yessenov"], "u85": ["карагандинский национальный исследовательский"],
}
for _slug, _extra in EXTRA_ALIASES.items():
    if _slug in UNIS:
        UNIS[_slug]["aliases"] = list(dict.fromkeys(UNIS[_slug]["aliases"] + _extra))
# Сокращения, похожие на обычные слова («карту», «тару», «ага»), засчитываем, только если написаны заглавными.
_ABBR_WORDS = {"карту", "кару", "тару", "ару", "ага", "касу", "кату", "мок", "мус", "алт", "ату", "ету", "жу", "кну", "умб",
               "ппу", "пгу", "кру", "цка", "гта", "коу", "рии", "риу", "ску", "вку", "зку", "удн", "муа", "аму", "ену", "сду",
               "мну", "еги", "кгу"}


_CITY_PREFIX = ("алмат", "астан", "караг", "тараз", "павло", "семей", "актюб", "атыра", "кокше", "коста", "кызыл", "шымке",
                "туркес", "ураль", "петро", "жезка", "экиба", "рудне", "аркал", "актау", "талды")
_SKIP_WORDS = {"и", "в", "на", "по", "г", "города", "при", "для", "филиал"}


def _generated_abbr(name: str) -> set[str]:
    """Сокращения, которые люди составляют из названия: первые буквы слов («Каз» для «Казахский»,
    «Кар» для «Карагандинский»), с «Г» (государственный — старые названия) и без."""
    name = re.split(r"(?:^|\s)(?:им\.|имени)(?:\s|$)", re.sub(r"[«\"].*?[»\"]|\(.*?\)", " ", name) + " ")[0]
    words = [w for w in re.findall(r"[А-ЯЁа-яё]+", name) if w.lower() not in _SKIP_WORDS]
    if len(words) < 2:
        return set()
    plain, kaz, city = [], [], []
    for i, w in enumerate(words):
        low = w.lower()
        letter = w[0].upper()
        plain.append(letter)
        kaz.append("Каз" if low.startswith("казах") and i == 0 else letter)
        city.append(w[:3].capitalize() if i == 0 and low.startswith(_CITY_PREFIX) else letter)
    out = set()
    for v in (plain, kaz, city):
        a = "".join(v)
        if len(a) >= 3:
            out.add(a)
            if a.endswith("У") and "Г" not in a:  # КарУ → КарГУ, ЮКУ → ЮКГУ, ВКТУ → ВКГТУ
                out.add(a[:-1] + "ГУ")
                if len(a) >= 4 and a[-2] in "ТПМАИ":
                    out.add(a[:-2] + "Г" + a[-2:])
    return out


_ABBR_CACHE: dict = {}


def _abbr_table() -> dict[str, list[tuple[str, bool, str]]]:
    """Сокращения всех вузов: (строчными, только заглавными, как пишется). Совпавшие у двух вузов автосокращения
    не берём — по ним вуз не понять."""
    if _ABBR_CACHE:
        return _ABBR_CACHE
    common = _common_stems()
    gen: dict[str, set[str]] = {}
    for slug, u in UNIS.items():
        names = [u["name_ru"]] + re.findall(r"\((.*?)\)", u["name_ru"])
        gen[slug] = set().union(*(_generated_abbr(n) for n in names))
    count = {}
    for slug, abbrs in gen.items():
        for a in abbrs:
            count[a.lower()] = count.get(a.lower(), 0) + 1
    manual = {a.lower() for v in ABBR.values() for a in v}
    for slug, u in UNIS.items():
        out = list(ABBR.get(slug, []))
        first = u["short"].split()[0]  # «КарТУ им. Сагинова» → КарТУ
        if sum(c.isupper() for c in first) >= 2 and len(first) <= 9 and first.lower() not in ("кму", "ку", "ау", "жу"):
            out.append(first)
        out += [a for a in gen[slug] if count[a.lower()] == 1 and a.lower() not in manual]
        res = {}
        for a in out:
            low = a.lower()
            if low in ("ент", "вуз", "гоп", "нцт", "орт", "кгу", "кму"):
                continue
            # Короткие и похожие на обычные слова — только заглавными (КарТУ ≠ «карту»).
            caps = (low in _ABBR_WORDS or low[:5] in common or len(low) <= 4) \
                and low not in _LOWER_OK \
                and not low.isascii() and low not in u["aliases"]  # латиница (SDU, AITU) и явные варианты — любым регистром
            if low not in res:
                res[low] = (caps, a)
            else:
                res[low] = (res[low][0] and caps, res[low][1])
        _ABBR_CACHE[slug] = [(low, caps, a) for low, (caps, a) in res.items()]
    return _ABBR_CACHE


# Короткие сокращения, которые пишут и строчными и которые не совпадают с обычными словами.
_LOWER_OK = {"ену", "сду", "мну", "кбту", "муит", "аиту", "айту", "кнус", "юку", "вкту", "зкму", "агэу", "ауэс", "мкту",
             "юкма", "юкпу", "ксту", "аунг", "еити", "кути", "мифи", "вшоз", "крму", "аинг", "аиги", "тигу", "кгиу",
             "кэук", "кгму", "скгу", "вкгу", "зкгу", "аргу", "атгу", "жгу", "ппу"}


def _abbr_list(slug: str, u: dict) -> list[tuple[str, bool, str]]:
    """(сокращение строчными, нужно ли писать заглавными, как пишется)."""
    return _abbr_table()[slug]


def _stem(word: str) -> str:
    return word[:5] if len(word) >= 5 else word


def _surname(words: list[str]) -> set[str]:
    """Фамилия после «им./имени»: «им. Л.Н. Гумилева» → гумиле, «имени аль-Фараби» → фараби."""
    out = set()
    for i, w in enumerate(words):
        if w in ("им", "имени"):
            # «имени Ахмет Байтұрсынұлы» → фамилия (последнее слово), но «Абылай хана», «Коркыт Ата» → первое
            cand = [x for x in words[i + 1:i + 6] if len(x) > 2 and x not in ("аль", "ибн", "академика", "академик",
                                                                                "профессора", "героя", "города")]
            cand = [x for x in cand if x not in ("хана", "хан", "ата", "би")] or cand
            if cand:
                nxt = cand[-1]
                out.add(nxt[:max(4, min(6, len(nxt) - 1))])
    return out


def _phrases(name: str) -> list[list[str]]:
    """Название как последовательность основ слов (без «имени …»): и основное, и то, что в скобках."""
    out = []
    for part in [re.sub(r"\(.*?\)", " ", name)] + re.findall(r"\((.*?)\)", name):
        words = _TOKEN.findall(part.lower().replace("ё", "е"))
        cut = next((i for i, w in enumerate(words) if w in ("им", "имени")), len(words))
        ph = [_stem(w) for w in words[:cut] if len(w) > 1]
        if len(ph) >= 2:
            out.append(ph)
    return out


def _name_profile(u: dict) -> dict:
    """Что из названия вуза помогает его узнать: фамилия, отличительные слова, вся фраза названия, сокращение."""
    words = _TOKEN.findall(re.sub(r"\(.*?\)", " ", u["name_ru"]).lower().replace("ё", "е"))
    surname = _surname(words)
    inf = {}
    for w in _TOKEN.findall(" ".join((u["name_ru"], u.get("name_en", ""))).lower().replace("ё", "е")):
        st = _stem(w)
        if len(w) < 4 or st in _GENERIC_STEMS or any(w.startswith(x) for x in surname):
            continue
        inf[st] = 1 if st in _PROFILE_STEMS else 2
    return {"surname": surname, "inf": inf, "phrases": _phrases(u["name_ru"]), "abbr": _abbr_list(u["slug"], u)}


def _alias_tokens(alias: str, tokens: list[str]) -> list[int]:
    """Позиции слов текста, которые совпали с вариантом названия (пусто — не совпало)."""
    a = _TOKEN.findall(alias.lower().replace("ё", "е"))
    if not a:
        return []
    if len(a) > 1:                                     # фраза: слова подряд, допускаем падежные окончания
        for i in range(len(tokens) - len(a) + 1):
            if all(tokens[i + j] == w or len(w) >= 4 and tokens[i + j].startswith(w[:max(4, len(w) - 2)])
                   for j, w in enumerate(a)):
                return list(range(i, i + len(a)))
        return []
    a = a[0]
    for i, t in enumerate(tokens):
        if len(a) <= 6:                                # сокращения и короткие названия: КазНУ, ЕНУ, КБТУ, Туран
            if t == a or (not a.isascii() and t.startswith(a) and len(t) - len(a) <= 2 and len(a) >= 4):
                return [i]
        elif t.startswith(a) or (a.startswith(t) and len(t) >= len(a) - 1):  # гумилев → гумилева, нарикбаева → нарикбаев
            return [i]
    return []


_COMMON: set[str] = set()


def _common_stems() -> set[str]:
    """Основы обычных слов из названий специальностей и групп (информационные, автоматизация, логистика…)."""
    if not _COMMON:
        for u in UNIS.values():
            for p in u["programs"].values():
                for w in _TOKEN.findall(" ".join((p["name_ru"], p.get("section", ""), p.get("name_translation", ""))).lower()):
                    _COMMON.add(_stem(w))
    return _COMMON


def match_unis(text: str) -> tuple[list[str], set[str]]:
    """Какие вузы названы в тексте и какие основы слов ушли на их названия (их не считаем темой вопроса)."""
    raw_tokens = _TOKEN.findall(text.replace("ё", "е").replace("Ё", "Е").lower())
    orig = re.findall(r"[A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі0-9]+", text)
    tokens = list(raw_tokens)
    found, used = [], set()
    # 1) Варианты названий (сокращения, фамилии, английские названия) — сначала длинные, чтобы
    #    «Туран-Астана» не превратилось в «Туран».
    variants = sorted(((a, slug) for slug, u in UNIS.items() for a in u["aliases"]), key=lambda x: -len(x[0]))
    abbrs = []
    for slug, u in UNIS.items():
        prof = u.setdefault("_profile", _name_profile(u))
        abbrs += [(ab, caps, slug) for ab, caps, _ in prof["abbr"]]
    # Бот — для поступления: сокращение вуза засчитываем в любом регистре и в любой фразе
    # («покажи карту» → КарТУ, «кнус» → университет спорта).
    for ab, caps, slug in sorted(abbrs, key=lambda x: -len(x[0])):  # сокращения — целым словом
        pos = [i for i, t in enumerate(tokens) if t == ab]
        if pos:
            if slug not in found:
                found.append(slug)
            for i in pos:
                used.add(_stem(tokens[i]))
                tokens[i] = "\x00"
    for alias, slug in variants:
        pos = _alias_tokens(alias, tokens)
        if pos:
            if slug not in found:
                found.append(slug)
            for i in pos:
                used.add(_stem(tokens[i]))
                tokens[i] = "\x00"  # это слово уже «занято» названием
    # Вуз узнан по сокращению или фамилии — остальные слова его названия («Кокшетауский университет»)
    # тоже его, они не должны «найти» соседний вуз с похожим названием.
    for slug in found:
        prof = UNIS[slug]["_profile"]
        own = set(prof["inf"]) | {x for ph in prof["phrases"] for x in ph}
        for i, t in enumerate(tokens):
            if t != "\x00" and _stem(t) in own:
                used.add(_stem(t))
                tokens[i] = "\x00"
    # 2) По словам полного названия: фамилия, вся фраза или отличительные слова (в любом падеже).
    stems = [_stem(t) for t in tokens]
    scores, hits = {}, {}
    for slug, u in UNIS.items():
        if slug in found:
            continue
        prof = u["_profile"]
        sur = {i for i, t in enumerate(tokens) for x in prof["surname"] if t.startswith(x) and len(t) - len(x) <= 3}
        hit = {st for st in prof["inf"] if st in stems}
        total = sum(prof["inf"].values()) or 1
        got = sum(prof["inf"][st] for st in hit)
        phrase = next((ph for ph in prof["phrases"]
                       if any(stems[i:i + len(ph)] == ph for i in range(len(stems) - len(ph) + 1))), None)
        # Имя собственное в названии («Туран», «Мирас», «Болашак») — слово, которого нет в названиях специальностей.
        proper = {st for st in hit if prof["inf"][st] == 2 and st not in _CITY_STEMS and st not in _common_stems()
                  and not st.isascii()}  # английские слова названия (irrigation…) вуз сами по себе не определяют
        score = 0
        if sur:
            score = 30 + got
        elif phrase:
            score = 20 + len(phrase)
        elif proper:
            score = 10 + got
        if score:
            scores[slug] = score
            hits[slug] = {stems[i] for i in sur} | hit | set(phrase or [])
    if scores:
        best = max(scores.values())
        for slug, v in scores.items():
            if v == best:
                found.append(slug)
                used |= hits[slug]
    return found, used


def mentioned_unis(text: str) -> list[str]:
    return match_unis(text)[0]


_STOP = {"бакалавр", "делового", "администрирования", "области", "программы", "программа", "двойной", "диплом",
         "университет", "университете", "лондона", "отраслям", "расскажи", "сколько", "стоит", "учиться", "хочу",
         "какие", "какой", "какая", "есть", "можно", "поступить", "мне", "для", "где", "что", "как", "или", "вузе",
         "вуза", "вузы", "вузах", "лучше", "сравни", "сравнить", "про", "это", "специальность", "специальности",
         "предметы", "предмет", "балл", "баллы", "грант", "грантов", "цена", "цены", "стоимость", "куда", "меня",
         "нужны", "нужно", "подходит", "подойдёт", "подойдет", "выбрать", "учеба", "учёба", "обучение",
         # «я поменяла предметы, теперь сдаю…», «хватит ли мне баллов» — это не тема программы
         "сдаю", "сдала", "сдал", "сдавать", "буду", "поменяла", "поменял", "теперь", "передумала", "передумал",
         "решила", "решил", "выбрала", "выбрал", "хватит", "хватает", "баллов", "баллами", "мне", "мой", "моя",
         "ещё", "еще", "варианты", "вариант", "другие", "другое", "тоже", "тогда", "лучше", "есть", "там", "тут"}
_SUBJECT_STEMS = list(_SUBJECTS) + ["ент", "ұбт", "экзамен", "творческ"]
_SYNONYMS = {"it": ["информ", "программ", "компьютер"], "айти": ["информ", "программ", "компьютер"],
             "ai": ["искусствен"], "ии": ["искусствен"], "юрис": ["юрисп", "прав"], "юрист": ["юрисп", "прав"],
             "програм": ["программ", "информ"]}


def _stems(text: str) -> list[str]:
    """Основы слов вопроса: без служебных слов, названий вузов и предметов ЕНТ.
    Названия предметов отбрасываем, только когда в вопросе есть пара ЕНТ: иначе «право» или «история» —
    это направление, которое человек ищет."""
    slugs, used = match_unis(text)
    aliases = [a.lower() for slug in slugs for a in UNIS[slug]["aliases"]]
    subjects = _SUBJECT_STEMS if _groups(text) else ["ент", "ұбт", "экзамен"]
    out = []
    for w in re.findall(r"[\w-]+", text.lower()):
        if (w in _STOP or _stem(w) in used or any(a in w for a in aliases) or any(w.startswith(s) for s in subjects)
                or region_of(w)):
            continue
        stem = w[: max(4, len(w) - 2)] if len(w) >= 4 else w if re.fullmatch(r"[a-z]{2,3}|ии", w) else ""
        if stem == "прав":  # «право/праву» — не путать с «упРАВление»
            out += ["право", "юрис", "юрид"]
            continue
        if stem:  # короткие латинские: it, ai, hr, ux, pr
            out.append(stem)
            out += _SYNONYMS.get(stem, []) + _SYNONYMS.get(w, [])
    return list(dict.fromkeys(out))


def _score(p: dict, stems: list[str]) -> int:
    name = " ".join((p["name_ru"], p.get("name_kz", ""), p.get("name_translation", ""))).lower()
    rest = " ".join(p["key_courses"] + p["careers"] + p.get("tracks", [])).lower()
    # Совпадение в названии — главное; в предметах и профессиях — максимум +1, чтобы вузы с подробными
    # справками (больше текста) не получали преимущества над остальными.
    name_hits = rest_hit = 0
    for st in stems:
        hit = (lambda t: _contains(t, st)) if len(st) <= 3 else (lambda t: st in t)
        if hit(name):
            name_hits += 1
        elif hit(rest):
            rest_hit = 1
    return 3 * name_hits + rest_hit


def _ranked(items: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """По убыванию оценки; равные — в случайном порядке (никакой вуз не первый «по алфавиту»)."""
    return sorted(items, key=lambda x: (-x[0], random.random()))


def _balanced(keys: list[str], limit: int, per_uni: int = 2) -> list[str]:
    """Не больше per_uni программ одного вуза, пока есть другие — чтобы ни один вуз не перетягивал."""
    first, rest, seen = [], [], {}
    for k in keys:
        slug = k.split(":")[0]
        seen[slug] = seen.get(slug, 0) + 1
        (first if seen[slug] <= per_uni else rest).append(k)
    return (first + rest)[:limit]


def _groups(text: str) -> set[str]:
    low = text.lower()
    found = frozenset(v for k, v in _SUBJECTS.items() if k in low)
    groups = {g for pair, g in _PAIRS.items() if len(pair) == 2 and pair <= found}
    if "творческ" in low or "шығармашылық" in low:
        groups.add("creative")
    return groups | set(find_groups(text))


# Города: как их пишут люди → регион. Каскелен (SDU) — пригород Алматы, поэтому считается Алматы.
REGIONS = {
    "almaty": ("алмат", "almaty", "алма-ат", "каскелен", "қаскелең", "kaskelen"),
    "astana": ("астан", "astana", "нур-султан", "нурсултан", "акмол", "ақмол"),
}
REGION_NAMES = {"almaty": "Алматы", "astana": "Астана"}
# Другие города — как их пишут по-русски, по-казахски и латиницей.
CITY_WORDS = {
    "Шымкент": ("шымкент", "shymkent"), "Караганда": ("караганд", "қарағанды", "karaganda"),
    "Актобе": ("актобе", "ақтөбе", "aktobe"), "Атырау": ("атырау", "atyrau"), "Павлодар": ("павлодар", "pavlodar"),
    "Костанай": ("костанай", "қостанай", "kostanay", "kostanai"), "Кызылорда": ("кызылорд", "қызылорда", "kyzylorda"),
    "Тараз": ("тараз", "taraz"), "Туркестан": ("туркестан", "түркістан", "turkestan"), "Уральск": ("уральск", "uralsk"),
    "Усть-Каменогорск": ("усть-каменогорск", "өскемен", "оскемен", "oskemen", "ust-kamenogorsk"),
    "Семей": ("семей", "семипалатинск", "semey"), "Кокшетау": ("кокшетау", "көкшетау", "kokshetau"),
    "Талдыкорган": ("талдыкорган", "талдықорған", "taldykorgan"), "Петропавловск": ("петропавл", "petropavl"),
    "Актау": ("актау", "ақтау", "aktau"), "Темиртау": ("темиртау", "теміртау", "temirtau"),
    "Экибастуз": ("экибастуз", "екібастұз", "ekibastuz"), "Жезказган": ("жезказган", "жезқазған", "zhezkazgan"),
    "Рудный": ("рудном", "рудного", "г. рудный", "rudny"), "Аркалык": ("аркалык", "арқалық", "arkalyk"),
}


def _add_cities() -> None:
    """Регионы для всех городов, где есть вузы базы (Алматы и Астана уже есть выше)."""
    for city in sorted({u["city"] for u in UNIS.values()}):
        if city in CITY_WORDS and city not in REGIONS:
            REGIONS[city] = CITY_WORDS[city]
            REGION_NAMES[city] = city


def region_of(text: str | None) -> str | None:
    """Регион по тексту (городу из профиля или вопросу). None — если в базе нет вузов этого города."""
    low = (text or "").lower()
    return next((r for r, words in REGIONS.items() if any(w in low for w in words)), None)


_add_cities()


def uni_region(slug: str) -> str | None:
    return region_of(UNIS[slug]["city"])


def _home_first(keys: list[str], home: str | None) -> list[str]:
    """Сначала программы вузов в городе человека, потом остальные — порядок внутри групп сохраняем."""
    if not home:
        return keys
    return [k for k in keys if uni_region(k.split(":")[0]) == home] + \
           [k for k in keys if uni_region(k.split(":")[0]) != home]


def _avoid_filter(pool: list[dict], text: str, slugs: list[str], avoid: dict | None) -> list[dict]:
    """Убирает вузы и направления, от которых человек отказался (если он сейчас сам о них не спрашивает)."""
    if not avoid:
        return pool
    asked = set(slugs) - set(avoid.get("just_rejected", []))       # вуз назван в вопросе — его не прячем
    no_unis = [s for s in avoid.get("no_unis", []) if s not in asked]
    low = text.lower()
    just = set(avoid.get("just_topics", []))                        # отказ в этом же сообщении — прячем сразу
    no_topics = [t for t in avoid.get("no_topics", []) if t in just or t not in low]
    def ok(p: dict) -> bool:
        if p["key"].split(":")[0] in no_unis:
            return False
        words = _TOKEN.findall(" ".join((p["name_ru"], p.get("name_translation", ""))).lower())
        return not any(w.startswith(t) for w in words for t in no_topics)  # «право» ≠ «упРАВление»
    return [p for p in pool if ok(p)] or pool


def relevant(text: str, recent: list[str], limit: int = 8, home: str | None = None, avoid: dict | None = None) -> list[str]:
    """Какие программы (ключи «вуз:код») подробно показать ИИ для этого вопроса — из всех вузов поровну.
    home — регион из профиля: его вузы идут первыми. Если в вопросе назван город — берём только его вузы."""
    slugs = mentioned_unis(text)
    asked_city = region_of(text)
    if not slugs and asked_city:  # «покажи вузы Алматы по IT» — только этот город
        slugs = [s for s in UNIS if uni_region(s) == asked_city]
        home = None
    if avoid and avoid.get("just_rejected"):  # «не хочу в КазНУ» — программы КазНУ в этом ответе не нужны
        slugs = [s for s in slugs if s not in avoid["just_rejected"]]
    named = [s for s in mentioned_unis(text) if not avoid or s not in avoid.get("just_rejected", [])]
    pool = _avoid_filter([p for s in (slugs or UNIS) for p in UNIS[s]["programs"].values()], text, named, avoid)
    allowed = {p["key"] for p in pool}
    recent = [k for k in recent if k in allowed]
    # Название программы написано в вопросе целиком (в любом падеже) — она точно нужна, и первой.
    text_stems = [_stem(t) for t in _TOKEN.findall(text.lower().replace("ё", "е")) if len(t) > 2]
    # «Сдаю историю и право» / «у меня математика и физика» — это предметы ЕНТ, а не программы «История»,
    # «Математика и физика». Такие названия считаем программой, только если в вопросе назван вуз.
    pair = bool(_groups(text)) and not slugs
    only_subjects = lambda seq: all(any(x.startswith(sub[:4]) for sub in _SUBJECTS) or x in ("основ", "язык", "литер")
                                    for x in seq)
    exact = [p["key"] for p in pool if p["open"] and _contains_seq(text_stems, _name_seq(p))
             and not (pair and only_subjects(_name_seq(p)))]
    random.shuffle(exact)  # одинаковые названия в разных вузах — без порядка «по алфавиту»
    exact.sort(key=lambda k: -len(_name_seq(program(k))))  # «Математика и информатика» важнее «Математика»
    groups = _groups(text)
    if groups:
        pool = [p for p in pool if set(p["ent_groups"]) & groups] or pool
    query = avoid.get("query") if avoid and "query" in avoid else text  # в сообщении-отказе ищем без самого отказа
    stems = _stems(query)
    if avoid and "query" in avoid and not stems:  # чистый отказ: продолжаем прошлую тему без отвергнутого
        return _balanced(_home_first(recent, home), limit, per_uni=limit if len(slugs) == 1 else 2)
    scored = _ranked([(_score(p, stems), p["key"]) for p in pool])
    top = scored[0][0] if scored else 0
    result = [k for sc, k in scored if sc > 0 and sc * 2 >= top]  # отсекаем случайные совпадения
    if not result and groups:  # «у меня математика и физика — куда поступить?»
        result = random.sample([p["key"] for p in pool if p["open"]], k=sum(1 for p in pool if p["open"]))
    if not result:  # «а сколько стоит?» — продолжаем про недавние программы
        result = [k for k in recent if not slugs or k.split(":")[0] in slugs]
    if not result and slugs and len(slugs) <= 2:  # «что есть в КазНУ?» — программы этого вуза
        result = random.sample([p["key"] for p in pool if p["open"]], k=sum(1 for p in pool if p["open"]))
    if exact:
        longest = len(_name_seq(program(exact[0])))
        exact = [k for k in exact if len(_name_seq(program(k))) == longest]
        result = exact + [k for k in result if k not in exact]
    return _balanced(_home_first(result, home), limit, per_uni=limit if len(slugs) == 1 else 2)


def _name_seq(p: dict) -> list[str]:
    seq = p.get("_seq")
    if seq is None:
        seq = p["_seq"] = [_stem(t) for t in _TOKEN.findall(p["name_ru"].lower().replace("ё", "е")) if len(t) > 2]
    return seq


def _contains_seq(stems: list[str], seq: list[str]) -> bool:
    n = len(seq)
    return n > 0 and any(stems[i:i + n] == seq for i in range(len(stems) - n + 1))


def select(text: str, recent: list[str], asked: str | None = None, home: str | None = None,
           avoid: dict | None = None) -> list[str]:
    """Программы для ответа ИИ. asked — программа, под карточкой которой нажали «Задать вопрос ИИ»."""
    # старые записи (до объединения вузов) хранили коды AlmaU без «вуз:» — пропускаем всё неизвестное
    recent = [k for k in recent if ":" in k and k.split(":")[1] in UNIS.get(k.split(":")[0], {}).get("programs", {})]
    if asked and ":" in asked and asked.split(":")[1] not in UNIS.get(asked.split(":")[0], {}).get("programs", {}):
        asked = None
    if asked and not mentioned_unis(text):
        return [asked]
    keys = relevant(text, recent, home=home, avoid=avoid)
    return ([asked] + [k for k in keys if k != asked])[:8] if asked else keys


def for_quiz(tags: list[str], group: str | None, limit: int = 8, home: str | None = None,
             avoid: dict | None = None) -> list[str]:
    """Программы для анкеты «Подобрать специальность»: по интересам и предметам ЕНТ, из всех вузов поровну."""
    words = [w for t in tags for w in INTERESTS[t]["words"]]
    pool = _avoid_filter([p for u in UNIS.values() for p in u["programs"].values()
                          if p["open"] and (group is None or group in p["ent_groups"])], "", [], avoid)
    # Программа «на любые предметы» (AI + X в MNU) не должна выходить в каждой анкете — при выбранных предметах
    # она чуть ниже программ, сделанных именно под эти предметы.
    scored = _ranked([(_score(p, words) - (1 if group and len(p["ent_groups"]) >= 8 and _score(p, words) else 0), p["key"])
                      for p in pool])
    keys = [k for sc, k in scored if sc > 0] or [k for _, k in scored]
    return _balanced(_home_first(keys, home), limit)


# ---------------------------------------------------------------------------
# Тексты для кнопок (без ИИ)
# ---------------------------------------------------------------------------
def all_groups() -> list[str]:
    present = {g for u in UNIS.values() for p in u["programs"].values() if p["open"] for g in p["ent_groups"]}
    return [g for g in ENT_LABELS if g in present]


def groups_in(slug: str) -> list[str]:
    present = {g for p in UNIS[slug]["programs"].values() if p["open"] for g in p["ent_groups"]}
    return [g for g in ENT_LABELS if g in present]


def programs_in(slug: str, group: str) -> list[dict]:
    return [p for p in UNIS[slug]["programs"].values() if p["open"] and group in p["ent_groups"]]


def unis_with(group: str, home: str | None = None) -> list[str]:
    return ordered([slug for slug in UNIS if programs_in(slug, group)], home)


def ordered(slugs: list[str], home: str | None = None) -> list[str]:
    """Сначала вузы города человека, потом остальные по алфавиту."""
    return sorted(slugs, key=lambda s: (uni_region(s) != home if home else False, UNIS[s]["short"].lower()))


PAGE = 10


def unis_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "вуз"
    return "вуза" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "вузов"


def uni_text(slug: str, lang: str) -> str:
    u = UNIS[slug]
    kz = lang == "kz"
    n = sum(1 for p in u["programs"].values() if p["open"])
    facts = [f"📍 {esc(' · '.join(x for x in (u['city'], u.get('region') if u.get('region') != u['city'] else '') if x))}"]
    if u.get("type"):
        facts.append(("Түрі: " if kz else "Тип: ") + esc(u["type"]))
    facts.append((f"Бакалавриат бағдарламалары: {n}" if kz else f"Программ бакалавриата: {n}"))
    if u.get("students"):
        facts.append((f"Студенттер: {u['students']:,}" if kz else f"Студентов: {u['students']:,}").replace(",", " "))
    if u.get("rating"):
        facts.append(("Рейтинг: " if kz else "Рейтинг: ") + esc(u["rating"]))
    if u.get("website"):
        facts.append(("🌐 Сайт: " if not kz else "🌐 Сайты: ") + u["website"])
    a = u.get("admissions") or {}
    if a.get("phones"):
        facts.append("📞 " + esc(", ".join(a["phones"])))
    return (f"🏛 {b(uni_name(slug, lang))}\n" + "\n".join(facts) + "\n\n" + f"{esc(u['notes'])}\n\n💰 {esc(u['price_note'])}\n\n"
            + ("ҰБТ пәндеріңді таңда — бағдарламаларды көрсетемін:" if kz
               else "Выбери свои предметы ЕНТ — покажу программы:"))


def programs_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "программа"
    return "программы" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "программ"


def ent_text(group: str, lang: str, page: int = 0, home: str | None = None) -> str:
    kz = lang == "kz"
    slugs = unis_with(group, home)
    shown = slugs[page * PAGE:(page + 1) * PAGE]
    lines = [f"📝 {b(ENT_LABELS[group][lang])}\n",
             (f"Осы пәндермен түсуге болатын ЖОО: {len(slugs)}" if kz else f"Где можно учиться с этими предметами — вузов: {len(slugs)}")
             + (f" ({page * PAGE + 1}–{page * PAGE + len(shown)})" if len(slugs) > PAGE else "")]
    for slug in shown:
        n = len(programs_in(slug, group))
        lines.append(f"• {b(UNIS[slug]['short'])}, {esc(UNIS[slug]['city'])} — {n} " + ("бағдарлама" if kz else programs_word(n)))
    lines.append("\nЖОО-ны таңда:" if kz else "\nВыбери вуз:")
    return "\n".join(lines)


def group_text(slug: str, group: str, lang: str) -> str:
    kz = lang == "kz"
    lines = [f"🏛 {b(UNIS[slug]['short'])} · {esc(ENT_LABELS[group][lang])}\n"]
    items = []
    for p in programs_in(slug, group):
        g = p.get("grant_2026") or {}
        grant = (f", грант 2026: {g['min']} бастап" if kz else f", грант 2026 от {g['min']}") if g.get("count") else ""
        items.append((f"• {b(prog_name(p, lang))} — {esc(price_text(p, lang))}{grant}", f"• {b(prog_name(p, lang))}"))
    tail = "\nТолығырақ білу үшін бағдарламаны бас." if kz else "\nНажми на программу, чтобы узнать подробнее."
    full = "\n".join(lines + [x for x, _ in items] + [tail])
    if len(full) <= 3900:
        return full
    # Не помещается в одно сообщение Telegram — только названия; цена и грант — в карточке программы.
    short = lines + [y for _, y in items]
    note = ("\nБағасы мен гранты — бағдарлама карточкасында." if kz else "\nЦена и грант — в карточке программы.")
    text = "\n".join(short + [note, tail])
    while len(text) > 3900 and len(short) > 2:
        short.pop()
        text = "\n".join(short + ["…", note, tail])
    return text


def program_card(key: str, lang: str) -> str:
    """Карточка программы (HTML): важное — жирным."""
    slug, code = key.split(":")
    p = program(key)
    extra = catalog.PROGRAMS.get(code, {}) if slug == "almau" else {}   # у AlmaU есть срок, практика, оговорки
    kz = lang == "kz"
    head = f"🎓 {b(prog_name(p, lang))} ({esc(p['code'])})"
    lines = [head, f"🏛 {esc(uni_name(slug, lang))} · {esc(UNIS[slug]['city'])}"] + ([esc(p["section"])] if p.get("section") else [])
    if extra.get("degree"):
        lines.append(f"{esc(extra['degree'])} · {extra['duration_years']} " + ("жыл" if kz else "года"))
    elif p.get("duration") or p.get("languages"):
        lines.append("⏳ " + esc(" · ".join(x for x in (duration_text(p, lang), languages_text(p, lang)) if x)))
    extra_facts = []
    if p.get("credits"):
        extra_facts.append(f"{p['credits']} " + ("кредит" if kz else "кредитов ECTS"))
    if p.get("format"):
        extra_facts.append(("оқу формасы: " if kz else "форма: ") + FORMAT_KZ.get(p["format"], p["format"]) if kz else "форма: " + p["format"])
    if p.get("thesis") == "да":
        extra_facts.append("дипломдық жұмыс бар" if kz else "есть дипломная работа")
    if extra_facts:
        lines.append("📚 " + esc(" · ".join(extra_facts)))
    if p.get("not_in_reference"):
        lines.append("⚠️ " + ("Бағдарлама ЖОО анықтамасында жоқ, ашық каталогта бар — 2026 жылғы қабылдауды комиссиядан нақтыла."
                             if kz else "Программы нет в справке вуза, но она есть в открытом каталоге — набор в 2026 году уточняй в приёмной."))
    if not p["open"]:
        lines.append("⚠️ " + b("2026 жылы бұл бағдарламаға қабылдау жоқ." if kz else "В 2026 году набора на эту программу нет."))
    else:
        ent = ENT_LABELS[p["ent_groups"][0]][lang] if p.get("ent_groups") and (kz or not p["ent_subjects"]) else p["ent_subjects"]
        lines.append(("📝 ҰБТ: " if kz else "📝 ЕНТ: ") + b(ent or ("қабылдау комиссиясынан нақтыла" if kz else "уточнять в приёмной комиссии"))
                     + ((" (ұқсас бағдарламалар бойынша — қабылдау комиссиясынан нақтыла)" if kz else
                         " (по похожим программам — уточни в приёмной)") if "ent_subjects" in p.get("inferred", []) else ""))
        lines.append("💰 " + b(price_text(p, lang)))
        if p.get("grant_2026"):
            lines.append(esc(grant_text(p, lang)) + ((" — топ ұқсас бағдарламалар бойынша анықталды" if kz else
                                                      " — группа определена по похожим программам")
                                                     if "group" in p.get("inferred", []) else ""))
    if p.get("ent_note"):
        lines.append("⚠️ " + esc(p["ent_note"]))
    if p.get("about"):
        lines.append("\n" + b("Бағдарлама туралы:" if kz else "О программе:") + " " + esc(p["about"]))
    if p.get("tracks"):
        lines.append("\n" + b("Траекториялар (мамандану):" if kz else "Траектории обучения (специализации):"))
        lines += [f"• {b(t)}" for t in p["tracks"]]
    elif p.get("study_path"):
        lines.append("\n" + b("Оқу траекториясы — курстар бойынша:" if kz else "Траектория обучения по курсам:"))
        for year, items in p["study_path"].items():
            lines.append(f"• {b(year)}: " + esc(", ".join(items[:5])))
    if p.get("key_courses") and not p.get("study_path"):
        lines.append("\n" + b("Негізгі пәндер:" if kz else "Ключевые предметы:"))
        lines += [f"• {esc(c)}" for c in p["key_courses"][:8]]
    if extra.get("practice"):
        lines.append("\n" + b("Практика:") + " " + esc(extra["practice"]))
    if p.get("outcomes"):
        lines.append("\n" + b("Не үйренесің:" if kz else "Чему научишься:"))
        lines += [f"• {esc(x if len(x) <= 160 else x[:160].rsplit(' ', 1)[0] + '…')}" for x in p["outcomes"][:3]]
    if p.get("careers"):
        lines.append("\n" + b("Кім болып жұмыс істейді:" if kz else "Кем работают:") + " " + esc(", ".join(p["careers"])))
    if p.get("workplaces"):
        lines.append(b("Қайда:" if kz else "Где:") + " " + esc(", ".join(p["workplaces"])))
    if extra.get("note"):
        lines.append("\nℹ️ " + esc(extra["note"]))
    if UNIS[slug].get("catalog"):
        lines.append("\nℹ️ " + ("Деректер ЖОО-лардың ашық каталогынан алынды — қабылдау комиссиясынан нақтыла."
                               if kz else "Данные из открытого каталога вузов — уточняй в приёмной комиссии вуза."))
    else:
        lines.append("\nℹ️ " + ("Деректер бағдар ретінде берілген — ЖОО қабылдау комиссиясынан нақтыла." if kz
                               else "Данные ориентировочные — уточняй в приёмной комиссии вуза."))
    lines.append(esc(link_line(key, lang)))
    return "\n".join(lines)


def link_line(key: str, lang: str) -> str:
    slug, code = key.split(":")
    ln = links(slug, code)
    if ln.get("program"):
        return ("🔗 Бағдарлама сайтта: " if lang == "kz" else "🔗 Программа на сайте вуза: ") + ln["program"]
    if ln.get("bachelor_list"):
        return ("🔗 ЖОО сайтындағы бағдарламалар тізімі: " if lang == "kz" else "🔗 Список программ на сайте вуза: ") + ln["bachelor_list"]
    return ("🌐 ЖОО сайты: " if lang == "kz" else "🌐 Сайт вуза: ") + ln.get("site", "")


MAX_ENT_SCORE = 140


def gop_stats(group: str) -> dict[str, dict]:
    """Группы ГОП, куда ведут программы с этими предметами ЕНТ: минимум по стране и по каждому вузу."""
    out: dict[str, dict] = {}
    for slug in UNIS:
        for p in programs_in(slug, group):
            g = p.get("grant_2026")
            if not g or g.get("kz_min") is None:
                continue
            item = out.setdefault(g["gop"], {"kz_min": g["kz_min"], "unis": {}, "programs": {}})
            item["programs"].setdefault(slug, []).append(p["name_ru"])
            if g.get("count"):
                item["unis"][slug] = {"min": g["min"], "count": g["count"]}
            else:
                item["unis"].setdefault(slug, None)
    return out


def grant_chances(group: str, score: int, lang: str, home: str | None = None) -> str:
    """Ответ калькулятора «Шанс на грант» (по данным 2026 года, общий конкурс)."""
    kz = lang == "kz"
    stats = sorted(gop_stats(group).items(), key=lambda kv: kv[1]["kz_min"])
    lines = [f"🎯 {'Баллың' if kz else 'Твой балл'}: {b(score)} · {b(ENT_LABELS[group][lang])}",
             "2026 жылғы грант нәтижелері бойынша (жалпы конкурс, квотасыз):\n" if kz
             else "По итогам грантов 2026 года (общий конкурс, без квот):\n"]
    yes, no = [], []
    for gop, st in stats:
        (yes if score >= st["kz_min"] else no).append((gop, st))
    if yes:
        lines.append("✅ " + b("Осы баллмен грант берілген топтар:" if kz else "С таким баллом давали грант по группам:"))
        for gop, st in yes:
            lines.append(f"\n{b(gop)} — " + (f"ел бойынша {st['kz_min']} бастап" if kz else f"по стране от {st['kz_min']}"))
            ok, near, none = [], [], []
            for slug in ordered(list(st["programs"]), home):
                u = st["unis"].get(slug)
                short = b(UNIS[slug]["short"])
                if u and score >= u["min"]:
                    ok.append(f"✅ {short}: " + (f"{u['min']} бастап ({u['count']} грант)" if kz else f"от {u['min']} (грантов: {u['count']})"))
                elif u:
                    gap = u["min"] - score
                    near.append(f"🟡 {short}: " + (f"{u['min']} бастап — {gap} балл жетпейді" if kz
                                                  else f"от {u['min']} — не хватает {gap}"))
                else:
                    none.append(slug)
            lines += ["   " + x for x in ok[:12]]
            if len(ok) > 12:
                lines.append("   " + (f"…тағы {len(ok) - 12} ЖОО" if kz else f"…и ещё {len(ok) - 12} {unis_word(len(ok) - 12)}"))
            lines += ["   " + x for x in near[:5]]
            if len(near) > 5:
                lines.append("   " + (f"…тағы {len(near) - 5} ЖОО-ға сәл жетпейді" if kz else f"…и ещё {len(near) - 5} {unis_word(len(near) - 5)}, где чуть не хватает"))
            if none:
                lines.append("   ⚪ " + (f"2026 жылы грант берілмеген ЖОО: {len(none)}" if kz
                                        else f"вузов, куда в 2026 году грантов не было: {len(none)}"))
    if no:
        lines.append("\n❌ " + b("Әзірге жетпейді:" if kz else "Пока не хватает:"))
        for gop, st in no:
            gap = st["kz_min"] - score
            lines.append(f"• {b(gop)} — " + (f"{st['kz_min']} бастап ({gap} балл жетпейді)" if kz
                                          else f"от {st['kz_min']} (не хватает {gap})"))
    if not stats:
        lines.append("Бұл пәндер бойынша грант деректері жоқ." if kz else "По этим предметам данных о грантах нет.")
    lines.append("\nℹ️ " + (
        "Грант ЖОО-ға емес, топқа беріледі: топ бойынша өтсең, кез келген ЖОО-ны таңдауға болады, бірақ танымал ЖОО-ға "
        "балл жоғарырақ. Бұл 2026 жылғы деректер — келесі жылы шекті балл өзгереді, кепілдік емес. Ауыл квотасы бар болса, "
        "мүмкіндік жоғарырақ." if kz else
        "Грант дают на группу программ, а не на вуз: прошёл по группе — выбираешь любой вуз, но в популярные вузы нужен балл выше. "
        "Это данные 2026 года, не гарантия: в следующем году границы будут другими. С сельской квотой шансы выше."))
    if home:
        lines.append("📍 " + ("Алдымен — сенің қалаңның ЖОО-лары." if kz else "Сначала — вузы твоего города."))
    lines.append("✅ — " + ("ЖОО-ға осындай баллмен грант берілген" if kz else "в этот вуз с таким баллом брали") + " · 🟡 — "
                 + ("сәл жетпейді" if kz else "чуть не хватает") + " · ⚪ — " + ("ЖОО-ға грант берілмеді" if kz else "грантов в вуз не было"))
    return "\n".join(lines)


def contacts_text(lang: str, slugs: list[str] | None = None) -> str:
    """Контакты приёмных комиссий: вузов, о которых шла речь, или вузов города человека."""
    kz = lang == "kz"
    if not slugs:
        return ("☎️ Базада 120 ЖОО бар. Қай ЖОО-ның қабылдау комиссиясы керек екенін жаз, мысалы: «ҚазҰУ байланыстары» — "
                "немесе профильде қалаңды көрсет, сонда сол қаланың ЖОО-ларын көрсетемін." if kz else
                "☎️ В базе 120 вузов. Напиши, чья приёмная комиссия нужна, например: «контакты КазНУ» — "
                "или укажи город в профиле, и я покажу вузы твоего города.")
    lines = [b("☎️ ЖОО қабылдау комиссиялары:" if kz else "☎️ Приёмные комиссии вузов:")]
    for u in (UNIS[s] for s in slugs[:12]):
        a = u.get("admissions") or {}
        block = [f"\n🏛 {b(u['name_kz' if kz else 'name_ru'])}" + (f" ({esc(u['city'])})" if u.get("catalog") else "")]
        block += [f"📞 {esc(p)}" for p in a.get("phones", [])]
        if a.get("email"):
            block.append(f"✉️ {a['email']}")
        if a.get("hours"):
            block.append(f"🕘 {a['hours']}")
        if a.get("address"):
            block.append(f"📍 {esc(a['address'])}")
        if a.get("url") or u.get("website"):
            block.append(f"🌐 {a.get('url') or u.get('website', '')}")
        lines.append("\n".join(block))
    lines.append("\nКонтактілер ЖОО сайттарынан және ашық каталогтан алынды (қазан 2026) — құжат тапсырар алдында ЖОО сайтынан тексер." if kz
                 else "\nКонтакты — с сайтов вузов и из открытого каталога (октябрь 2026). Перед подачей документов сверь на сайте вуза.")
    return "\n".join(lines)

