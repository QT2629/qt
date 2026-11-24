#!/usr/bin/env python3
"""Проверки собранного сайта Pro4U (site/dist). Техзадание: site/SPEC.md, раздел «Проверки».

Запуск (после python site/build.py):
    /Users/rahmatullinaalua/qt/.venv/bin/python site/check_site.py [--dist site/dist] [--base ""]

Код выхода: 0 — ошибок нет; 1 — есть ошибки; 2 — папка сборки не найдена.
Только стандартная библиотека Python 3.12+.
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import posixpath
import random
import re
import shutil
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

SITE_DIR = Path(__file__).resolve().parent
ROOT = SITE_DIR.parent  # корень репозитория бота
DEFAULT_DIST = SITE_DIR / "dist"

CHECK_TITLES = {
    1: "страницы вузов и программ",
    2: "внутренние ссылки",
    3: "внешние домены",
    4: "запрещённые слова",
    5: "числа грантов на страницах программ",
    6: "каркас страниц",
    7: "data/index.json",
}
EXTRA_EXTERNAL_HOSTS = {"t.me"}
FORBIDDEN_WORDS = ["univision", "studyinkz", "epvo", "bilim.expert", "vuzopedia", "лучший вуз"]
SAMPLE_SIZE = 50
SAMPLE_SEED = 42
MAX_PRINT = 30
DESCRIPTION_MAX = 160
DOCTYPE_RE = re.compile(r"\s*<!doctype html\s*>", re.IGNORECASE)
GOP_RE = re.compile(r"[A-Za-z]\d{3}")
# «1006», «1 006», «1 006» — первое число в строке
INT_RE = re.compile(r"\d{1,3}(?:[\s  ]\d{3})+(?!\d)|\d+")
LINK_ATTRS = ("href", "src")


# ---------------------------------------------------------------- данные бота

def load_bot_data():
    """Данные бота — так же, как в ТЗ: переменные окружения по умолчанию, путь к репозиторию, импорт модулей."""
    for k in ("TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY"):
        os.environ.setdefault(k, "build")
    if "DATA_DIR" not in os.environ:
        tmp = tempfile.mkdtemp(prefix="pro4u-check-")
        atexit.register(shutil.rmtree, tmp, True)
        os.environ["DATA_DIR"] = tmp
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import universities as U
    import grants
    return U, grants


def make_pid(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", code).lower()


def program_page(slug: str, code: str) -> str:
    return f"vuz/{slug}/{make_pid(code)}/index.html"


def uni_page(slug: str) -> str:
    return f"vuz/{slug}/index.html"


def host_of(url: str) -> str:
    s = url.strip()
    if s.startswith("//"):
        s = "https:" + s
    elif "://" not in s:
        s = "https://" + s
    try:
        host = (urlsplit(s).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def allowed_hosts(U) -> set[str]:
    hosts = set(EXTRA_EXTERNAL_HOSTS)
    urls: list[str] = []
    for u in U.UNIS.values():
        urls += [u.get("website"), (u.get("admissions") or {}).get("url"), u.get("programs_url")]
        urls += [p.get("url") for p in (u.get("programs") or {}).values()]
    for url in urls:
        if url:
            h = host_of(url)
            if h:
                hosts.add(h)
    return hosts


# ---------------------------------------------------------------- разбор HTML

def norm(text: str) -> str:
    return " ".join(text.split())


class PageParser(HTMLParser):
    """Собирает href/src, title, meta description, lang у html и таблицы (строки ячеек + контекст)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str, str]] = []  # (тег, атрибут, значение)
        self.title = ""
        self._in_title = False
        self.description: str | None = None
        self.lang: str | None = None
        self.tables: list[dict] = []  # {"context", "caption", "header", "rows"}
        self._open_tables: list[dict] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._text = ""  # текст вне таблиц — контекст для следующей таблицы
        self._skip = 0  # внутри script/style

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "title":
            self._in_title = True
        elif tag == "meta" and (a.get("name") or "").strip().lower() == "description":
            self.description = a.get("content") or ""
        for attr in LINK_ATTRS:
            if attr in a:
                self.links.append((tag, attr, a[attr] or ""))
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "table":
            self._open_tables.append({"context": norm(self._text)[-400:], "caption": "", "header": "", "rows": []})
            self._text = ""
            self._row = None
            self._cell = None
        elif tag == "tr" and self._open_tables:
            self._row = []
        elif tag in ("td", "th") and self._open_tables:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th"):
            if self._cell is not None and self._row is not None:
                self._row.append(norm("".join(self._cell)))
            self._cell = None
        elif tag == "tr":
            if self._row is not None and self._open_tables:
                self._open_tables[-1]["rows"].append(self._row)
            self._row = None
        elif tag == "table" and self._open_tables:
            t = self._open_tables.pop()
            if t["rows"]:
                t["header"] = " | ".join(t["rows"][0])
            self.tables.append(t)
            self._text = ""
            self._row = None
            self._cell = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._skip:
            return
        if self._open_tables:
            if self._cell is not None:
                self._cell.append(data)
            else:
                self._open_tables[-1]["caption"] += data
        else:
            self._text = (self._text + " " + data)[-2000:]


