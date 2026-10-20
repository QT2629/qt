# Собирает компактный каталог бакалавриата всех вузов Казахстана для бота.
# Нужен, когда обновляются исходные файлы каталога (univision.kz + studyinkz.kz + реестр epvo.kz)
# или выходит новый список грантов. Боту эта программа не нужна — он читает готовый файл.
#
#   python tools/build_catalog.py <папка с pro4u_programs_full_*.json и pro4u_disciplines_*.json.gz> grants_rows.pkl
#
# grants_rows.pkl — строки официального списка грантов без ФИО: (группа ГОП, конкурс, балл, код вуза).
# Результат: knowledge/catalog/kz_bachelor.json.gz
import collections
import glob
import gzip
import json
import lzma
import pickle
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "knowledge" / "catalog" / "kz_bachelor.json.gz"
NAME_TR = __import__("runpy").run_path(str(OUT.parent / "name_translations.py"))["NAMES"]
FORMAT = {"On Campus": "очно", "Blended": "смешанный (очно + онлайн)", "Hybrid": "смешанный (очно + онлайн)",
          "On Campus, Blended": "очно или смешанный"}

# Города, которых нет в исходных данных (определены по названию и сайту вуза).
CITY_FIX = {1: "Кызылорда", 3: "Астана", 4: "Алматы", 6: "Алматы", 8: "Астана", 9: "Алматы", 10: "Актобе",
            12: "Алматы", 13: "Петропавловск", 14: "Алматы", 16: "Алматы", 17: "Алматы", 18: "Астана",
            19: "Алматы", 25: "Астана", 32: "Алматы", 43: "Астана", 44: "Астана", 59: "Астана", 61: "Астана",
            70: "Астана", 73: "Астана", 97: "Астана", 104: "Астана", 107: "Астана", 118: "Астана", 122: "Астана",
            127: "Астана", 132: "Астана"}

