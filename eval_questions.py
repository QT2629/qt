# Автопроверка: задаёт боту типичные вопросы абитуриентов и проверяет ответы.
# Запуск: python eval_questions.py
# Каждый вопрос — отдельный новый диалог. Проверки простые: ищем в ответе
# ключевые слова (без учёта регистра). Прочитайте ответы и глазами тоже.
import asyncio

import catalog
import universities
from claude_client import ask_claude
from knowledge import build_knowledge_text
from prompts import with_details

# (язык, вопрос, слова — хотя бы одно из каждой группы должно быть в ответе)
CASES = [
    ("ru", "У меня на ЕНТ математика и информатика. Куда я могу поступить в AlmaU?",
     [["data science"], ["software engineering", "инженерия программного"], ["информационные системы"]]),
    ("ru", "Сколько стоит учёба на Менеджменте?",
     [["2 950 000", "2950000"], ["год"]]),
    ("ru", "Хочу поступить на Digital Commerce",
     [["нет набора", "не набира", "набора нет", "не будет набора"]]),
    ("ru", "Какие документы нужны для поступления?",
     [["075"], ["эцп"], ["6 фото", "6 фотограф", "шесть"]]),
    ("ru", "Какой проходной балл на грант на Финансы?",
     [["128"], ["b046", "групп"]]),
    ("ru", "С каким баллом дали грант на IT в AlmaU?",
     [["100"], ["2026"]]),
    ("ru", "Я люблю снимать видео и монтировать ролики, что мне подойдёт?",
     [["кинопроизводств", "новые медиа", "new media", "filmmaking"]]),
    ("ru", "Когда регистрация на творческий экзамен?",
     [["22 июня"], ["10 августа"]]),
    ("ru", "Сколько стоит магистратура?",
     [["2 310 000", "2310000"]]),
    ("ru", "Расскажи, какой проходной балл в КИМЭП",
     [["нет данных", "данных нет", "нет информации", "не знаю", "нет в базе", "пока нет"]]),
    ("ru", "Сколько стоит Финансы в КБТУ и какие предметы ЕНТ нужны?",
     [["1 800 000", "1800000"], ["математика"], ["географ"]]),
    ("ru", "Сравни юриспруденцию в AlmaU, ЕНУ и Нархозе по цене",
     [["1 550 000", "1550000"], ["1 602 000", "1602000"], ["almau"]]),
    ("ru", "Где можно учиться на Data Science в Нархозе?",
     [["статистика и наука о данных", "наука о данных"], ["2 322 000", "2322000"]]),
    ("ru", "Чем отличается Психология от Клинической психологии и можно ли туда поступить?",
     [["клиническ"], ["нет набора", "набора нет", "не набира", "не будет набора", "2026"]]),
    ("kz", "Менің ҰБТ пәндерім география және биология. Қандай мамандыққа түсе аламын?",
     [["психология"]]),
    ("kz", "Қандай құжаттар керек?",
     [["эцқ", "эцп"], ["075"]]),
]


def check(answer: str, groups: list[list[str]]) -> list[str]:
    low = answer.lower()
    return [" / ".join(g) for g in groups if not any(word.lower() in low for word in g)]


async def main() -> None:
    knowledge_text = build_knowledge_text()
    passed = 0
    for i, (lang, question, groups) in enumerate(CASES, 1):
        codes, uni_keys = universities.select(question, [], [])
        details = catalog.program_details(codes, universities.details(uni_keys)) if codes or uni_keys else None
        answer, _cost = await ask_claude(knowledge_text, lang, [{"role": "user", "content": with_details(question, details)}])
        missing = check(answer, groups)
        status = "OK  " if not missing else "FAIL"
        passed += not missing
        print(f"\n{'=' * 70}\n[{status}] {i}. ({lang}) {question}\n{'-' * 70}\n{answer}")
        if missing:
            print(f"\n  Не найдено: {missing}")
    print(f"\n{'=' * 70}\nИтого: {passed}/{len(CASES)} проверок пройдено")


if __name__ == "__main__":
    asyncio.run(main())
