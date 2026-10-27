# Собирает для бота итоги грантов 2025 и 2026 годов: общий конкурс, сельская квота, целевой госзаказ
# и все квоты (многодетные, неполные семьи, инвалидность, сироты, кандасы, отслужившие и др.).
# Боту эта программа не нужна — он читает готовый файл. Запускать, когда выйдет новый список грантов.
#
#   python tools/build_grants.py pro4u_grants_by_vuz_group.json
#   python tools/build_grants.py pro4u_grants_2025_general_rural.json pro4u_grants_quotas_2025_2026.json [общий 2026.json]
#
# Вход — одна или несколько таблиц «вуз × группа программ» без ФИО (строки: year, list, competition, study_form, note,
# region, group_code, group_name, university_id, grants, score_min, pct_min …); одинаковые строки из разных файлов
# считаются один раз. Результат: knowledge/catalog/grants.json.gz
#   unis[вуз][группа][год][категория] = [грантов, мин. балл или null] (+ мин. процент, если в списке процент, а не балл)
#   country[группа][год][категория]   = то же по всей стране; country[группа]["name"] — название группы.
import collections
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "knowledge" / "catalog" / "grants.json.gz"
CATALOG = ROOT / "knowledge" / "catalog" / "kz_bachelor.json.gz"

# Списки, где вместо балла ЕНТ стоит процент или балла нет совсем, — показываем только число грантов.
NO_SCORE = {"oralman", "military_service", "children_of_security_staff", "olympiad"}
WEST = {"МАНГИСТАУСКАЯ": "west_mangystau", "АТЫРАУСКАЯ": "west_atyrau"}


def num(x):
    """Число из таблицы: в JSON-файлах числа бывают строками («98», «94.5»), пустое — None."""
    if x in (None, ""):
        return None
    f = float(x)
    return int(f) if f.is_integer() else f


def category(r: dict) -> str:
    """Категория гранта: g — общий конкурс, r — сельская квота, s — сокращённая форма (после колледжа),
    ped/tech — целевой госзаказ на педагогические и технические/с-х группы (+ _r — его сельская квота),
    west_* — молодёжь западных регионов, health — госзаказ Минздрава, abroad — филиалы иностранных вузов и др.,
    остальное — квоты по названию списка."""
    lst, rural = r["list"], r["competition"] == "rural_quota"
    if lst == "general":
        if "СОКРАЩЕННАЯ" in r["study_form"]:
            return "s"
        return "r" if rural else "g"
    if lst == "state_order_health":
        return "health_r" if rural else "health"
    if lst == "state_order_other":
        note = r["note"].lower()
        if r["region"] in WEST:
            return WEST[r["region"]]
        if "педагогическ" in note:
            return "ped_r" if rural else "ped"
        if "техническ" in note:
            return "tech_r" if rural else "tech"
        return "abroad"
    return lst


def main() -> None:
    rows, seen = [], set()
    for path in sys.argv[1:]:
        for r in json.load(open(path, encoding="utf-8")):
            key = tuple(str(r.get(k) or "") for k in ("year", "list", "competition", "study_form", "note", "region",
                                                          "group_code", "vuz_code", "university_id"))
            if key not in seen:
                seen.add(key)
                rows.append(r)
    with gzip.open(CATALOG, "rt", encoding="utf-8") as f:
        slug_of = {u["id"]: u.get("existing") or f"u{u['id']}" for u in json.load(f)["universities"]}
    acc = collections.defaultdict(lambda: [0, None, None])
    names, skipped = {}, collections.Counter()
    for r in rows:
        gop, year, cat = r["group_code"], str(r["year"]), category(r)
        if not gop:  # строки без группы программ (в исходном PDF не распознана) — пропускаем
            skipped["без группы"] += num(r["grants"]) or 0
            continue
        names.setdefault(gop, r["group_name"])
        score = None if r["list"] in NO_SCORE else num(r.get("score_min"))
        # В списке кандасов вместо балла — процент от максимального балла ЕНТ.
        pct = num(r.get("pct_min")) if r["list"] in NO_SCORE else None
        keys = [("country", gop, year, cat)]
        slug = slug_of.get(num(r.get("university_id")))
        if slug:
            keys.append((slug, gop, year, cat))
        else:
            skipped[r.get("vuz_name") or r.get("vuz_code")] += num(r["grants"]) or 0
        for k in keys:
            a = acc[k]
            a[0] += num(r["grants"]) or 0
            if score is not None:
                a[1] = score if a[1] is None else min(a[1], score)
            if pct is not None:
                a[2] = pct if a[2] is None else min(a[2], pct)
    unis, country = {}, {}
    for (who, gop, year, cat), v in sorted(acc.items()):
        v = v if v[2] is not None else v[:2]
        if who == "country":
            country.setdefault(gop, {"name": names[gop]}).setdefault(year, {})[cat] = v
        else:
            unis.setdefault(who, {}).setdefault(gop, {}).setdefault(year, {})[cat] = v
    data = {"meta": {"years": [2025, 2026], "built_from": [Path(p).name for p in sys.argv[1:]],
                     "note": "Гранты дают на группу программ (ГОП). Мин. балл — самый низкий балл среди получивших "
                             "грант (не официальный порог). ФИО и ИИН не хранятся."},
            "unis": unis, "country": country}
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{OUT.name}: вузов {len(unis)}, групп {len(country)}, {OUT.stat().st_size // 1024} КБ")
    if skipped:
        print("Вузов нет в каталоге (их гранты учтены только в цифрах по стране):", dict(skipped.most_common(5)))


if __name__ == "__main__":
    main()