# Короткие названия и то, как вуз называют люди (для поиска по вопросу).
SHORT = {
    69: ("КазНУ им. аль-Фараби", ["казну", "аль-фараби", "альфараби", "фараби", "kaznu", "al-farabi"]),
    67: ("КазНПУ им. Абая", ["казнпу", "kaznpu"]),
    71: ("КазУМОиМЯ им. Абылай хана", ["абылай", "ablaikhan", "ablai khan", "казумо"]),
    66: ("КазНМУ им. Асфендиярова", ["казнму", "асфендияр", "kaznmu"]),
    128: ("KIMEP", ["кимэп", "kimep", "кимеп"]),
    105: ("МУИТ (IITU)", ["муит", "iitu"]),
    120: ("Университет «Туран»", ["туран"]),
    141: ("ЮКУ им. Ауэзова", ["ауэзов", "auezov", "юку "]),
    85: ("КарУ им. Букетова", ["букетов", "buketov"]),
    101: ("МКТУ им. Ясави", ["ясави", "yasawi", "yassawi"]),
    116: ("Торайгыров университет", ["торайгыров", "toraighyrov"]),
    64: ("Казахский национальный женский педагогический университет", ["женский педагогический", "казнжпу"]),
    63: ("КазНАУ (аграрный)", ["казнау", "kaznaru", "аграрный университет"]),
    31: ("АУЭС им. Даукеева", ["ауэс", "aues", "даукеев"]),
    30: ("Алматинский технологический университет", ["алматинский технологический"]),
    58: ("КазНАИ им. Жургенова", ["жургенов", "казнаи"]),
    60: ("Консерватория им. Курмангазы", ["консерватори", "курмангаз"]),
    70: ("КазНУИ (университет искусств)", ["казнуи", "университет искусств"]),
    73: ("КазУТБ им. Кулажанова", ["казутб", "кулажанов"]),
    97: ("Медицинский университет Астана", ["медицинский университет астана", "амu", "мua"]),
    104: ("AIU — Международный университет Астана", ["aiu", "международный университет астана"]),
    80: ("Казахстанско-Немецкий университет (DKU)", ["dku", "немецкий университет"]),
    115: ("ТарУ им. Дулати", ["дулати", "dulaty"]),
    125: ("Университет Шакарима", ["шакарим", "shakarim"]),
    40: ("ВКУ им. Аманжолова", ["аманжолов", "amanzholov"]),
    39: ("ВКТУ им. Серикбаева", ["серикбаев", "serikbayev"]),
    53: ("ЗКУ им. Утемисова", ["утемисов", "utemisov"]),
    112: ("СКУ им. Козыбаева", ["козыбаев", "kozybayev"]),
    92: ("КРУ им. Байтұрсынұлы", ["байтұрсын", "байтурсын", "baitursyn"]),
    90: ("КУ им. Уалиханова", ["уалиханов", "ualikhanov"]),
    96: ("КУ им. Коркыт Ата", ["коркыт", "korkyt"]),
    28: ("АРУ им. Жубанова", ["жубанов", "zhubanov"]),
    36: ("АУ им. Досмухамедова", ["досмухамедов", "dosmukhamedov"]),
    37: ("АУНГ им. Утебаева", ["утебаев", "университет нефти и газа"]),
    88: ("КУТИ им. Есенова", ["есенов", "yessenov"]),
    84: ("КарТУ им. Сагинова", ["сагинов", "картех", "картеху"]),
    83: ("Карагандинский медицинский университет", ["карагандинский медицинский", "кму"]),
    98: ("Медицинский университет Семей", ["медицинский университет семей"]),
    139: ("ЮКМА (медицинская академия)", ["юкма", "южно-казахстанская медицинская"]),
    52: ("ЗКМУ им. Оспанова", ["оспанов", "zkmu"]),
    2: ("Alikhan Bokeikhan University", ["бокейхан", "bokeikhan"]),
    20: ("Академия «Bolashaq»", ["bolashaq"]),
    95: ("Университет «Болашак» (Кызылорда)", ["болашак"]),
    49: ("ЖУ им. Жансугурова", ["жансугуров", "zhansugurov"]),
    48: ("ЖезУ им. Байконурова", ["байконуров"]),
    76: ("КМУ «ВШОЗ»", ["вшоз", "ksph"]),
    81: ("Казахстанско-Российский медицинский университет", ["казахстанско-российский медицинский", "крму"]),
    74: ("Казахско-Русский международный университет", ["казахско-русский международный"]),
    78: ("Казахстанско-Американский свободный университет", ["kafu", "казахстанско-американский"]),
    123: ("Университет дружбы народов им. Куатбекова", ["куатбеков", "дружбы народов"]),
    121: ("Университет «Мирас»", ["мирас", "miras"]),
    119: ("Университет «Сырдария»", ["сырдария", "syrdariya"]),
    122: ("Университет «Туран-Астана»", ["туран-астана", "turan-astana"]),
    129: ("Университет Кунаева", ["кунаев"]),
    130: ("Университет международного бизнеса (UIB)", ["uib", "международного бизнеса"]),
    99: ("Международная образовательная корпорация (МОК, КазГАСА)", ["казгаса", "мок ", "международная образовательная корпорация"]),
    100: ("Международный инженерно-технологический университет", ["миту", "инженерно-технологический университет"]),
    102: ("Международный транспортно-гуманитарный университет", ["транспортно-гуманитарный"]),
    106: ("Международный университет туризма и гостеприимства", ["университет туризма и гостеприимства"]),
    87: ("Каспийский университет", ["каспийский университет"]),
    24: ("Академия логистики и транспорта", ["логистики и транспорта", "алт "]),
    23: ("Академия гражданской авиации", ["академия гражданской авиации"]),
    56: ("Казахская академия спорта и туризма", ["академия спорта"]),
    25: ("Академия физической культуры и массового спорта", ["массового спорта"]),
    59: ("Академия хореографии", ["академия хореографии"]),
    8: ("Esil University", ["esil", "есиль", "есіл"]),
    38: ("Баишев Университет", ["баишев", "baishev"]),
    41: ("Гуманитарно-техническая академия (Кокшетау)", ["гуманитарно-техническая академия"]),
    46: ("Университет «Нур-Мубарак»", ["нур-мубарак", "мубарак"]),
    47: ("ЕИТИ им. Сатпаева (Экибастуз)", ["екибастузский"]),
    50: ("ЗКАТУ им. Жангир-хана", ["жангир"]),
    51: ("ЗКИТУ (Уральск)", ["западно-казахстанский инновационно"]),
    54: ("Инновационный Евразийский университет", ["инновационный евразийский"]),
    55: ("КазАДИ им. Гончарова", ["гончаров", "казади"]),
    82: ("Карагандинский индустриальный университет", ["карагандинский индустриальный"]),
    86: ("Карагандинский университет Казпотребсоюза", ["казпотребсоюз"]),
    89: ("Кокшетауский университет им. Мырзахметова", ["мырзахметов"]),
    91: ("КИнЭУ им. Дулатова", ["дулатов"]),
    93: ("КСТУ им. Алдамжара", ["алдамжар"]),
    108: ("Павлодарский педагогический университет", ["павлодарский педагогический"]),
    111: ("Рудненский индустриальный университет", ["рудненский"]),
    114: ("Таразский инновационно-гуманитарный университет", ["таразский инновационно"]),
    135: ("Центрально-Азиатский инновационный университет", ["центрально-азиатский инновационный"]),
    137: ("Центрально-Казахстанская академия", ["центрально-казахстанская"]),
    138: ("Шымкентский университет", ["шымкентский университет"]),
    140: ("ЮКПУ (педагогический, Шымкент)", ["южно-казахстанский педагогический", "юкпу"]),
    13: ("Kozybayev University + University of Arizona", ["university of arizona"]),
    14: ("NPU + КазНУ им. аль-Фараби", ["northwestern polytechnic"]),
    17: ("TIIAME + КазНАУ", ["tiiame"]),
    29: ("АГЭУ (гуманитарно-экономический, Алматы)", ["агэу", "алматинский гуманитарно-экономический"]),
    32: ("МИФИ (филиал в Алматы)", ["мифи", "mephi"]),
    34: ("Аркалыкский пединститут им. Алтынсарина", ["аркалыкский педагогический", "алтынсарин"]),
    43: ("ЕГИ им. Кусаинова", ["евразийский гуманитарный институт", "кусаинов"]),
    68: ("КазНУВХИ (водное хозяйство, Тараз)", ["университет водного хозяйства"]),
    77: ("КазУИТС (Уральск)", ["казуитс", "инновационных и телекоммуникационных"]),
}

