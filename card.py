# Картинки бота: график роста баллов («Мой прогресс») и карточка пользователя («Моя карточка»).
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).parent / "assets" / "fonts"
W, H = 1080, 1350          # 4:5 — хорошо читается и в чате, и в ленте
PAD = 84

BG = (247, 246, 242)
INK = (22, 24, 29)
MUTED = (110, 113, 120)
LINE = (224, 222, 215)
GREEN = (31, 138, 91)
AMBER = (194, 124, 14)


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


PROGRESS_TEXT = {
    "ru": {"title": "Мой прогресс", "sub": "баллы пробных тестов и ЕНТ", "mock": "пробный", "ent": "ЕНТ",
           "target": "грант в {uni} в 2026: от {n}", "best": "лучший", "delta": "с первого теста"},
    "kz": {"title": "Менің прогресім", "sub": "сынақ тесттері мен ҰБТ баллдары", "mock": "сынақ", "ent": "ҰБТ",
           "target": "{uni}: 2026 жылғы грант — {n} баллдан", "best": "ең жоғары", "delta": "алғашқы тесттен бері"},
}


def progress_chart(rows: list[dict], lang: str, target: dict | None = None) -> bytes | None:
    """График роста баллов (PNG). rows — из profiles.scores(); target — {"uni": "SDU", "min": 120}."""
    if len(rows) < 2:
        return None
    tx = PROGRESS_TEXT.get(lang, PROGRESS_TEXT["ru"])
    img = Image.new("RGB", (W, 1080), BG)
    d = ImageDraw.Draw(img)

    d.text((PAD, PAD), "Pro4U", font=_font("Bold", 34), fill=INK)
    d.text((PAD + d.textlength("Pro4U", font=_font("Bold", 34)) + 14, PAD + 3), "· " + tx["title"],
           font=_font("Regular", 30), fill=MUTED)

    totals = [r["total"] for r in rows]
    first, last, best = totals[0], totals[-1], max(totals)
    f_big = _font("Bold", 120)
    d.text((PAD - 4, PAD + 70), str(last), font=f_big, fill=INK)
    x = PAD + d.textlength(str(last), font=f_big) + 30
    delta = last - first
    sign = "+" if delta > 0 else ""
    d.text((x, PAD + 96), f"{sign}{delta} {tx['delta']}", font=_font("Medium", 36), fill=GREEN if delta >= 0 else AMBER)
    d.text((x, PAD + 146), f"{tx['best']}: {best} · {tx['sub']}", font=_font("Regular", 28), fill=MUTED)

    # Область графика
    left, right, top, bottom = PAD + 60, W - PAD, PAD + 270, 1080 - PAD - 70
    lo = min(totals + ([target["min"]] if target else [])) - 10
    hi = max(totals + ([target["min"]] if target else [])) + 10
    lo, hi = max(0, lo - lo % 10), min(140, hi + (10 - hi % 10) % 10)
    if hi - lo < 20:
        hi = min(140, lo + 20)

    def yy(v: float) -> float:
        return bottom - (v - lo) / (hi - lo) * (bottom - top)

    f_axis = _font("Regular", 24)
    for v in range(lo, hi + 1, 10 if hi - lo <= 60 else 20):
        d.line((left, yy(v), right, yy(v)), fill=LINE, width=1)
        d.text((PAD, yy(v) - 14), str(v), font=f_axis, fill=MUTED)

    if target:
        ty = yy(target["min"])
        for sx in range(int(left), int(right), 22):                    # пунктир
            d.line((sx, ty, min(sx + 12, right), ty), fill=GREEN, width=3)

    n = len(rows)
    xs = [left + 20 + i * (right - left - 40) / (n - 1) for i in range(n)]
    pts = [(xs[i], yy(t)) for i, t in enumerate(totals)]
    d.line(pts, fill=INK, width=5, joint="curve")
    step = max(1, n // 8)                                              # подписи дат — не теснее 8 штук
    for i, ((px, py), r) in enumerate(zip(pts, rows)):
        color = GREEN if r["kind"] == "ent" else INK
        rad = 11 if r["kind"] == "ent" else 8
        d.ellipse((px - rad, py - rad, px + rad, py + rad), fill=color, outline=BG, width=3)
        d.text((px - d.textlength(str(r["total"]), font=f_axis) / 2, py - 44), str(r["total"]), font=f_axis, fill=INK)
        if i % step == 0 or i == n - 1:
            dd = r["taken_on"][8:10] + "." + r["taken_on"][5:7]
            d.text((px - d.textlength(dd, font=f_axis) / 2, bottom + 18), dd, font=f_axis, fill=MUTED)

    lx = PAD
    for color, label in ((INK, tx["mock"]), (GREEN, tx["ent"])):
        d.ellipse((lx, 1080 - PAD - 2, lx + 16, 1080 - PAD + 14), fill=color)
        d.text((lx + 26, 1080 - PAD - 8), label, font=f_axis, fill=MUTED)
        lx += 26 + d.textlength(label, font=f_axis) + 40
    if target:
        ly = 1080 - PAD + 6
        for sx in range(int(lx), int(lx) + 40, 16):
            d.line((sx, ly, sx + 9, ly), fill=GREEN, width=3)
        d.text((lx + 52, 1080 - PAD - 8), tx["target"].format(uni=target["uni"], n=target["min"]), font=f_axis, fill=GREEN)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def profile_card(info: dict, lang: str) -> bytes:
    """Карточка пользователя (PNG): главное о человеке на одной картинке.
    info: name, sub, rows [(подпись, значение, цвет|None)], totals [баллы по порядку], footer."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    inner = W - 2 * PAD

    f_brand = _font("Bold", 34)
    d.text((PAD, PAD), "Pro4U", font=f_brand, fill=INK)
    d.text((PAD + d.textlength("Pro4U", font=f_brand) + 14, PAD + 3),
           "· " + ("менің карточкам" if lang == "kz" else "моя карточка"), font=_font("Regular", 30), fill=MUTED)

    y = PAD + 100
    f_name = _font("Bold", 76)
    for line in _wrap(d, info["name"], f_name, inner)[:2]:
        d.text((PAD - 3, y), line, font=f_name, fill=INK)
        y += 88
    if info.get("sub"):
        d.text((PAD, y + 4), info["sub"], font=_font("Regular", 34), fill=MUTED)
        y += 56
    y += 26
    d.line((PAD, y, W - PAD, y), fill=LINE, width=2)
    y += 34

    colors = {"green": GREEN, "amber": AMBER, None: INK}
    f_label, f_val = _font("Regular", 28), _font("Medium", 38)
    spark_h = 210 if len(info.get("totals") or []) >= 2 else 0
    bottom_limit = H - PAD - 70 - spark_h
    for label, value, color in info["rows"]:
        lines = _wrap(d, value, f_val, inner)[:2]
        need = 36 + 48 * len(lines) + 22
        if y + need > bottom_limit:
            break
        d.text((PAD, y), label, font=f_label, fill=MUTED)
        y += 36
        for line in lines:
            d.text((PAD, y), line, font=f_val, fill=colors.get(color, INK))
            y += 48
        y += 22

    totals = info.get("totals") or []
    if spark_h:                                         # мини-график баллов
        top, bot = H - PAD - 70 - spark_h + 40, H - PAD - 90
        lo, hi = min(totals) - 5, max(totals) + 5
        n = len(totals)
        pts = [(PAD + 10 + i * (inner - 20) / (n - 1), bot - (v - lo) / max(1, hi - lo) * (bot - top))
               for i, v in enumerate(totals)]
        d.text((PAD, top - 40), info.get("spark_label", ""), font=f_label, fill=MUTED)
        d.line(pts, fill=INK, width=4, joint="curve")
        for (px, py) in pts:
            d.ellipse((px - 6, py - 6, px + 6, py + 6), fill=INK)
        lx, ly = pts[-1]
        d.ellipse((lx - 10, ly - 10, lx + 10, ly + 10), fill=GREEN)
        f_pt = _font("Medium", 28)
        for (px, py), v, anchor in ((pts[0], totals[0], "l"), (pts[-1], totals[-1], "r")):
            label = str(v)
            tx_ = px - 4 if anchor == "l" else px - d.textlength(label, font=f_pt) + 4
            d.text((tx_, py - 46), label, font=f_pt, fill=GREEN if anchor == "r" else INK)

    d.text((PAD, H - PAD - 34), info.get("footer", ""), font=_font("Regular", 26), fill=MUTED)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
