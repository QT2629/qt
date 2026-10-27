# Собирает для бота итоги грантов 2025 и 2026 годов: общий конкурс, сельская квота, целевой госзаказ
# и все квоты (многодетные, неполные семьи, инвалидность, сироты, кандасы, отслужившие и др.).
# Боту эта программа не нужна — он читает готовый файл. Запускать, когда выйдет новый список грантов.
#
#   python tools/build_grants.py pro4u_grants_by_vuz_group.json
#
# Вход — таблица «вуз × группа программ» без ФИО (строки: year, list, competition, study_form, note, region,
# group_code, group_name, university_id, grants, score_min …). Результат: knowledge/catalog/grants.json.gz
#   unis[вуз][группа][год][категория] = [грантов, мин. балл или null]
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
    rows = json.load(open(sys.argv[1], encoding="utf-8"))
    with gzip.open(CATALOG, "rt", encoding="utf-8") as f:
        slug_of = {u["id"]: u.get("existing") or f"u{u['id']}" for u in json.load(f)["universities"]}
    acc = collections.defaultdict(lambda: [0, None])
    names, skipped = {}, collections.Counter()
    for r in rows:
        gop, year, cat = r["group_code"], str(r["year"]), category(r)
        if not gop:  # строки без группы программ (в исходном PDF не распознана) — пропускаем
            skipped["без группы"] += r["grants"]
            continue
        names.setdefault(gop, r["group_name"])
        score = None if r["list"] in NO_SCORE else r.get("score_min")
        keys = [("country", gop, year, cat)]
        slug = slug_of.get(r.get("university_id"))
        if slug:
            keys.append((slug, gop, year, cat))
        else:
            skipped[r.get("vuz_name") or r.get("vuz_code")] += r["grants"]
        for k in keys:
            a = acc[k]
            a[0] += r["grants"]
            if score is not None:
                a[1] = score if a[1] is None else min(a[1], score)
    unis, country = {}, {}
    for (who, gop, year, cat), v in sorted(acc.items()):
        if who == "country":
            country.setdefault(gop, {"name": names[gop]}).setdefault(year, {})[cat] = v
        else:
            unis.setdefault(who, {}).setdefault(gop, {}).setdefault(year, {})[cat] = v
    data = {"meta": {"years": [2025, 2026], "built_from": Path(sys.argv[1]).name,
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