# Вузы искусств: консерватория, академии искусств и хореографии, университет искусств.
ARTS = {58, 59, 60, 70}

# Вузы, по которым у бота уже есть подробные справки: из каталога берём только «предметы по курсам», цель, профессии.
EXISTING = {33: "almau", 44: "enu", 79: "kbtu", 131: "narxoz", 124: "sdu", 127: "mnu", 3: "aitu", 65: "satbayev",
            61: "kazatu"}

# Общеобразовательные дисциплины — в «траекторию по курсам» не попадают.
GENERAL = re.compile(
    r"иностранн|английск|казахск\w* (\(русск\w*\) )?язык|русск\w* язык|профессиональн\w* (казахск|русск)|"
    r"истори\w* казахстан|философ|физическ\w* культур|социолог|политолог|культуролог|абаевед|"
    r"экологи\w* и|безопасност\w* жизнедеят|охрана труда|антикорруп|финансов\w* грамот|"
    r"основы экономики|основы права|академическ\w* письм|информационно-коммуникац|\bикт\b|"
    r"модуль социально|основы искусственного интеллекта|итогов\w* аттестац|дипломн|"
    r"методы научных исследований|основы научных исследований|исследования, развитие и инновации|"
    r"предпринимательство$|психология$|^практика|практика$|учебная практика|производственная практика|"
    r"преддипломная|педагогическая практика|самопознани|основы антикор|учение абая|абаев|инклюзи|коррупци|"
    r"цифровая грамотность|казахстанский путь|рухани", re.I)