def parse_page(path: Path) -> tuple[str, PageParser]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    parser = PageParser()
    parser.feed(raw)
    parser.close()
    return raw, parser


# ---------------------------------------------------------------- отчёт

class Report:
    def __init__(self):
        self.errors: dict[int, list[str]] = {n: [] for n in CHECK_TITLES}
        self.warnings: dict[int, list[str]] = {n: [] for n in CHECK_TITLES}
        self.stats: dict[int, str] = {n: "" for n in CHECK_TITLES}

    def error(self, n: int, msg: str) -> None:
        self.errors[n].append(msg)

    def warn(self, n: int, msg: str) -> None:
        self.warnings[n].append(msg)

    def total_errors(self) -> int:
        return sum(len(v) for v in self.errors.values())

    def total_warnings(self) -> int:
        return sum(len(v) for v in self.warnings.values())


# ---------------------------------------------------------------- проверки

def check_1_pages(report, U, pages):
    """Для каждого вуза и каждой open-программы есть страница."""
    n_progs = 0
    for slug in sorted(U.UNIS):
        uni = U.UNIS[slug]
        if uni_page(slug) not in pages:
            report.error(1, f"нет страницы вуза: {uni_page(slug)}")
        for code, prog in (uni.get("programs") or {}).items():
            if not prog.get("open"):
                continue
            n_progs += 1
            rel = program_page(slug, code)
            if rel not in pages:
                report.error(1, f"нет страницы программы: {rel} (код {code}, вуз {slug})")
    report.stats[1] = f"вузов {len(U.UNIS)}, открытых программ {n_progs}"


def resolve_internal(page_rel: str, ref: str, base: str, dist: Path) -> str | None:
    """Вернёт текст ошибки или None, если внутренняя ссылка ведёт на существующий файл."""
    path = unquote(urlsplit(ref).path)
    if not path:  # только ?query — ссылка на эту же страницу
        return None
    if path.startswith("/"):
        if base:
            if path == base or path.startswith(base + "/"):
                path = path[len(base):] or "/"
            else:
                return f"ссылка с «/» без префикса BASE «{base}»"
        target = path.lstrip("/")
    else:
        target = posixpath.join(posixpath.dirname(page_rel), path)
    is_dir_link = path.endswith("/")
    target = posixpath.normpath(target) if target else "."
    if target == ".." or target.startswith("../"):
        return "ссылка ведёт за пределы сайта"
    if is_dir_link or target == ".":
        target = posixpath.normpath(posixpath.join(target, "index.html"))
    full = dist / target
    if full.is_file() or (full.is_dir() and (full / "index.html").is_file()):
        return None
    return f"файл не найден: {target}"


