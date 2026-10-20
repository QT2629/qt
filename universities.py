# Все вузы бота на равных: AITU, AlmaU, ЕНУ, КазАТУ, КБТУ, MNU, Нархоз, Satbayev, SDU (и любые новые из knowledge/universities/).
# Здесь — загрузка данных, краткий каталог для ИИ, подбор программ под вопрос и анкету,
# тексты для кнопок. Всё работает без ИИ и ничего не стоит.
#
# Данные: knowledge/universities/<вуз>/university.json + programs.json.
# AlmaU хранится в своём старом формате (knowledge/programs/*.json, см. catalog.py) — здесь он
# приводится к общему виду, поэтому для бота это такой же вуз, как остальные.
import gzip
import json
import re
from pathlib import Path

import catalog
from formatting import b, esc
from catalog import INTERESTS, _contains, find_groups, money

UNI_DIR = Path(__file__).parent / "knowledge" / "universities"
# Каталог бакалавриата всех вузов страны (univision.kz + studyinkz.kz + реестр epvo.kz, гранты 2026).
# Собирается программой tools/build_catalog.py.
CATALOG_PATH = Path(__file__).parent / "knowledge" / "catalog" / "kz_bachelor.json.gz"

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
    unis.update(_catalog_unis(unis))
    for slug, u in unis.items():
        for p in u["programs"].values():
            p["key"] = f"{slug}:{p['code']}"
    return dict(sorted(unis.items(), key=lambda kv: kv[1]["short"]))  # по алфавиту — никого не выделяем


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
            for code, p in unis[u["existing"]]["programs"].items():
                c = progs.get(code)
                if not c:
                    continue
                if not p.get("track_courses") and c.get("study_path"):
                    p["study_path"] = c["study_path"]
                for field in ("about", "careers"):
                    if not p.get(field) and c.get(field):
                        p[field] = c[field]
            continue
        slug = f"u{u['id']}"
        names = [u["short"], u["name_ru"], u.get("name_en", "")]
        aliases = [a.lower() for a in names if a and len(a) >= 5]
        aliases += [a for a in u.get("aliases", []) if len(a) >= 4 or a.isascii() and len(a) >= 3]
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
            "slug": slug, "short": u["short"], "name_ru": u["name_ru"], "name_kz": u["name_ru"],
            "aliases": list(dict.fromkeys(aliases)), "city": u.get("city") or "город не указан", "type": "",
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
                    "admissions": admissions_line(u),
                    "all_bachelor_programs": [f"{p['name_ru']} ({p['code']})" for p in u["programs"].values() if p["open"]]})
    for key in keys:
        slug, code = key.split(":")
        u = UNIS[slug]
        if slug == "almau":  # у AlmaU полей больше: практика, оговорки, языки
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
                    **{k: p[k] for k in ("code", "name_ru", "section", "ent_subjects", "ent_note", "price_kzt",
                                         "price_other", "duration", "languages", "tracks", "track_courses", "about",
                                         "study_path", "key_courses", "careers", "workplaces", "grant_2026")
                       if p.get(k) not in (None, "", [], {})}, "links": links(slug, code)})
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")) if out else None


# ---------------------------------------------------------------------------
# Подбор программ под вопрос
# ---------------------------------------------------------------------------
def mentioned_unis(text: str) -> list[str]:
    low = " " + re.sub(r"[^\w-]+", " ", text.lower()) + " "  # пробелы по краям — чтобы находить «ЮКУ» как слово
    return [slug for slug, u in UNIS.items() if any(_norm(a) in low for a in u["aliases"])]


def _norm(alias: str) -> str:
    return re.sub(r"[^\w-]+", " ", alias.lower()) if alias.strip() == alias else " " + alias.strip() + " "