LAT2CYR = str.maketrans("aopecxyAOPECXHKMBT", "аоресхуАОРЕСХНКМВТ")
CYR2LAT = str.maketrans("аоресхуАОРЕСХНКМВТ", "aopecxyAOPECXHKMBT")


def fix_letters(text: str) -> str:
    """Слова, где смешаны латиница и кириллица-двойники: «Соmрutеr» → «Computer», «фopмиpoвaние» → «формирование».
    Если в слове есть латинские буквы без кириллических двойников (m, u, t…) — слово английское, иначе русское."""
    def one(m: re.Match) -> str:
        w = m.group(0)
        if not (re.search(r"[а-яё]", w, re.I) and re.search(r"[a-z]", w, re.I)):
            return w
        return w.translate(CYR2LAT) if re.search(r"[b-df-np-wzBDFGIJLNQRSUVWYZ]", w.translate(CYR2LAT).translate(str.maketrans("", "", "aopecxyAOPECXHKMBT"))) else w.translate(LAT2CYR)
    return re.sub(r"\w+", one, text)


def strip_uni(name: str) -> str:
    """«Геоинформатика в КазНУ им. аль-Фараби» → «Геоинформатика» (так названия записаны на univision.kz)."""
    head, sep, tail = name.rpartition(" в ")
    return head if sep and head and (tail[:1].isupper() or tail[:1] in "«\"'") else name


def _open(path: str):
    return (lzma.open if path.endswith(".xz") else gzip.open if path.endswith(".gz") else open)(path, "rt", encoding="utf-8")


def clean(text: str, limit: int) -> str:
    text = fix_letters(re.sub(r"\s+", " ", (text or "")).strip(" .,;"))
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def study_path(discs: list[dict]) -> tuple[dict, list[str]]:
    """Профильные предметы по курсам (до 5 на курс) и 8 ключевых предметов со 2-го курса."""
    by_year = collections.defaultdict(list)
    seen = set()
    for d in discs:
        name = clean(d.get("name", ""), 80)
        low = name.lower()
        if not name or low in seen or GENERAL.search(low):
            continue
        seen.add(low)
        try:
            credits = float(str(d.get("credits") or 0).replace(",", "."))
        except ValueError:
            credits = 0
        year = d.get("year") or ""
        by_year[year if year.isdigit() else ""].append((credits, name))
    path = {}
    for year in sorted(y for y in by_year if y):
        items = sorted(by_year[year], key=lambda x: -x[0])[:8]
        path[f"{year} курс"] = [n for _, n in items]
    key = [n for _, n in sorted((x for y, xs in by_year.items() if y not in ("", "1") for x in xs), key=lambda x: -x[0])][:8]
    if not path and by_year.get(""):
        key = [n for _, n in by_year[""][:8]]
    return path, key


def price(tuition: list[dict]) -> tuple[int | None, str]:
    for t in tuition or []:
        if t.get("currency") == "KZT" and str(t.get("amount", "")).isdigit():
            return int(t["amount"]), ""
    for t in tuition or []:
        if t.get("amount"):
            amount = f"{int(float(t['amount'])):,}".replace(",", " ") if re.fullmatch(r"[\d.]+", str(t["amount"])) else t["amount"]
            return None, f"{amount} {t.get('currency', '')}".strip()
    return None, ""


def grants(rows_path: str) -> tuple[dict, dict]:
    """Общий конкурс 2026: по (код вуза, группа) — число грантов и минимум; по группе — минимум по стране."""
    rows = pickle.load(open(rows_path, "rb"))
    by_uni, by_gop, names = collections.defaultdict(list), collections.defaultdict(list), {}
    for gop, contest, score, code in rows:
        if contest != "ОБЩИЙ КОНКУРС":
            continue
        g = gop.split()[0]
        names[g] = gop
        by_uni[(code, g)].append(score)
        by_gop[g].append(score)
    nat = {g: {"gop": names[g], "kz_min": min(v), "kz_count": len(v)} for g, v in by_gop.items()}
    return {k: {"count": len(v), "min": min(v)} for k, v in by_uni.items()}, nat