def check_2_internal_links(report, dist, pages, base):
    """Внутренние href/src ведут на существующие файлы."""
    count = 0
    for rel, (_raw, info) in pages.items():
        for tag, attr, ref in info.links:
            ref = ref.strip()
            low = ref.lower()
            if low.startswith(("http://", "https://", "//")):
                continue  # внешние — проверка 3
            if not ref or low.startswith(("mailto:", "tel:", "#", "javascript:", "data:")):
                continue
            count += 1
            err = resolve_internal(rel, ref, base, dist)
            if err:
                report.error(2, f"{rel}: <{tag} {attr}=\"{ref}\"> — {err}")
    report.stats[2] = f"страниц {len(pages)}, внутренних ссылок {count}"


def check_3_external_domains(report, U, pages):
    """Внешние ссылки — только на домены официальных полей данных и t.me."""
    allowed = allowed_hosts(U)
    count = 0
    for rel, (_raw, info) in pages.items():
        for tag, attr, ref in info.links:
            ref = ref.strip()
            if not ref.lower().startswith(("http://", "https://", "//")):
                continue
            count += 1
            host = host_of(ref)
            if host not in allowed:
                report.error(3, f"{rel}: <{tag} {attr}=\"{ref}\"> — домен «{host or '?'}» не из официальных полей")
    report.stats[3] = f"внешних ссылок {count}, разрешённых доменов {len(allowed)}"


def check_4_forbidden_words(report, pages):
    """На страницах нет агрегаторов и «лучший вуз»."""
    for rel, (raw, _info) in pages.items():
        text = norm(raw).casefold()
        for word in FORBIDDEN_WORDS:
            if word in text:
                report.error(4, f"{rel}: найдено запрещённое слово «{word}»")
    report.stats[4] = f"страниц {len(pages)}, слов в списке {len(FORBIDDEN_WORDS)}"


def row_text(cells: list[str]) -> str:
    return " | ".join(cells)


def find_common_grants(info: PageParser, label: str) -> tuple[int | None, str | None]:
    """Число грантов по строке «label» в таблице за 2026 «в этом вузе». Возвращает (число, причина_если_None)."""
    label_cf = label.casefold()
    best: tuple[int, str] | None = None  # (приоритет, текст строки)
    for table in info.tables:
        context = " ".join([table["context"], table["caption"], table["header"]]).casefold()
        if "2026" not in context:
            continue
        hits = [r for r in table["rows"] if label_cf in row_text(r).casefold()]
        if not hits:
            continue
        priority = 2 if "в этом вузе" in context else 1
        if best is None or priority > best[0]:
            best = (priority, row_text(hits[0]))
        if priority == 2:
            break
    if best is None:
        return None, f"не найдена таблица 2026 со строкой «{label}»"
    line = best[1]
    idx = line.casefold().find(label_cf)
    tail = line[idx + len(label_cf):]
    m = INT_RE.search(tail)
    if not m:
        return None, f"в строке «{label}» нет числа"
    return int(re.sub(r"\D", "", m.group(0))), None


BUILD_GOP_RE = re.compile(r"^[A-Z]\d{3}\b")
SCOPE_RE = re.compile(r"(\d{4}), в этом вузе \(([^()]*(?:\([^()]*\))?[^()]*)\)\s*$")  # h4 непосредственно перед таблицей


def build_gop_of(p: dict) -> str:
    """Группа программы — ровно как site/build.py:gop_of."""
    g = (p.get("grant_2026") or {}).get("gop") or ""
    if g:
        return g.split()[0]
    sec = p.get("section") or ""
    return sec[:4] if BUILD_GOP_RE.match(sec) else ""


def expected_score_text(grants, v) -> str | None:
    """Ожидаемый текст ячейки «Мин. балл»: балл; «от N% …» для процентов (None = достаточно префикса «от »)."""
    if v[1] is not None:
        return str(v[1])
    if len(v) > 2 and v[2] is not None:
        return None
    return "балл в списке не указан"