_STOP = {"бакалавр", "делового", "администрирования", "области", "программы", "программа", "двойной", "диплом",
         "университет", "университете", "лондона", "отраслям", "расскажи", "сколько", "стоит", "учиться", "хочу",
         "какие", "какой", "какая", "есть", "можно", "поступить", "мне", "для", "где", "что", "как", "или", "вузе",
         "вуза", "вузы", "вузах", "лучше", "сравни", "сравнить", "про", "это", "специальность", "специальности",
         "предметы", "предмет", "балл", "баллы", "грант", "грантов", "цена", "цены", "стоимость", "куда", "меня",
         "нужны", "нужно", "подходит", "подойдёт", "подойдет", "выбрать", "учеба", "учёба", "обучение"}
_SUBJECT_STEMS = list(_SUBJECTS) + ["ент", "ұбт", "экзамен", "творческ"]
_SYNONYMS = {"it": ["информ", "программ", "компьютер"], "айти": ["информ", "программ", "компьютер"],
             "ai": ["искусствен"], "ии": ["искусствен"], "юрис": ["юрисп", "прав"], "юрист": ["юрисп", "прав"],
             "програм": ["программ", "информ"]}


def _stems(text: str) -> list[str]:
    """Основы слов вопроса: без служебных слов, названий вузов и предметов ЕНТ.
    Названия предметов отбрасываем, только когда в вопросе есть пара ЕНТ: иначе «право» или «история» —
    это направление, которое человек ищет."""
    aliases = [a for u in UNIS.values() for a in u["aliases"]]
    subjects = _SUBJECT_STEMS if _groups(text) else ["ент", "ұбт", "экзамен"]
    out = []
    for w in re.findall(r"[\w-]+", text.lower()):
        if w in _STOP or any(a in w for a in aliases) or any(w.startswith(s) for s in subjects) or region_of(w):
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
    name = (p["name_ru"] + " " + p.get("name_kz", "")).lower()
    rest = " ".join(p["key_courses"] + p["careers"] + p.get("tracks", [])).lower()
    score = 0
    for st in stems:
        hit = (lambda t: _contains(t, st)) if len(st) <= 3 else (lambda t: st in t)
        score += 3 if hit(name) else 1 if hit(rest) else 0
    return score


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


def relevant(text: str, recent: list[str], limit: int = 8, home: str | None = None) -> list[str]:
    """Какие программы (ключи «вуз:код») подробно показать ИИ для этого вопроса — из всех вузов поровну.
    home — регион из профиля: его вузы идут первыми. Если в вопросе назван город — берём только его вузы."""
    slugs = mentioned_unis(text)
    asked_city = region_of(text)
    if not slugs and asked_city:  # «покажи вузы Алматы по IT» — только этот город
        slugs = [s for s in UNIS if uni_region(s) == asked_city]
        home = None
    pool = [p for s in (slugs or UNIS) for p in UNIS[s]["programs"].values()]
    groups = _groups(text)
    if groups:
        pool = [p for p in pool if set(p["ent_groups"]) & groups] or pool
    stems = _stems(text)
    scored = sorted(((_score(p, stems), p["key"]) for p in pool), key=lambda x: -x[0])
    top = scored[0][0] if scored else 0
    result = [k for sc, k in scored if sc > 0 and sc * 2 >= top]  # отсекаем случайные совпадения
    if not result and groups:  # «у меня математика и физика — куда поступить?»
        result = [p["key"] for p in pool if p["open"]]
    if not result:  # «а сколько стоит?» — продолжаем про недавние программы
        result = [k for k in recent if not slugs or k.split(":")[0] in slugs]
    if not result and slugs and len(slugs) <= 2:  # «что есть в КазНУ?» — программы этого вуза
        result = [p["key"] for p in pool if p["open"]]
    return _balanced(_home_first(result, home), limit, per_uni=limit if len(slugs) == 1 else 2)


