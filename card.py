# Картинка «Шанс на грант» — чтобы результатом можно было поделиться (переслать другу, выложить в сторис).
# Рисуется без ИИ, по тем же данным, что и текстовый ответ (universities.chance_summary).
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import universities

FONTS = Path(__file__).parent / "assets" / "fonts"
W, H = 1080, 1350          # 4:5 — хорошо читается и в чате, и в ленте
PAD = 84

BG = (247, 246, 242)
INK = (22, 24, 29)
MUTED = (110, 113, 120)
LINE = (224, 222, 215)
GREEN = (31, 138, 91)
AMBER = (194, 124, 14)

CLOSE_GAP = 10             # «почти»: не хватает до 10 баллов

TEXT = {
    "ru": {
        "brand": "шанс на грант", "score": "балл ЕНТ", "contest": "общий конкурс, без квот",
        "head_yes": "Где с таким баллом давали грант в 2026",
        "head_no": "Ближе всего к гранту в 2026",
        "from": "от {n}", "gap": "не хватает {n}", "more": "и ещё {n}", "country": "по стране от {n}",
        "note": "По официальному списку грантов 2026. Это не гарантия: в 2027 году границы будут другими.",
        "cta": "Проверь свой балл:",
    },
    "kz": {
        "brand": "грантқа мүмкіндік", "score": "ҰБТ баллы", "contest": "жалпы конкурс, квотасыз",
        "head_yes": "2026 жылы осы баллмен грант берілген ЖОО",
        "head_no": "2026 жылы грантқа ең жақын нұсқалар",
        "from": "{n} бастап", "gap": "{n} балл жетпейді", "more": "тағы {n}", "country": "ел бойынша {n} бастап",
        "note": "2026 жылғы ресми грант тізімі бойынша. Бұл кепілдік емес: 2027 жылы шекті балл өзгереді.",
        "cta": "Өз баллыңды тексер:",
    },
}


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Roboto-{weight}.ttf"), size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        test = f"{cur} {word}".strip()
        if draw.textlength(test, font=font) <= width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def _pick(groups: list[dict], score: int) -> tuple[list[dict], bool]:
    """Какие группы и вузы показать: где проходишь, плюс «почти» (не хватает до CLOSE_GAP)."""
    shown = []
    for g in groups:
        unis = [u for u in g["unis"] if u["gap"] <= CLOSE_GAP]
        if unis:
            shown.append({**g, "show": unis, "hidden": len(g["unis"]) - len(unis)})
    passed = any(u["gap"] == 0 for g in shown for u in g["show"])
    if not passed:  # ни в один вуз базы пока не проходишь — ближайшие группы, по 2 вуза
        near = sorted(groups, key=lambda g: (g["unis"][0]["gap"], g["kz_min"]))[:4]
        shown = [{**g, "show": g["unis"][:2], "hidden": max(0, len(g["unis"]) - 2)} for g in near]
    return shown, passed


def chance_card(group: str, score: int, lang: str, bot_username: str) -> bytes | None:
    """PNG-картинка с результатом. None — если по этим предметам нет данных о грантах."""
    groups = universities.chance_summary(group, score)
    if not groups:
        return None
    tx = TEXT.get(lang, TEXT["ru"])
    shown, passed = _pick(groups, score)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    inner = W - 2 * PAD

    # Шапка
    f_brand, f_small = _font("Bold", 34), _font("Regular", 30)
    d.text((PAD, PAD), "Pro4U", font=f_brand, fill=INK)
    x = PAD + d.textlength("Pro4U", font=f_brand) + 14
    d.text((x, PAD + 3), "· " + tx["brand"], font=f_small, fill=MUTED)

    # Балл и предметы
    y = PAD + 96
    f_num = _font("Bold", 196)
    num = str(score)
    d.text((PAD - 6, y), num, font=f_num, fill=INK)
    nx = PAD + d.textlength(num, font=f_num) + 34
    f_pair = _font("Medium", 38)
    pair_lines = _wrap(d, universities.ENT_LABELS[group][lang], f_pair, W - PAD - nx)
    py = y + 46
    d.text((nx, py), tx["score"], font=f_small, fill=MUTED)
    py += 46
    for line in pair_lines[:2]:
        d.text((nx, py), line, font=f_pair, fill=INK)
        py += 48
    d.text((nx, py + 4), tx["contest"], font=f_small, fill=MUTED)

    y += 250
    d.line((PAD, y, W - PAD, y), fill=LINE, width=2)
    y += 44

    # Заголовок списка
    f_head = _font("Bold", 42)
    for line in _wrap(d, tx["head_yes"] if passed else tx["head_no"], f_head, inner):
        d.text((PAD, y), line, font=f_head, fill=INK)
        y += 54
    y += 18

    # Группы и вузы — сколько влезает до подвала
    footer_top = H - PAD - 196
    f_group, f_code = _font("Medium", 32), _font("Regular", 26)
    f_uni, f_val = _font("Medium", 34), _font("Regular", 32)
    row, title_h, gap_after = 50, 46, 26
    for g in shown:
        name = g["gop"].partition(" ")[2]
        if y + title_h + row > footer_top:
            break
        country = tx["country"].format(n=g["kz_min"])
        cw = d.textlength(country, font=f_code)
        name_line = _wrap(d, name, f_group, inner - cw - 30)[0]
        d.text((PAD, y), name_line, font=f_group, fill=MUTED)
        d.text((W - PAD - cw, y + 5), country, font=f_code, fill=GREEN if score >= g["kz_min"] else MUTED)
        y += title_h
        drawn = 0
        for u in g["show"]:
            if y + row > footer_top:
                break
            ok = u["gap"] == 0
            color = GREEN if ok else AMBER
            cy = y + 22
            d.ellipse((PAD, cy - 9, PAD + 18, cy + 9), fill=color)
            d.text((PAD + 36, y), u["short"], font=f_uni, fill=INK)
            val = tx["from"].format(n=u["min"]) if ok else tx["gap"].format(n=u["gap"])
            d.text((W - PAD - d.textlength(val, font=f_val), y + 2), val, font=f_val, fill=color if not ok else INK)
            y += row
            drawn += 1
        rest = g["hidden"] + len(g["show"]) - drawn
        if rest and y + 40 <= footer_top:
            d.text((PAD + 36, y), tx["more"].format(n=rest), font=f_code, fill=MUTED)
            y += 40
        y += gap_after

    # Подвал
    y = footer_top + 20
    d.line((PAD, y, W - PAD, y), fill=LINE, width=2)
    y += 30
    f_note = _font("Regular", 26)
    for line in _wrap(d, tx["note"], f_note, inner)[:2]:
        d.text((PAD, y), line, font=f_note, fill=MUTED)
        y += 36
    y += 22
    f_cta, f_link = _font("Regular", 34), _font("Bold", 36)
    d.text((PAD, y), tx["cta"], font=f_cta, fill=MUTED)
    link = f"t.me/{bot_username}" if bot_username else "Pro4U"
    d.text((PAD + d.textlength(tx["cta"], font=f_cta) + 14, y - 2), link, font=f_link, fill=INK)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