def check_5_grant_counts(report, U, grants, pages):
    """Для КАЖДОЙ открытой программы с группой грантов: таблицы «<год>, в этом вузе» (2026 и 2025) на странице
    содержат ровно категории из grants.uni(slug, gop)[год] с ненулевым числом: название, число грантов, мин. балл."""
    checked = no_data = skipped = rows_total = 0
    for slug in sorted(U.UNIS):
        seen_pid = set()
        progs = sorted((p for p in (U.UNIS[slug].get("programs") or {}).values() if p.get("open")),
                       key=lambda p: (p["name_ru"].casefold(), p["code"]))
        for prog in progs:
            k = make_pid(prog["code"])
            if k in seen_pid:  # build.py пишет только первую программу с таким pid
                continue
            seen_pid.add(k)
            gop = build_gop_of(prog)
            if not gop:
                continue
            rel = program_page(slug, prog["code"])
            if rel not in pages:
                skipped += 1  # отсутствие страницы — ошибка проверки 1
                continue
            raw, info = pages[rel]
            ug = grants.uni(slug, gop)
            if not ug and not grants.country(gop):
                continue  # блока грантов на странице нет
            # таблицы по годам
            tables: dict[str, dict] = {}
            for t in info.tables:
                m = SCOPE_RE.search(t["context"])
                if m:
                    tables[m.group(1)] = t
            for year in ("2026", "2025"):
                cats = {c: v for c, v in ((ug or {}).get(year) or {}).items() if v and v[0]}
                checked += 1
                t = tables.get(year)
                if not cats:
                    no_data += 1
                    if t is not None:
                        report.error(5, f"{rel}: {year} — данных нет, но на странице есть таблица «в этом вузе»")
                    elif f"В списках {year} года данных нет" not in raw:
                        report.error(5, f"{rel}: {year} — нет ни таблицы, ни заметки «данных нет»")
                    continue
                if t is None:
                    report.error(5, f"{rel}: {year} — нет таблицы «{year}, в этом вузе», ожидалось категорий {len(cats)}")
                    continue
                found = [r for r in t["rows"][1:] if len(r) >= 3]
                pool: dict[str, list[list[str]]] = {}
                for r in found:
                    pool.setdefault(r[0], []).append(r)
                for c, v in cats.items():
                    lab = grants.label(c)
                    rows_total += 1
                    cand = pool.get(lab)
                    if not cand:
                        report.error(5, f"{rel}: {year}, «{lab}» — ожидалась строка ({v[0]}), на странице нет")
                        continue
                    r = cand.pop(0)
                    exp = expected_score_text(grants, v)
                    if r[1] != str(v[0]):
                        report.error(5, f"{rel}: {year}, «{lab}» — грантов ожидалось {v[0]}, найдено {r[1]}")
                    if exp is None:
                        if not r[2].startswith("от "):
                            report.error(5, f"{rel}: {year}, «{lab}» — балл ожидался «от …%» ({v[2]}), найдено «{r[2]}»")
                    elif r[2] != exp:
                        report.error(5, f"{rel}: {year}, «{lab}» — балл ожидался «{exp}», найдено «{r[2]}»")
                for lab, left in pool.items():
                    for r in left:
                        report.error(5, f"{rel}: {year}, лишняя строка «{lab}» ({r[1]}, {r[2]})")
    report.stats[5] = (f"таблиц год×программа {checked} (без данных {no_data}), строк сверено {rows_total}, "
                       f"без страницы {skipped}")


def check_6_skeleton(report, pages):
    """Каждая страница — валидный каркас: doctype, title, meta description, lang=ru."""
    for rel, (raw, info) in pages.items():
        if not DOCTYPE_RE.match(raw.lstrip("﻿")):
            report.error(6, f"{rel}: нет <!doctype html> в начале")
        if not (info.title or "").strip():
            report.error(6, f"{rel}: пустой или отсутствующий <title>")
        desc = info.description
        if desc is None or not desc.strip():
            report.error(6, f"{rel}: нет <meta name=\"description\">")
        elif len(desc) > DESCRIPTION_MAX:
            report.error(6, f"{rel}: meta description длиннее {DESCRIPTION_MAX} символов ({len(desc)})")
        if (info.lang or "").strip().lower() != "ru":
            report.error(6, f"{rel}: <html lang=\"{info.lang or ''}\">, ожидалось lang=\"ru\"")
    report.stats[6] = f"страниц {len(pages)}"


