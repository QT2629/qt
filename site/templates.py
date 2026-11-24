"""Общие куски вёрстки сайта Pro4U: шапка, крошки, подвал, блок «Важно». Всё, что из данных, экранируется."""
import html
import re

TG_URL = "https://t.me/Pro4orU_bot?start=src_site"
SITE_NAME = "Pro4U — вузы Казахстана"

# Чужие агрегаторы никогда не показываем (ни ссылкой, ни словом).
_URL = re.compile(r"https?://[^\s)\]»]+", re.I)
_AGG = re.compile(r"univision|studyinkz|epvo|bilim\.expert|vuzopedia", re.I)


def is_agg(s) -> bool:
    return bool(_AGG.search(str(s or "")))


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def clean(text) -> str:
    """Текст поля из данных -> безопасный текст: ссылки не делаем ссылками, агрегаторы убираем."""
    t = str(text or "")
    t = _URL.sub(lambda m: "" if _AGG.search(m.group(0)) else m.group(0), t)
    t = _AGG.sub("сторонний справочник", t)
    t = t.replace("(см. price_note)", "(см. раздел «Стоимость»)")
    t = re.sub(r"лучший вуз", "вуз", t, flags=re.I)
    return t


def text(s) -> str:
    return esc(clean(s))


def paras(s) -> str:
    """Многострочный текст -> абзацы."""
    parts = [p.strip() for p in clean(s).split("\n") if p.strip()]
    return "".join(f"<p>{esc(p)}</p>" for p in parts)


def ul(items) -> str:
    items = [i for i in (items or []) if str(i).strip()]
    return "<ul>" + "".join(f"<li>{text(i)}</li>" for i in items) + "</ul>" if items else ""


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def fmt_date(iso) -> str:
    m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)", str(iso or ""))
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else str(iso or "")


def fmt_price(n) -> str:
    return f"{int(n):,}".replace(",", " ") + " ₸ в год"


def trunc(s: str, n: int = 160) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rstrip(" ,;:.—-") + "…"


def ext_link(url, label=None, rel="noopener noreferrer") -> str:
    """Внешняя (официальная) ссылка; ссылки на агрегаторы не выводим."""
    if is_agg(url):
        return ""
    return f'<a href="{esc(url)}" target="_blank" rel="{rel}">{esc(label or url)}</a>'


def tg_button(extra_cls="") -> str:
    return (f'<a class="btn {extra_cls}" href="{TG_URL}" target="_blank" rel="noopener">'
            f'Спросить в Telegram-боте</a>')


def crumbs(base: str, items) -> str:
    """items: [(название, url|None)], «Главная» добавляется сама."""
    out = [f'<a href="{esc(base)}/">Главная</a>']
    for name, url in items:
        out.append(f'<a href="{esc(url)}">{esc(name)}</a>' if url else f'<span aria-current="page">{esc(name)}</span>')
    return '<nav class="crumbs" aria-label="Навигация">' + " <span aria-hidden='true'>›</span> ".join(out) + "</nav>"


def important(checked_on=None) -> str:
    date = f" Дата проверки данных вуза: {esc(fmt_date(checked_on))}." if checked_on else ""
    return (
        '<aside class="card note" aria-labelledby="imp"><h2 id="imp">Важно</h2>'
        "<p>Данные взяты из справок вузов и официальных списков грантов МНВО РК. Правила приёма меняются каждый год: "
        "сроки, цены и документы обязательно уточняйте в приёмной комиссии вуза."
        f"{date}</p></aside>"
    )


def page(base: str, title: str, description: str, body: str, *, head_extra: str = "", body_end: str = "",
         canonical_path: str = "") -> str:
    b = esc(base)
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(trunc(description))}">
<meta name="color-scheme" content="light dark">
<link rel="stylesheet" href="{b}/static/style.css">
{head_extra}</head>
<body>
<a class="skip" href="#main">К содержимому</a>
<header class="site-header"><div class="wrap">
<a class="brand" href="{b}/">Pro4U <span>— вузы Казахстана</span></a>
<nav class="topnav" aria-label="Разделы"><a href="{b}/osobyi-priem/">Особый приём</a><a href="{b}/moe/">Избранное</a><a href="{b}/o-proekte/">О проекте</a><span id="who" class="who" hidden></span></nav>
</div></header>
<main id="main" class="wrap">
{body}
</main>
<footer class="site-footer"><div class="wrap">
<p>{tg_button()}</p>
<p class="small">Pro4U — независимый справочник для абитуриентов Казахстана. Вузы показаны на равных, по алфавиту.
Информация справочная и не заменяет данные приёмной комиссии: правила приёма, сроки, цены и документы уточняйте в вузе.
Ссылки ведут только на официальные сайты вузов.</p>
<p class="small"><a href="{b}/">Главная</a> · <a href="{b}/osobyi-priem/">Особый приём</a> · <a href="{b}/o-proekte/">О проекте</a></p>
</div></footer>
<script src="{b}/static/vendor/telegram-web-app.js"></script>
<script src="{b}/static/auth.js" defer></script>
{body_end}</body>
</html>
"""


def fav_button(kind: str, slug: str) -> str:
    """Кнопка «В избранное»: видна только после входа через Telegram (auth.js)."""
    return (f'<p><button type="button" class="btn fav-btn" data-kind="{esc(kind)}" data-slug="{esc(slug)}" hidden>'
            f'☆ В избранное</button></p>')
