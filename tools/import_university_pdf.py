# Превращает PDF-справку о вузе (формат «● Название-6B… / Профильные предметы ЕНТ / Ключевые дисциплины /
# Траектория выпускников / Где работают» + раздел «СТОИМОСТЬ ОБУЧЕНИЯ») в файл программ для бота.
# Боту эта программа не нужна — запускается вручную, когда пришла новая справка.
#
#   pip install pypdf
#   python tools/import_university_pdf.py справка.pdf knowledge/universities/<вуз>/programs.json
#
# После запуска обязательно просмотрите результат: скрипт печатает программы без цены и без предметов ЕНТ.
import json
import re
import sys

from pypdf import PdfReader

FIELDS = {
    "ent": "Профильные предметы ЕНТ:",
    "courses": "Ключевые дисциплины программы:",
    "careers": "Траектория выпускников:",
    "workplaces": "Где работают:",
}
PRICE = r"(\d{1,2}(?:\s\d{3}){2})\s*₸\s*в\s*год"


def norm_code(code: str) -> str:
    return code.replace("В", "B").replace(" ", "")  # в справках бывает кириллическая «В»


def clean(text: str) -> str:
    text = re.sub(r"(\w)- (\w)", r"\1-\2", text)  # «бизнес- аналитик» после переноса
    return re.sub(r"\s+", " ", text).strip(" .")


def split_list(text: str) -> list[str]:
    return [clean(x) for x in re.split(r",(?![^()]*\))", text) if clean(x)]


def parse(path: str) -> list[dict]:
    raw = "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
    raw = raw.replace("", "●").replace("\n l ", "\n● ").replace("\nl ", "\n● ")
    body, _, prices = raw.partition("СТОИМОСТЬ ОБУЧЕНИЯ")

    programs, section = [], ""
    for chunk in re.split(r"\n\s*●\s*", "\n" + body):
        head, _, rest = chunk.partition(FIELDS["ent"])
        if not rest:  # заголовок документа или раздела
            lines = [line.strip() for line in chunk.splitlines() if line.strip()]
            section = lines[-1] if lines else section
            continue
        m = re.match(r"(.+?)\s*-\s*(6\s*[BВ]\s*\d{5})\s*(.*)$", clean(head), re.S)
        if not m:
            print("Не разобрал заголовок:", clean(head)[:80], file=sys.stderr)
            continue
        name, code, tail = m.group(1), norm_code(m.group(2)), clean(m.group(3))
        values, text = {}, FIELDS["ent"] + rest
        keys = list(FIELDS)
        for i, key in enumerate(keys):
            start = text.find(FIELDS[key])
            if start < 0:
                continue
            start += len(FIELDS[key])
            ends = [text.find(FIELDS[k], start) for k in keys[i + 1:] if text.find(FIELDS[k], start) > 0]
            values[key] = text[start: min(ends) if ends else len(text)]
        # следующий заголовок раздела прилипает к концу «Где работают» — отрезаем его
        work = values.get("workplaces", "")
        last_dot = work.rfind(".")
        next_section = clean(work[last_dot + 1:]) if last_dot >= 0 else ""
        ent = clean(values.get("ent", "")).replace("✱", "").strip()
        programs.append({
            "code": code,
            "name_ru": clean(name + (" " + tail if tail else "")),
            "section": section,
            "ent_subjects": ent,
            "ent_note": "Предметы ЕНТ уточнять в приёмной комиссии" if "✱" in values.get("ent", "") else "",
            "key_courses": split_list(values.get("courses", "")),
            "careers": split_list(values.get("careers", "")),
            "workplaces": split_list(work[: last_dot] if last_dot >= 0 else work),
            "price_kzt": None,
        })
        if next_section:
            section = next_section

    by_code = {p["code"]: p for p in programs}
    current = None
    for m in re.finditer(PRICE + r"|стоимость\s+уточняется|\((6\s*[BВ]\d{5})\)\s*-\s*" + PRICE
                         + r"|(6\s*[BВ]\s*\d{5})", prices):
        if m.group(2):  # «Название (код) - цена»
            code = norm_code(m.group(2))
            if code in by_code:
                by_code[code]["price_kzt"] = int(re.sub(r"\s", "", m.group(3)))
        elif m.group(1):
            current = int(re.sub(r"\s", "", m.group(1)))
        elif m.group(0).startswith("стоимость"):
            current = None
        elif m.group(4):
            code = norm_code(m.group(4))
            if code in by_code and current:
                by_code[code]["price_kzt"] = current
    return programs


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    programs = parse(src)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(programs, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Программ: {len(programs)} → {dst}")
    for p in programs:
        problems = [k for k in ("price_kzt", "ent_subjects", "key_courses") if not p[k]]
        if problems:
            print(f"  ⚠ {p['code']} {p['name_ru']}: нет {', '.join(problems)}")


if __name__ == "__main__":
    main()