def check_7_index(report, U, dist):
    """data/index.json содержит все вузы и открытые программы; все url в нём существуют."""
    index_path = dist / "data" / "index.json"
    if not index_path.is_file():
        report.error(7, "нет файла data/index.json")
        return
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except ValueError as e:
        report.error(7, f"data/index.json не читается как JSON: {e}")
        return
    unis = [u for u in (data.get("unis") or []) if isinstance(u, dict)]
    by_slug = {u.get("slug"): u for u in unis}

    def url_exists(url: str) -> bool:
        if not url or url.startswith("/") or url.lower().startswith(("http://", "https://")):
            return False
        full = dist / url
        if url.endswith("/"):
            full = full / "index.html"
        return full.is_file()

    n_progs = 0
    for slug in sorted(U.UNIS):
        entry = by_slug.get(slug)
        if entry is None:
            report.error(7, f"вуз «{slug}» отсутствует в data/index.json")
            continue
        if not url_exists(entry.get("url") or ""):
            report.error(7, f"вуз «{slug}»: url «{entry.get('url')}» не существует в сборке")
        idx_progs = {p.get("code"): p for p in (entry.get("programs") or []) if isinstance(p, dict)}
        for code, prog in sorted((U.UNIS[slug].get("programs") or {}).items()):
            if not prog.get("open"):
                continue
            n_progs += 1
            idx = idx_progs.get(code)
            if idx is None:
                report.error(7, f"программа {code} вуза «{slug}» отсутствует в data/index.json")
                continue
            if not url_exists(idx.get("url") or ""):
                report.error(7, f"программа {code} («{slug}»): url «{idx.get('url')}» не существует в сборке")
    report.stats[7] = f"вузов в индексе {len(by_slug)}, открытых программ {n_progs}"


# ---------------------------------------------------------------- вывод

def print_report(report: Report) -> None:
    for kind, bucket in (("ОШИБКА", report.errors), ("ПРЕДУПРЕЖДЕНИЕ", report.warnings)):
        for n in CHECK_TITLES:
            items = bucket[n]
            for msg in items[:MAX_PRINT]:
                print(f"{kind} [check {n}] {msg}")
            if len(items) > MAX_PRINT:
                print(f"  … ещё {len(items) - MAX_PRINT} не показано (check {n}, всего {len(items)})")
    print()
    print("Итог по проверкам:")
    for n, title in CHECK_TITLES.items():
        e, w = len(report.errors[n]), len(report.warnings[n])
        status = "OK" if e == 0 else "FAIL"
        extra = f"; {report.stats[n]}" if report.stats[n] else ""
        print(f"  Проверка {n} ({title}): ошибок {e}, предупреждений {w} — {status}{extra}")
    print(f"Предупреждений: {report.total_warnings()}")
    print(f"Ошибок: {report.total_errors()}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Проверки собранного сайта Pro4U (см. site/SPEC.md).")
    ap.add_argument("--dist", default=str(DEFAULT_DIST), help="папка сборки (по умолчанию site/dist)")
    ap.add_argument("--base", default="", help="префикс сайта, например /pro4u (по умолчанию пусто)")
    args = ap.parse_args(argv)

    dist = Path(args.dist).expanduser().resolve()
    if not dist.is_dir():
        print(f"Папка сборки не найдена: {dist}")
        print("Сначала соберите сайт: python site/build.py")
        return 2
    base = args.base.strip().rstrip("/")
    if base and not base.startswith("/"):
        base = "/" + base

    U, grants = load_bot_data()
    print(f"Сборка: {dist}; BASE: «{base}»")

    pages: dict[str, tuple[str, PageParser]] = {}
    for f in sorted(dist.rglob("*.html")):
        pages[f.relative_to(dist).as_posix()] = parse_page(f)

    report = Report()
    check_1_pages(report, U, pages)
    check_2_internal_links(report, dist, pages, base)
    check_3_external_domains(report, U, pages)
    check_4_forbidden_words(report, pages)
    check_5_grant_counts(report, U, grants, pages)
    check_6_skeleton(report, pages)
    check_7_index(report, U, dist)

    print_report(report)
    return 1 if report.total_errors() > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
