# Все вузы бота на равных: AlmaU, ЕНУ, КБТУ, Нархоз, SDU (и любые новые из knowledge/universities/).
# Здесь — загрузка данных, краткий каталог для ИИ, подбор программ под вопрос и анкету,
# тексты для кнопок. Всё работает без ИИ и ничего не стоит.
#
# Данные: knowledge/universities/<вуз>/university.json + programs.json.
# AlmaU хранится в своём старом формате (knowledge/programs/*.json, см. catalog.py) — здесь он
# приводится к общему виду, поэтому для бота это такой же вуз, как остальные.
import json
import re
from pathlib import Path

import catalog
from catalog import INTERESTS, _contains, find_groups, money

UNI_DIR = Path(__file__).parent / "knowledge" / "universities"

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
             "дүниежүзі": "wh", "прав": "law", "құқық": "law", "казах": "kaz", "қазақ": "kaz", "русск": "rus",
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
            p["ent_groups"] = [g for g in [ent_group(p["ent_subjects"])] if g]
            p["open"] = True
        info["programs"] = {p["code"]: p for p in programs}
        unis[info["slug"]] = info
    for slug, u in unis.items():
        for p in u["programs"].values():
            p["key"] = f"{slug}:{p['code']}"
    return dict(sorted(unis.items(), key=lambda kv: kv[1]["short"]))  # по алфавиту — никого не выделяем


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
    return "бағасы нақтыланады" if lang == "kz" else "цена уточняется"


def grant_text(p: dict, lang: str) -> str:
    """Строка о госгрантах 2026 для карточки и списков."""
    g = p.get("grant_2026")
    if not g:
        return ""
    kz = lang == "kz"
    gop = g["gop"].split()[0]
    head = f"🏆 {'Мемлекеттік грант 2026' if kz else 'Госгрант 2026'} ({'топ' if kz else 'группа'} {gop}): "
    if g["count"]:
        return head + (f"ЖОО-ға {g['count']} грант, ең төменгі балл {g['min']} (ел бойынша {g['kz_min']})" if kz
                       else f"в вуз грантов — {g['count']}, мин. балл {g['min']} (по стране {g['kz_min']})")
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


