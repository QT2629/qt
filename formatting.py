# Разметка сообщений: бот отправляет всё в режиме HTML Telegram, чтобы выделять важное жирным.
# Любой текст из данных или от ИИ сначала экранируем, иначе «&» или «<» сломают сообщение.
import html
import re

ALLOWED = ("b", "i")


def esc(text) -> str:
    return html.escape(str(text), quote=False)


def b(text) -> str:
    return f"<b>{esc(text)}</b>"


def from_ai(text: str) -> str:
    """Ответ ИИ → безопасный HTML: оставляем только <b> и <i>; **жирный** из Markdown тоже превращаем в <b>."""
    out = esc(text)
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
