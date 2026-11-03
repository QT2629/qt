# Разметка сообщений: бот отправляет всё в режиме HTML Telegram, чтобы выделять важное жирным.
# Любой текст из данных или от ИИ сначала экранируем, иначе «&» или «<» сломают сообщение.
import html
import re

ALLOWED = ("b", "i")


def esc(text) -> str:
    return html.escape(str(text), quote=False)


def b(text) -> str:
    return f"<b>{esc(text)}</b>"


_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _cells(line: str) -> list[str]:
    return [c.replace("**", "").strip() for c in line.strip().strip("|").split("|")]


def tables_to_lists(text: str) -> str:
    """Telegram не умеет таблицы. Если ИИ всё же прислал «| вуз | цена |», превращаем её в список:
    таблица «пункт × вуз» — блок на каждый вуз, любая другая — строки через « · »."""
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            header, rows, j = _cells(lines[i]), [], i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append(_cells(lines[j]))
                j += 1
            if len(header) >= 3 and all(len(r) == len(header) for r in rows):   # первый столбец — названия пунктов
                for col in range(1, len(header)):
                    out.append(f"**{header[col]}**")
                    out += [f"• {r[0]}: {r[col]}" for r in rows if r[col]]
                    out.append("")
            else:
                if any(header):
                    out.append("**" + " · ".join(c for c in header if c) + "**")
                out += [" · ".join(c for c in r if c) for r in rows]
            i = j
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def from_ai(text: str) -> str:
    """Ответ ИИ → безопасный HTML: оставляем только <b> и <i>; **жирный** из Markdown тоже превращаем в <b>."""
    out = esc(tables_to_lists(text))
    for tag in ALLOWED:
        out = re.sub(rf"&lt;(/?){tag}&gt;", rf"<\1{tag}>", out, flags=re.I)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out, flags=re.S)
    out = re.sub(r"(?m)^#{1,6}\s*(.+)$", r"<b>\1</b>", out)       # заголовки Markdown — жирной строкой
    return balance(out)


def balance(text: str) -> str:
    """Закрывает незакрытые и убирает лишние закрывающие теги — Telegram не принимает «битый» HTML."""
    stack, out, pos = [], [], 0
    for m in re.finditer(r"</?(b|i)>", text):
        out.append(text[pos:m.start()])
        pos = m.end()
        tag, closing = m.group(1), m.group(0).startswith("</")
        if not closing:
            if tag in stack:          # вложенный такой же тег — просто пропускаем
                continue
            stack.append(tag)
            out.append(m.group(0))
        elif tag in stack:
            while stack:              # закрываем всё до нужного тега
                top = stack.pop()
                out.append(f"</{top}>")
                if top == tag:
                    break
    out.append(text[pos:])
    out += [f"</{t}>" for t in reversed(stack)]
    return "".join(out)


def strip_tags(text: str) -> str:
    """Запасной вариант, если Telegram всё же не принял разметку: тот же текст без тегов."""
    return html.unescape(re.sub(r"</?(b|i)>", "", text))


def split(text: str, limit: int) -> list[str]:
    """Режет длинный HTML по абзацам/строкам, не разрывая теги."""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for part in re.split(r"(\n)", text):
        if len(cur) + len(part) > limit and cur:
            chunks.append(cur)
            cur = ""
        cur += part
    if cur:
        chunks.append(cur)
    result = []
    for c in chunks:                       # одна строка длиннее лимита — режем грубо, без тегов
        result += [c] if len(c) <= limit else [strip_tags(c)[i:i + limit] for i in range(0, len(c), limit)]
    return [balance(c) for c in result]