def compact_catalog() -> str:
    """Короткий список программ всех вузов — лежит в кэшируемом system prompt."""
    blocks = []
    for u in UNIS.values():
        lines = [f"{u['name_ru']} — {u['city']}, {u['type']}. {u['price_note']} {u['notes']}",
                 "Приёмная комиссия: " + admissions_line(u),
                 "(код | программа | предметы ЕНТ | цена в год | группа ГОП для гранта)"]
        for p in u["programs"].values():
            if not p["open"]:
                lines.append(f"{p['code']} | {p['name_ru']} | НАБОРА В 2026 НЕТ")
                continue
            price = f"{p['price_kzt']} тг" if p["price_kzt"] else "цена не объявлена"
            gop = p["grant_2026"]["gop"].split()[0] if p.get("grant_2026") else "—"
            lines.append(f"{p['code']} | {p['name_ru']} | {p['ent_subjects']} | {price} | {gop}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def details(keys: list[str]) -> str | None:
    """Подробные данные выбранных программ для блока <program_details> (JSON)."""
    out = []
    for key in keys:
        slug, code = key.split(":")
        u = UNIS[slug]
        if slug == "almau":  # у AlmaU полей больше: практика, оговорки, языки
            src = catalog.PROGRAMS[code]
            fields = ["code", "name_ru", "name_kz", "school", "degree", "duration_years", "tracks", "key_courses",
                      "practice", "note", "ent_subjects", "extra_ent_subjects", "ent_note", "price_kzt", "price_note",
                      "availability_note", "languages", "grant_2026"]
            out.append({"university": u["name_ru"], **{k: src[k] for k in fields if k in src}})
            continue
        p = u["programs"][code]
        out.append({"university": u["name_ru"], "city": u["city"], "price_note": u["price_note"],
                    **{k: p[k] for k in ("code", "name_ru", "section", "ent_subjects", "ent_note", "price_kzt",
                                         "tracks", "key_courses", "careers", "workplaces", "grant_2026")
                       if p.get(k) not in (None, "", [])}})
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")) if out else None


# ---------------------------------------------------------------------------
# Подбор программ под вопрос
# ---------------------------------------------------------------------------
def mentioned_unis(text: str) -> list[str]:
    low = text.lower()
    return [slug for slug, u in UNIS.items() if any(a in low for a in u["aliases"])]


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
    """Основы слов вопроса: без служебных слов, названий вузов и предметов ЕНТ."""
    aliases = [a for u in UNIS.values() for a in u["aliases"]]
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


def relevant(text: str, recent: list[str], limit: int = 8) -> list[str]:
    """Какие программы (ключи «вуз:код») подробно показать ИИ для этого вопроса — из всех вузов поровну."""
    slugs = mentioned_unis(text)
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
    return _balanced(result, limit, per_uni=limit if len(slugs) == 1 else 2)


def select(text: str, recent: list[str], asked: str | None = None) -> list[str]:
    """Программы для ответа ИИ. asked — программа, под карточкой которой нажали «Задать вопрос ИИ»."""
    # старые записи (до объединения вузов) хранили коды AlmaU без «вуз:» — пропускаем всё неизвестное
    recent = [k for k in recent if ":" in k and k.split(":")[1] in UNIS.get(k.split(":")[0], {}).get("programs", {})]
    if asked and ":" in asked and asked.split(":")[1] not in UNIS.get(asked.split(":")[0], {}).get("programs", {}):
        asked = None
    if asked and not mentioned_unis(text):
        return [asked]
    keys = relevant(text, recent)
    return ([asked] + [k for k in keys if k != asked])[:8] if asked else keys


def for_quiz(tags: list[str], group: str | None, limit: int = 8) -> list[str]:
    """Программы для анкеты «Подобрать специальность»: по интересам и предметам ЕНТ, из всех вузов поровну."""
    words = [w for t in tags for w in INTERESTS[t]["words"]]
    pool = [p for u in UNIS.values() for p in u["programs"].values()
            if p["open"] and (group is None or group in p["ent_groups"])]
    scored = sorted(((_score(p, words), p["key"]) for p in pool), key=lambda x: -x[0])
    keys = [k for sc, k in scored if sc > 0] or [k for _, k in scored]
    return _balanced(keys, limit)


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


def unis_with(group: str) -> list[str]:
    return [slug for slug in UNIS if programs_in(slug, group)]


def uni_text(slug: str, lang: str) -> str:
    u = UNIS[slug]
    kz = lang == "kz"
    n = sum(1 for p in u["programs"].values() if p["open"])
    return (f"🏛 {uni_name(slug, lang)}\n{u['city']} · {u['type']}\n"
            + (f"Бағдарламалар: {n}\n\n" if kz else f"Программ: {n}\n\n") + f"{u['notes']}\n\n💰 {u['price_note']}\n\n"
            + ("ҰБТ пәндеріңді таңда — бағдарламаларды көрсетемін:" if kz
               else "Выбери свои предметы ЕНТ — покажу программы:"))


def ent_text(group: str, lang: str) -> str:
    kz = lang == "kz"
    lines = [f"📝 {ENT_LABELS[group][lang]}\n", "Осы пәндермен түсуге болатын ЖОО:" if kz else "Где можно учиться с этими предметами:"]
    for slug in unis_with(group):
        n = len(programs_in(slug, group))
        lines.append(f"• {UNIS[slug]['short']} — {n} " + ("бағдарлама" if kz else "программ(ы)"))
    lines.append("\nЖОО-ны таңда:" if kz else "\nВыбери вуз:")
    return "\n".join(lines)


def group_text(slug: str, group: str, lang: str) -> str:
    lines = [f"🏛 {UNIS[slug]['short']} · {ENT_LABELS[group][lang]}\n"]
    for p in programs_in(slug, group):
        g = p.get("grant_2026") or {}
        grant = (f", грант 2026 от {g['min']}" if lang != "kz" else f", грант 2026: {g['min']} бастап") \
            if g.get("count") else ""
        lines.append(f"• {prog_name(p, lang)} — {price_text(p, lang)}{grant}")
    lines.append("\nБағдарламаны басып, толығырақ біліңіз." if lang == "kz"
                 else "\nНажми на программу, чтобы узнать подробнее.")
    return "\n".join(lines)


def program_card(key: str, lang: str) -> str:
    slug, code = key.split(":")
    if slug == "almau":  # у AlmaU карточка подробнее (траектории, практика) — берём её, баллы показываем как у всех
        lines = [line for line in catalog.program_card(code, lang).split("\n") if not line.startswith("🏆")]
        lines.insert(1, f"🏛 {uni_name(slug, lang)} · {UNIS[slug]['city']}")
        price_at = next((i for i, line in enumerate(lines) if line.startswith("💰")), None)
        grant = grant_text(program(key), lang)
        if price_at is not None and grant:
            lines.insert(price_at + 1, grant)
        return "\n".join(lines)
    p = program(key)
    kz = lang == "kz"
    lines = [f"🎓 {p['name_ru']} ({p['code']})", f"🏛 {uni_name(slug, lang)} · {UNIS[slug]['city']}", p["section"],
             ("ҰБТ: " if kz else "ЕНТ: ") + p["ent_subjects"], "💰 " + price_text(p, lang)]
    if p.get("grant_2026"):
        lines.append(grant_text(p, lang))
    if p.get("ent_note"):
        lines.append("⚠️ " + p["ent_note"])
    if p.get("tracks"):
        lines.append("\nТраекториялар:" if kz else "\nТраектории (специализации):")
        lines += [f"• {t}" for t in p["tracks"]]
    if p.get("key_courses"):
        lines.append("\nНегізгі пәндер:" if kz else "\nКлючевые предметы:")
        lines += [f"• {c}" for c in p["key_courses"][:8]]
    if p.get("careers"):
        lines.append(("\nКім болып жұмыс істейді: " if kz else "\nКем работают: ") + ", ".join(p["careers"]))
    if p.get("workplaces"):
        lines.append(("Қайда: " if kz else "Где: ") + ", ".join(p["workplaces"]))
    lines.append("\nℹ️ " + ("Деректер бағдар үшін — вуздың қабылдау комиссиясынан нақтылаңыз." if kz
                           else "Данные ориентировочные — уточняй в приёмной комиссии вуза."))
    return "\n".join(lines)


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


def grant_chances(group: str, score: int, lang: str) -> str:
    """Ответ калькулятора «Шанс на грант» (по данным 2026 года, общий конкурс)."""
    kz = lang == "kz"
    stats = sorted(gop_stats(group).items(), key=lambda kv: kv[1]["kz_min"])
    lines = [f"🎯 {'Балың' if kz else 'Твой балл'}: {score} · {ENT_LABELS[group][lang]}",
             "2026 жылғы грант нәтижелері бойынша (жалпы конкурс, квотасыз):\n" if kz
             else "По итогам грантов 2026 года (общий конкурс, без квот):\n"]
    yes, no = [], []
    for gop, st in stats:
        (yes if score >= st["kz_min"] else no).append((gop, st))
    if yes:
        lines.append("✅ " + ("Осы баллмен грант берілген топтар:" if kz else "С таким баллом давали грант по группам:"))
        for gop, st in yes:
            lines.append(f"\n{gop} — " + (f"ел бойынша {st['kz_min']} бастап" if kz else f"по стране от {st['kz_min']}"))
            for slug in sorted(st["programs"], key=lambda s: UNIS[s]["short"]):
                u = st["unis"].get(slug)
                short = UNIS[slug]["short"]
                if u and score >= u["min"]:
                    mark = f"✅ {short}: " + (f"{u['min']} бастап ({u['count']} грант)" if kz else f"от {u['min']} ({u['count']} гр.)")
                elif u:
                    gap = u["min"] - score
                    mark = f"🟡 {short}: " + (f"{u['min']} бастап — {gap} балл жетпейді" if kz
                                              else f"от {u['min']} — не хватает {gap}")
                else:
                    mark = f"⚪ {short}: " + ("2026 жылы бұл ЖОО-ға грант болмады" if kz else "в 2026 грантов в этот вуз не было")
                lines.append("   " + mark)
    if no:
        lines.append("\n❌ " + ("Әзірге жетпейді:" if kz else "Пока не хватает:"))
        for gop, st in no[:6]:
            gap = st["kz_min"] - score
            lines.append(f"• {gop} — " + (f"{st['kz_min']} бастап ({gap} балл жетпейді)" if kz
                                          else f"от {st['kz_min']} (не хватает {gap})"))
    if not stats:
        lines.append("Бұл пәндер бойынша грант деректері жоқ." if kz else "По этим предметам данных о грантах нет.")
    lines.append("\nℹ️ " + (
        "Грант ЖОО-ға емес, топқа беріледі: топ бойынша өтсең, кез келген ЖОО-ны таңдауға болады, бірақ танымал ЖОО-ға "
        "балл жоғарырақ. Бұл 2026 жылғы деректер — келесі жылы шекті балл өзгереді, кепілдік емес. Ауыл квотасы бар болса, "
        "мүмкіндік жоғарырақ." if kz else
        "Грант дают на группу, а не на вуз: прошёл по группе — можешь выбрать любой вуз, но в популярные вузы балл выше. "
        "Это данные 2026 года: в следующем году границы будут другими, это не гарантия. Если у тебя сельская квота, "
        "шансы выше."))
    lines.append("✅ — " + ("ЖОО-ға осындай баллмен грант берілген" if kz else "в этот вуз с таким баллом брали") + " · 🟡 — "
                 + ("сәл жетпейді" if kz else "чуть не хватает") + " · ⚪ — " + ("ЖОО-ға грант болмады" if kz else "грантов в вуз не было"))
    return "\n".join(lines)


def contacts_text(lang: str) -> str:
    kz = lang == "kz"
    lines = ["☎️ ЖОО қабылдау комиссиялары:" if kz else "☎️ Приёмные комиссии вузов:"]
    for u in UNIS.values():
        a = u.get("admissions") or {}
        block = [f"\n🏛 {u['name_kz' if kz else 'name_ru']}"]
        block += [f"📞 {p}" for p in a.get("phones", [])]
        if a.get("email"):
            block.append(f"✉️ {a['email']}")
        if a.get("hours"):
            block.append(f"🕘 {a['hours']}")
        if a.get("address"):
            block.append(f"📍 {a['address']}")
        block.append(f"🌐 {a.get('url') or u.get('website', '')}")
        lines.append("\n".join(block))
    lines.append("\nКонтактілер ЖОО ресми сайттарынан алынды (қазан 2026) — құжат тапсырар алдында сайттан тексер." if kz
                 else "\nКонтакты взяты с официальных сайтов вузов (октябрь 2026) — перед подачей документов сверь на сайте.")
    return "\n".join(lines)