def select(text: str, recent: list[str], asked: str | None = None, home: str | None = None) -> list[str]:
    """Программы для ответа ИИ. asked — программа, под карточкой которой нажали «Задать вопрос ИИ»."""
    # старые записи (до объединения вузов) хранили коды AlmaU без «вуз:» — пропускаем всё неизвестное
    recent = [k for k in recent if ":" in k and k.split(":")[1] in UNIS.get(k.split(":")[0], {}).get("programs", {})]
    if asked and ":" in asked and asked.split(":")[1] not in UNIS.get(asked.split(":")[0], {}).get("programs", {}):
        asked = None
    if asked and not mentioned_unis(text):
        return [asked]
    keys = relevant(text, recent, home=home)
    return ([asked] + [k for k in keys if k != asked])[:8] if asked else keys


def for_quiz(tags: list[str], group: str | None, limit: int = 8, home: str | None = None) -> list[str]:
    """Программы для анкеты «Подобрать специальность»: по интересам и предметам ЕНТ, из всех вузов поровну."""
    words = [w for t in tags for w in INTERESTS[t]["words"]]
    pool = [p for u in UNIS.values() for p in u["programs"].values()
            if p["open"] and (group is None or group in p["ent_groups"])]
    scored = sorted(((_score(p, words), p["key"]) for p in pool), key=lambda x: -x[0])
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
    return (f"🏛 {b(uni_name(slug, lang))}\n{esc(' · '.join(x for x in (u['city'], u['type']) if x))}\n"
            + (f"Бағдарламалар: {n}\n\n" if kz else f"Программ: {n}\n\n") + f"{esc(u['notes'])}\n\n💰 {esc(u['price_note'])}\n\n"
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
    for p in programs_in(slug, group):
        g = p.get("grant_2026") or {}
        grant = (f", грант 2026: {g['min']} бастап" if kz else f", грант 2026 от {g['min']}") if g.get("count") else ""
        lines.append(f"• {b(prog_name(p, lang))} — {esc(price_text(p, lang))}{grant}")
    lines.append("\nТолығырақ білу үшін бағдарламаны бас." if kz else "\nНажми на программу, чтобы узнать подробнее.")
    return "\n".join(lines)


def program_card(key: str, lang: str) -> str:
    """Карточка программы (HTML): важное — жирным."""
    slug, code = key.split(":")
    p = program(key)
    extra = catalog.PROGRAMS.get(code, {}) if slug == "almau" else {}   # у AlmaU есть срок, практика, оговорки
    kz = lang == "kz"
    head = f"🎓 {b(prog_name(p, lang))} ({esc(p['code'])})"
    lines = [head, f"🏛 {esc(uni_name(slug, lang))} · {esc(UNIS[slug]['city'])}", esc(p["section"])]
    if extra.get("degree"):
        lines.append(f"{esc(extra['degree'])} · {extra['duration_years']} " + ("жыл" if kz else "года"))
    elif p.get("duration") or p.get("languages"):
        lines.append(esc(" · ".join(x for x in (p.get("duration"), p.get("languages")) if x)))
    if not p["open"]:
        lines.append("⚠️ " + b("2026 жылы бұл бағдарламаға қабылдау жоқ." if kz else "В 2026 году набора на эту программу нет."))
    else:
        lines.append(("📝 ҰБТ: " if kz else "📝 ЕНТ: ") + b(p["ent_subjects"] or ("приёмнан нақтыла" if kz else "уточнять в приёмной")))
        lines.append("💰 " + b(price_text(p, lang)))
        if p.get("grant_2026"):
            lines.append(esc(grant_text(p, lang)))
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
            lines.append(f"• {b(year)}: " + esc(", ".join(items[:4])))
    if p.get("key_courses") and not p.get("study_path"):
        lines.append("\n" + b("Негізгі пәндер:" if kz else "Ключевые предметы:"))
        lines += [f"• {esc(c)}" for c in p["key_courses"][:8]]
    if extra.get("practice"):
        lines.append("\n" + b("Практика:") + " " + esc(extra["practice"]))
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
    lines = [f"🎯 {'Балың' if kz else 'Твой балл'}: {b(score)} · {b(ENT_LABELS[group][lang])}",
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