def main() -> None:
    src, rows_path = sys.argv[1], sys.argv[2]
    programs, unis = [], {}
    for f in sorted(glob.glob(f"{src}/pro4u_programs_full_part*")):
        d = json.load(_open(f))
        programs += d["programs"]
        unis.update({u["id"]: u for u in d["universities"]})
    discs = {}
    for f in sorted(glob.glob(f"{src}/pro4u_disciplines_part*")):
        discs.update(json.load(_open(f)))
    by_uni_grant, nat = grants(rows_path)

    bach = collections.defaultdict(list)
    for p in programs:
        if p.get("degree") == "Bachelor" and p.get("university_id"):
            bach[p["university_id"]].append(p)

    # Проход 1: программы каждого вуза (дубли из двух источников склеиваем).
    items = []
    for uid, plist in sorted(bach.items()):
        coded = any(p["code"] for p in plist)
        merged = {}
        for p in plist:
            if coded and not p["code"]:
                continue  # без кода — обычно дубль той же программы с английским названием (studyinkz)
            key = p["code"] or next((k for k, q in merged.items() if not q["code"] and
                                     (q.get("name") or "").strip().lower() == (p.get("name") or "").strip().lower()),
                                    f"x{p['id']}")  # одинаковые программы без кода — одна запись
            if key in merged:  # одна программа из двух источников — дополняем пустые поля
                old = merged[key]
                for k, v in p.items():
                    if not old.get(k) and v:
                        old[k] = v
                old["_ids"].append(p["id"])
                continue
            merged[key] = dict(p, _ids=[p["id"]])
        for key, p in merged.items():
            p["_name"] = strip_uni(clean(p.get("name") or p.get("name_en", ""), 150))
            items.append((uid, key, p))

    # Проход 2: восстанавливаем пустые «предметы ЕНТ» и «группу ГОП» по похожим программам —
    # только когда похожие программы почти единодушны (80%+), и с пометкой inferred.
    def name_key(p: dict) -> str:
        n = re.sub(r"\s*\(.*?\)", "", p["_name"].lower()).strip(" .«»\"")
        return NAME_TR.get(n, (n,))[0].lower()

    def majority(counter: collections.Counter, need: int) -> str:
        if not counter:
            return ""
        value, n = counter.most_common(1)[0]
        return value if n >= need and n / sum(counter.values()) >= 0.8 else ""

    gop_ent, dir_gop, name_gop, name_ent = (collections.defaultdict(collections.Counter) for _ in range(4))
    for _, key, p in items:
        if p.get("group"):
            if p.get("ent_subjects"):
                gop_ent[p["group"]][p["ent_subjects"]] += 1
            if p.get("code"):
                dir_gop[p["code"][:5]][p["group"]] += 1
            name_gop[name_key(p)][p["group"]] += 1
        if p.get("ent_subjects"):
            name_ent[name_key(p)][p["ent_subjects"]] += 1
    for uid, key, p in items:
        p["_inferred"] = []
        if not p.get("group"):
            g = (majority(dir_gop[p["code"][:5]], 3) if p.get("code") else "") or majority(name_gop[name_key(p)], 2)
            if g:
                p["group"] = g
                p["_inferred"].append("group")
        if not p.get("ent_subjects"):
            e = (majority(gop_ent[p["group"]], 3) if p.get("group") else "") or majority(name_ent[name_key(p)], 2)
            e = e or ("Творческий экзамен" if uid in ARTS else "")  # вузы искусств принимают по творческому экзамену
            if e:
                p["ent_subjects"] = e
                p["_inferred"].append("ent_subjects")

    # Проход 3: итоговые записи.
    progs_by_uni = collections.defaultdict(list)
    for uid, key, p in items:
        u = unis[uid]
        dl = next((discs[str(i)] for i in p["_ids"] if discs.get(str(i))), [])
        path, key_courses = study_path(dl)
        kzt, other = price(p.get("tuition"))
        gop = p["group"].split()[0] if p.get("group") else ""
        grant = None
        if gop and gop in nat:
            g = by_uni_grant.get((u.get("vuz_code"), gop), {})
            grant = {"gop": nat[gop]["gop"], "count": g.get("count", 0), "min": g.get("min"),
                     "kz_min": nat[gop]["kz_min"], "kz_count": nat[gop]["kz_count"]}
        urls = [s["url"] for s in p.get("sources", []) if s.get("url") and s.get("site") != "drive"]
        fmt = FORMAT.get((p.get("format") or "").strip(), "")
        progs_by_uni[uid].append({k: v for k, v in {
            "code": key, "name_ru": p["_name"],
            "section": p.get("group") or p.get("direction") or "", "ent_subjects": p.get("ent_subjects", ""),
            "area": p.get("area", ""), "direction": p.get("direction", ""),
            "price_kzt": kzt, "price_other": other, "duration": p.get("duration", ""),
            "credits": p.get("credits", ""), "languages": p.get("languages", ""), "format": fmt,
            "thesis": {"yes": "да", "no": "нет"}.get(p.get("thesis", ""), ""),
            "about": clean(p.get("goal", ""), 400),
            "careers": list(dict.fromkeys(clean(x, 90) for x in (p.get("professions") or [])))[:10],
            "outcomes": [clean(x, 250) for x in (p.get("learning_outcomes") or [])[:5]],
            "study_path": path, "key_courses": key_courses, "grant_2026": grant,
            "inferred": p["_inferred"], "url": urls[0] if urls else "", "in_registry": p.get("epvo") == "in_registry",
        }.items() if v not in (None, "", [], {})})

    out = []
    for uid in sorted(progs_by_uni):
        u = unis[uid]
        progs = progs_by_uni[uid]
        city = u.get("city") or CITY_FIX.get(uid, "")
        short, aliases = SHORT.get(uid, (None, []))
        name = u.get("name_ru") or u.get("name_en") or ""
        kind = (u.get("type") or "").split("|")[0].strip().lower()
        out.append({k: v for k, v in {
            "id": uid, "existing": EXISTING.get(uid), "vuz_code": u.get("vuz_code") if u.get("vuz_code") not in ("", "000") else "",
            "name_ru": name, "name_en": u.get("name_en") or ", ".join(u.get("studyinkz_names") or []),
            "short": short or (name if len(name) <= 48 else name[:46].rsplit(" ", 1)[0] + "…"),
            "aliases": aliases, "city": city, "region": u.get("region", ""),
            "type": {"частный": "частный", "государственный": "государственный", "акционированный": "акционерное общество",
                     "международный": "международный"}.get(kind, ""),
            "students": int(u["students"]) if str(u.get("students", "")).isdigit() else None,
            "rating": clean(u.get("rating", ""), 300),
            "website": (u.get("official_site") or "").replace("https:// ", "https://").strip(),
            "phones": [("+" + ph if re.match(r"7[ (]", ph) else ph) for ph in u.get("phones", [])[:3]], "emails": u.get("emails", [])[:2],
            "contacts_raw": "" if u.get("phones") else clean(u.get("contacts_raw", ""), 160), "programs": progs,
        }.items() if v not in (None, "", [])})
    meta = {"generated_from": "univision.kz, studyinkz.kz, реестр ОП epvo.kz (каталог Pro4U от 2026-10-19); "
                              "гранты — официальный список обладателей грантов 2026–2027, общий конкурс",
            "universities": len(out), "programs": sum(len(u["programs"]) for u in out)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump({"meta": meta, "universities": out}, f, ensure_ascii=False, separators=(",", ":"))
    print(meta, OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()
