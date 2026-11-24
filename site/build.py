#!/usr/bin/env python3
"""Сборка статического сайта Pro4U: python site/build.py [--base /pro4u] [--out site/dist]"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
for k in ("TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY"):
    os.environ.setdefault(k, "build")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pro4u_site_"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import universities as U  # noqa: E402
import grants  # noqa: E402
from templates import (fav_button, esc, text, paras, ul, plural, fmt_date, fmt_price, trunc, ext_link, tg_button,  # noqa: E402
                       crumbs, important, page, clean, is_agg)

WARNINGS: list[str] = []
GOP_RE = re.compile(r"^[A-Z]\d{3}\b")
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


def warn(msg):
    WARNINGS.append(msg)


def pid(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", code).lower()


def gop_of(p: dict) -> str:
    g = (p.get("grant_2026") or {}).get("gop") or ""
    if g:
        return g.split()[0]
    sec = p.get("section") or ""
    return sec[:4] if GOP_RE.match(sec) else ""


_SEC_NAMES: dict[str, str] = {}


def gop_name(gop: str) -> str:
    """Название группы: из файла грантов, а если там нет — из поля section программ («B086 Медицина» -> «Медицина»)."""
    if not gop:
        return ""
    n = grants.gop_name(gop)
    if n:
        return n
    if not _SEC_NAMES:
        for u in U.UNIS.values():
            for p in u["programs"].values():
                sec = (p.get("section") or "").strip()
                if GOP_RE.match(sec) and sec[4:].strip():
                    _SEC_NAMES.setdefault(sec[:4], sec[4:].strip())
        _SEC_NAMES["_"] = ""
    return _SEC_NAMES.get(gop, "")


def ent_of(p: dict) -> str:
    e = p.get("ent_subjects") or ""
    return "" if is_agg(e) else e


def open_programs(u: dict) -> list[dict]:
    return sorted((p for p in u["programs"].values() if p.get("open")), key=lambda p: (p["name_ru"].casefold(), p["code"]))


def score_text(v) -> str:
    if v[1] is not None:
        return str(v[1])
    if len(v) > 2 and v[2] is not None:
        return grants.pct_text(v[2], "ru")  # «от 46,4% от максимального балла» — как в боте
    return "балл в списке не указан"


def grants_table(data: dict, year: str, caption: str) -> str:
    cats = (data or {}).get(year) or {}
    rows = sorted(((c, v) for c, v in cats.items() if v and v[0]), key=lambda x: (-x[1][0], grants.label(x[0])))
    if not rows:
        return f"<h4>{esc(caption)}</h4><p class='muted'>В списках {esc(year)} года данных нет.</p>"
    body = "".join(f"<tr><td>{esc(grants.label(c))}</td><td class='num'>{v[0]}</td><td>{esc(score_text(v))}</td></tr>"
                   for c, v in rows)
    return (f"<h4>{esc(caption)}</h4><div class='tbl'><table><thead><tr><th>Категория</th><th>Грантов</th>"
            f"<th>Мин. балл</th></tr></thead><tbody>{body}</tbody></table></div>")


GRANT_CAPTION = ("<p class='small muted'>Мин. балл — самый низкий балл среди получивших грант, "
                 "не официальный порог.</p>")


def country_block(gop: str) -> str:
    c = grants.country(gop)
    rows = []
    for year in ("2026", "2025"):
        for cat, name in (("g", "Общий конкурс"), ("r", "Сельская квота")):
            v = (c.get(year) or {}).get(cat)
            if v and v[0]:
                rows.append(f"<tr><td>{esc(name)}</td><td>{year}</td><td class='num'>{v[0]}</td>"
                            f"<td>{esc(score_text(v))}</td></tr>")
    if not rows:
        return ""
    return ("<h4>По стране (все вузы)</h4><div class='tbl'><table><thead><tr><th>Конкурс</th><th>Год</th>"
            "<th>Грантов</th><th>Мин. балл</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def dl(rows) -> str:
    rows = [(k, v) for k, v in rows if v]
    return "<dl class='facts'>" + "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>" if rows else ""


def uni_titles(u: dict) -> str:
    h = f"<h1>{esc(u['short'])}</h1>"
    name = u["name_ru"]
    sub = f"<p class='lead'>{esc(name)}"
    kz = u.get("name_kz")
    if kz and kz != name and kz != u["short"]:
        sub += f"<br><span class='muted'>{esc(kz)}</span>"
    return h + sub + "</p>"


def contacts_html(u: dict) -> str:
    a = u.get("admissions") or {}
    parts = []
    if a.get("phones"):
        parts.append("Телефон: " + ", ".join(text(p) for p in a["phones"]))
    em = (a.get("email") or "").strip()
    if em:
        parts.append("Эл. почта: " + (f'<a href="mailto:{esc(em)}">{esc(em)}</a>' if EMAIL_RE.match(em) else text(em)))
    if a.get("address"):
        parts.append("Адрес: " + text(a["address"]))
    if a.get("hours"):
        parts.append("Часы работы: " + text(a["hours"]))
    if a.get("url"):
        parts.append("Страница приёмной комиссии: " + ext_link(a["url"]))
    return "<br>".join(parts)


def special_block(u: dict) -> str:
    s = u.get("admission_special")
    if not s:
        return ""
    out = ["<section class='card'><h2>Особый порядок поступления</h2>"]
    if s.get("summary"):
        out.append(paras(s["summary"]))
    rows = []
    if s.get("exam_name"):
        rows.append(("Экзамен", text(s["exam_name"])))
    if s.get("ent_required") is not None and s.get("ent_required") != "":
        v = s["ent_required"]
        word = ("да" if v else "нет") if isinstance(v, bool) else str(v)
        rows.append(("Нужен ли ЕНТ", text(word) + (" — " + text(s["ent_note"]) if s.get("ent_note") else "")))
    elif s.get("ent_note"):
        rows.append(("ЕНТ", text(s["ent_note"])))
    for key, label in (("eligibility", "Кто может поступать"), ("deadlines", "Сроки"), ("grants", "Гранты"),
                       ("diploma", "Диплом")):
        if s.get(key):
            rows.append((label, text(s[key])))
    if s.get("documents"):
        rows.append(("Документы", ul(s["documents"])))
    out.append(dl(rows))
    out.append("</section>")
    return "".join(out)


def uni_page(base: str, u: dict, progs: list[dict]) -> str:
    slug = u["slug"]
    n = len(progs)
    checked = (u.get("admission_special") or {}).get("checked_on") or u.get("checked_on")
    desc = (f"{u['short']}: программы, гранты, поступление. {u['city']}, "
            f"{n} {plural(n, 'программа', 'программы', 'программ')} бакалавриата.")
    facts = dl([
        ("Город", text(u["city"] + (f", {u['region']}" if u.get("region") and u["region"] != u["city"] else ""))),
        ("Тип", text(u.get("type"))),
        ("Официальный сайт", ext_link(u["website"]) if u.get("website") else ""),
        ("Приёмная комиссия", contacts_html(u)),
        ("Список программ на сайте вуза", ext_link(u["programs_url"]) if u.get("programs_url") else ""),
    ])
    body = [crumbs(base, [(u["short"], None)]), uni_titles(u), fav_button("university", slug),
            f"<section class='card'>{facts}</section>", important(checked)]
    if u.get("notes"):
        body.append(f"<section class='card'><h2>О вузе</h2>{paras(u['notes'])}</section>")
    body.append(special_block(u))
    if u.get("price_note"):
        body.append(f"<section class='card'><h2>Стоимость</h2>{paras(u['price_note'])}</section>")
    if u.get("dorm"):
        body.append(f"<section class='card'><h2>Общежитие</h2>{paras(u['dorm'])}</section>")
    # программы по группам
    groups: dict[str, list[dict]] = {}
    for p in progs:
        groups.setdefault(p.get("section") or "Без группы", []).append(p)
    body.append(f"<section><h2>Программы бакалавриата ({n})</h2>")
    if not progs:
        body.append("<p class='muted'>Открытых программ в справке нет — уточняйте в приёмной комиссии.</p>")
    for sec in sorted(groups, key=str.casefold):
        body.append(f"<details class='grp' open><summary>{esc(sec)} <span class='muted'>({len(groups[sec])})</span></summary><ul class='plist'>")
        for p in groups[sec]:
            tag = " <span class='badge'>набор уточняйте</span>" if p.get("not_in_reference") else ""
            body.append(f"<li><a href=\"{esc(base)}/vuz/{esc(slug)}/{pid(p['code'])}/\">{esc(p['name_ru'])}</a> "
                        f"<span class='muted'>{esc(p['code'])}</span>{tag}</li>")
        body.append("</ul></details>")
    body.append("</section>")
    # гранты по группам
    rows = []
    seen = {}
    for p in progs:
        g = gop_of(p)
        if g and g not in seen:
            seen[g] = p
    for g in sorted(seen):
        v = (grants.uni(slug, g).get("2026") or {}).get("g")
        if v and v[0]:
            rows.append(f"<tr><td>{esc(g)} {esc(gop_name(g))}</td><td class='num'>{v[0]}</td>"
                        f"<td>{esc(score_text(v))}</td></tr>")
    if rows:
        body.append("<section class='card'><h2>Гранты по группам 2026</h2><p class='small muted'>Общий конкурс "
                    "в этом вузе.</p><div class='tbl'><table><thead><tr><th>Группа программ</th><th>Грантов</th>"
                    "<th>Мин. балл</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
                    + GRANT_CAPTION + "</section>")
    body.append(f"<p>{tg_button()}</p>")
    return page(base, f"{u['short']}: программы, гранты, поступление", desc, "\n".join(b for b in body if b))


def program_page(base: str, u: dict, p: dict) -> str:
    slug = u["slug"]
    gop = gop_of(p)
    gname = gop_name(gop)
    ent = ent_of(p)
    desc = (f"{p['name_ru']} — {u['short']}. Предметы ЕНТ: {ent or 'уточняйте'}. "
            f"Группа: {(gop + ' ' + gname).strip() if gop else (p.get('section') or '—')}.")
    checked = (u.get("admission_special") or {}).get("checked_on") or u.get("checked_on")
    uni_url = f"{base}/vuz/{slug}/"
    body = [crumbs(base, [(u["short"], uni_url), (p["name_ru"], None)]),
            f"<h1>{esc(p['name_ru'])}</h1><p class='lead'><a href=\"{esc(uni_url)}\">{esc(u['name_ru'])}</a>, "
            f"{esc(u['city'])}</p>", fav_button("program", f"{slug}/{pid(p['code'])}")]
    if p.get("not_in_reference"):
        body.append("<p class='card warn'>Программа есть в реестре, но нет в справке вуза — набор уточняйте "
                    "в приёмной.</p>")
    price = (fmt_price(p["price_kzt"]) if p.get("price_kzt")
             else ("цена не указана — уточняйте в приёмной"))
    if p.get("price_other"):
        price += f" ({clean(p['price_other'])})"
    rows = [("Код программы", esc(p["code"])),
            ("Группа программ", esc(((gop + " " + gname).strip()) if gop else (p.get("section") or ""))),
            ("Предметы ЕНТ", text(ent) + (f"<br><span class='muted'>{text(p['ent_note'])}</span>" if p.get("ent_note") else "")),
            ("Срок обучения", text(p.get("duration"))), ("Язык обучения", text(p.get("languages"))),
            ("Формат", text(p.get("format"))),
            ("Стоимость", text(price)),
            ("Страница на сайте вуза", ext_link(p["url"]) if p.get("url") else "")]
    body.append(f"<section class='card'>{dl(rows)}</section>")
    body.append(important(checked))
    for key, title in (("about", "О программе"),):
        if p.get(key):
            body.append(f"<section class='card'><h2>{title}</h2>{paras(p[key])}</section>")
    for key, title in (("tracks", "Траектории"), ("key_courses", "Ключевые дисциплины"),
                       ("careers", "Кем работать"), ("workplaces", "Где работать"),
                       ("outcomes", "Результаты обучения")):
        v = p.get(key)
        if isinstance(v, str):
            v = [v]
        if v:
            body.append(f"<section class='card'><h2>{title}</h2>{ul(v)}</section>")
    # гранты
    if gop:
        ug = grants.uni(slug, gop)
        cn = grants.country(gop)
        if ug or cn:
            g = [f"<section class='card'><h2>Гранты по группе {esc(gop)}" + (f" «{esc(gname)}»" if gname else "")
                 + "</h2><p class='small muted'>Гранты даются на группу программ, а не на отдельную программу.</p>"]
            g.append(grants_table(ug, "2026", f"2026, в этом вузе ({u['short']})"))
            g.append(grants_table(ug, "2025", f"2025, в этом вузе ({u['short']})"))
            g.append(country_block(gop))
            g.append(GRANT_CAPTION + "</section>")
            body.append("".join(g))
    body.append(f"<p>{tg_button()}</p>")
    return page(base, f"{p['name_ru']} — {u['short']}", desc, "\n".join(b for b in body if b))


def home_page(base: str, unis: list[dict], n_prog: int) -> str:
    items = "".join(
        f"<li><a href=\"{esc(base)}/vuz/{esc(u['slug'])}/\">{esc(u['short'])}</a> <span class='muted'>"
        f"{esc(u['city'])} · {len(open_programs(u))}</span></li>" for u in unis)
    body = (f"<h1>Вузы Казахстана: программы, гранты, поступление</h1>"
            f"<p class='lead'>{len(unis)} вузов и {n_prog} программ бакалавриата. Данные из справок вузов и "
            f"официальных списков грантов МНВО РК. Вузы показаны на равных, по алфавиту.</p>"
            f"<div id=\"search-root\"></div>"
            f"<section id='static-list'><h2>Все вузы по алфавиту</h2><ul class='ulist'>{items}</ul></section>"
            f"<p>{tg_button()}</p>")
    head = (f'<link rel="stylesheet" href="{esc(base)}/static/search.css">\n')
    end = f'<script src="{esc(base)}/static/search.js" defer></script>\n'
    return page(base, "Pro4U — вузы Казахстана: программы, гранты, поступление",
                f"Справочник по {len(unis)} вузам Казахстана: программы бакалавриата, предметы ЕНТ, гранты, правила приёма.",
                body, head_extra=head, body_end=end)


def special_page(base: str, unis: list[dict]) -> str:
    sp = [u for u in unis if u.get("admission_special")]
    items = []
    for u in sp:
        s = u["admission_special"]
        sm = trunc(clean(s.get("summary") or ""), 220)
        items.append(f"<li class='card'><a href=\"{esc(base)}/vuz/{esc(u['slug'])}/\"><strong>{esc(u['short'])}</strong></a> "
                     f"<span class='muted'>{esc(u['city'])}</span><br>{esc(sm)}</li>")
    body = [crumbs(base, [("Особый приём", None)]), "<h1>Особый порядок поступления</h1>",
            "<p class='lead'>Вузы, где приём идёт не только по ЕНТ или со своими экзаменами и условиями. "
            f"Всего: {len(sp)}. Список по алфавиту.</p>", important(), "<ul class='cards'>" + "".join(items) + "</ul>",
            f"<p>{tg_button()}</p>"]
    return page(base, "Особый порядок поступления в вузы Казахстана",
                f"{len(sp)} вузов с собственными экзаменами и особыми условиями приёма: список по алфавиту.", "\n".join(body))


def about_page(base: str, n_u: int, n_p: int) -> str:
    body = f"""{crumbs(base, [("О проекте", None)])}
