# Проверка: бот узнаёт каждый вуз (по-русски, в разных падежах, по сокращению и фамилии)
# и находит каждую программу каждого вуза. Запуск: python tools/check_names.py
import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import universities as U  # noqa: E402

_PREP = (("ский", "ском"), ("цкий", "цком"), ("ный", "ном"), ("ной", "ном"), ("ый", "ом"), ("ий", "ем"), ("ая", "ой"),
         ("ия", "ии"), ("ет", "ете"), ("ут", "уте"), ("ум", "уме"), ("ка", "ке"), ("ла", "ле"))
_GEN = (("ский", "ского"), ("цкий", "цкого"), ("ный", "ного"), ("ой", "ого"), ("ый", "ого"), ("ий", "его"), ("ая", "ой"),
        ("ия", "ии"), ("ет", "ета"), ("ут", "ута"), ("ка", "ки"))


def inflect(name: str, rules) -> str:
    """Грубо ставит название в падеж (до «им.» и скобок) — как его напишет абитуриент."""
    out, stop = [], False
    for w in name.split():
        if w.lower() in ("им.", "имени") or w[:1] in "(«":
            stop = True
        if not stop and re.fullmatch(r"[А-ЯЁа-яё-]+", w):
            w = next((w[: len(w) - len(a)] + b for a, b in rules if w.lower().endswith(a)), w)
        out.append(w)
    return " ".join(out)


def main() -> None:
    bad = []
    n_uni = 0
    for slug, u in U.UNIS.items():
        tests = {u["name_ru"], u["short"]}
        for n in (u["name_ru"], u["short"]):
            tests |= {f"хочу поступить в {inflect(n, _PREP)}", f"какие программы {inflect(n, _GEN)}"}
        m = re.search(r"(?:им\.|имени)\s+(?:[А-ЯЁ]\.\s*)*([А-ЯЁA-Z][\w-]+)", u["name_ru"])
        if m:
            tests.add(f"университет {m.group(1)}")
        for q in tests:
            n_uni += 1
            got = U.mentioned_unis(q)
            if slug not in got or len(got) > 2:
                bad.append(("вуз", u["short"], q, [U.UNIS[s]["short"] for s in got]))
    names = {p["name_ru"] for u in U.UNIS.values() for p in u["programs"].values()}
    for n in names:  # название специальности не должно приниматься за вуз
        if U.mentioned_unis(n):
            bad.append(("ложный вуз", n, "", [U.UNIS[s]["short"] for s in U.mentioned_unis(n)]))
    n_prog = 0
    for slug, u in U.UNIS.items():
        for p in u["programs"].values():
            if not p["open"]:
                continue
            for q in (f"{p['name_ru']} в {u['short']}", f"расскажи про {p['name_ru']} в {inflect(u['name_ru'], _PREP)}"):
                n_prog += 1
                keys = U.select(q, [])
                if not any(k.startswith(slug + ":") and U.program(k)["name_ru"].lower() == p["name_ru"].lower() for k in keys):
                    bad.append(("программа", u["short"], q, [U.program(k)["name_ru"] for k in keys][:3]))
    print(f"Вузов: {len(U.UNIS)}, проверок названий вузов: {n_uni}, названий специальностей: {len(names)}, "
          f"проверок поиска программ: {n_prog}. Ошибок: {len(bad)}")
    print(collections.Counter(b[0] for b in bad))
    for b in bad[:30]:
        print(b)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
