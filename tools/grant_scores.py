# Считает баллы госгрантов по вузу из официального PDF «Список обладателей образовательных грантов».
# Нужен раз в год, когда выходит новый список. Боту эта программа не нужна.
#
#   pip install pypdf
#   python tools/grant_scores.py список.pdf [ещё_части.pdf ...] --code 083
#
# Печатает по каждой группе (ГОП): сколько грантов у вуза и минимальный/максимальный балл,
# а также минимальный балл по стране. ФИО не выводятся и никуда не сохраняются.
import argparse
import re
from collections import defaultdict

from pypdf import PdfReader

ROW = re.compile(r"\b\d+ \d{9} [^\d]+? (\d{2,3}) (\d{3})(?=\s)")
GROUP = re.compile(r"^\s*(B\d{3}) - (.+?)\s*$", re.M)
CONTEST = re.compile(r"^\s*(ОБЩИЙ КОНКУРС|СЕЛЬСКАЯ КВОТА)", re.M)
# После общего списка идут отдельные списки (Минздрав, педагогические, технические) — без кода вуза.
SPECIAL = "Список обладателей образовательных грантов, поступивших"


def read_text(paths: list[str]) -> str:
    text = []
    for path in paths:
        for page in PdfReader(path).pages:
            text.append(page.extract_text() or "")
    return "\n".join(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", nargs="+", help="PDF-файлы списка по порядку страниц")
    parser.add_argument("--code", default="083", help="код вуза (ОВПО), AlmaU = 083")
    args = parser.parse_args()

    text = read_text(args.pdf)
    if SPECIAL in text:
        text = text[: text.find(SPECIAL)]

    events = [(m.start(), "group", f"{m.group(1)} {m.group(2)}") for m in GROUP.finditer(text)]
    events += [(m.start(), "contest", m.group(1)) for m in CONTEST.finditer(text)]
    events.sort()

    everyone, ours = defaultdict(list), defaultdict(list)
    state = {"group": "?", "contest": "?"}
    i = 0
    for m in ROW.finditer(text):
        while i < len(events) and events[i][0] < m.start():
            state[events[i][1]] = events[i][2]
            i += 1
        key = (state["group"], state["contest"])
        score = int(m.group(1))
        everyone[key].append(score)
        if m.group(2) == args.code:
            ours[key].append(score)

    print(f"Всего строк: {sum(map(len, everyone.values()))}, у вуза {args.code}: {sum(map(len, ours.values()))}\n")
    for group, contest in sorted({k for k in everyone if k[0] in {g for g, _ in ours}}):
        mine = ours.get((group, contest), [])
        line = f"{group} | {contest} | мин. по стране {min(everyone[(group, contest)])}"
        if mine:
            line += f" | у вуза: {len(mine)} грантов, мин. {min(mine)}, макс. {max(mine)}"
        print(line)


if __name__ == "__main__":
    main()