<h1>О проекте</h1>
<section class="card"><h2>Что это</h2>
<p>Pro4U — независимый справочник для абитуриентов Казахстана и одноимённый Telegram-бот. На сайте собраны {n_u} вузов
и {n_p} программ бакалавриата: предметы ЕНТ, описание программ, стоимость, правила приёма и госгранты.</p></section>
<section class="card"><h2>Откуда данные</h2>
<p>Информация взята из справок самих вузов и официальных списков грантов Министерства науки и высшего образования РК.
Для каждого вуза указана дата проверки, если она известна. Ссылки на сайте ведут только на официальные сайты вузов.</p></section>
<section class="card"><h2>Уточняйте в приёмной</h2>
<p>Правила приёма меняются каждый год. Сроки, цены, документы и проходные баллы обязательно проверяйте в приёмной
комиссии вуза. «Мин. балл» по грантам — самый низкий балл среди получивших грант в прошлых списках, а не официальный
порог и не прогноз.</p></section>
<section class="card"><h2>Независимость</h2>
<p>Проект ведёт автор бота, а не университет. Все вузы показаны на равных и по алфавиту: без рейтингов, оценок и
рекомендаций «лучший — худший». Решение остаётся за вами и вашей семьёй.</p></section>
<section class="card"><h2>Бот в Telegram</h2>
<p>Бот поможет подобрать специальность, посчитать шансы на грант и напомнит о сроках ЕНТ.</p><p>{tg_button()}</p></section>"""
    return page(base, "О проекте Pro4U", "Pro4U — независимый справочник по вузам Казахстана: откуда данные, "
                "почему важно уточнять в приёмной, как мы относимся ко всем вузам одинаково.", body)


def moe_page(base: str) -> str:
    """Избранное: список подгружает auth.js для человека, вошедшего через Telegram."""
    body = [crumbs(base, [("Избранное", None)]), "<h1>Избранное</h1>",
            f'<div id="fav-root" data-base="{esc(base)}">'
            '<p id="fav-status" class="muted">Загрузка…</p><ul id="fav-list" class="plist"></ul>'
            '<section id="fav-guest" class="card note" hidden><p>Избранное доступно, когда сайт открыт из Telegram-бота: '
            'так сайт узнаёт вас без пароля. Откройте бота и нажмите кнопку «🌐 Сайт» рядом с полем ввода.</p>'
            f"<p>{tg_button()}</p></section></div>"]
    return page(base, "Избранное — Pro4U", "Избранные вузы и программы: личная страница в Telegram-боте Pro4U.",
                "\n".join(body))


def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="")
    ap.add_argument("--out", default=str(HERE / "dist"))
    a = ap.parse_args()
    base = a.base.rstrip("/")
    out = Path(a.out)
    t0 = time.time()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    unis = sorted(U.UNIS.values(), key=lambda u: (u["short"].casefold(), u["slug"]))
    count = 0
    index = []
    n_prog = 0
    no_ent: list[str] = []
    for u in unis:
        progs = open_programs(u)
        n_prog += len(progs)
    write(out / "index.html", home_page(base, unis, n_prog)); count += 1
    for u in unis:
        progs = open_programs(u)
        write(out / "vuz" / u["slug"] / "index.html", uni_page(base, u, progs)); count += 1
        seen = {}
        entry = {"slug": u["slug"], "short": u["short"], "name": u["name_ru"], "city": u["city"],
                 "type": u.get("type") or "", "special": bool(u.get("admission_special")),
                 "url": f"vuz/{u['slug']}/", "programs": []}
        for p in progs:
            k = pid(p["code"])
            if k in seen:
                warn(f"{u['slug']}: pid {k} повторяется ({seen[k]} / {p['code']})")
                continue
            seen[k] = p["code"]
            write(out / "vuz" / u["slug"] / k / "index.html", program_page(base, u, p)); count += 1
            gop = gop_of(p)
            entry["programs"].append({"name": p["name_ru"], "code": p["code"], "url": f"vuz/{u['slug']}/{k}/",
                                      "ent": ent_of(p), "gop": gop,
                                      "gop_name": gop_name(gop),
                                      "price": p.get("price_kzt") or None})
            if not ent_of(p):
                no_ent.append(f"{u['slug']}:{p['code']}")
        index.append(entry)
    if no_ent:
        warn(f"{len(no_ent)} программ без ent_subjects (у вузов-филиалов; строка ЕНТ скрыта), например {no_ent[:3]}")
    write(out / "osobyi-priem" / "index.html", special_page(base, unis)); count += 1
    write(out / "o-proekte" / "index.html", about_page(base, len(unis), n_prog)); count += 1
    write(out / "moe" / "index.html", moe_page(base)); count += 1
    write(out / "data" / "index.json",
          json.dumps({"generated": date.today().isoformat(), "unis": index}, ensure_ascii=False, separators=(",", ":")))
    st = HERE / "static"
    if st.exists():
        shutil.copytree(st, out / "static")
    for need in ("style.css", "search.js", "search.css"):
        if not (out / "static" / need).exists():
            warn(f"нет static/{need}")
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"Страниц HTML: {count} (вузов {len(unis)}, программ {n_prog}); размер {size/1e6:.1f} МБ; "
          f"индекс {(out/'data'/'index.json').stat().st_size/1e6:.2f} МБ; {time.time()-t0:.1f} с; "
          f"предупреждений: {len(WARNINGS)}")
    for w in WARNINGS[:50]:
        print("  warning:", w)


if __name__ == "__main__":
    main()
