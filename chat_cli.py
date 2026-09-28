# Проверка бота прямо в терминале, без Telegram.
# Запуск: python chat_cli.py        (русский)
#         python chat_cli.py kz     (казахский)
# Выход: Ctrl+C или пустая строка.
import asyncio
import sys

import catalog
from claude_client import ask_claude
from knowledge import build_knowledge_text
from prompts import with_details


async def main() -> None:
    lang = sys.argv[1] if len(sys.argv) > 1 else "ru"
    knowledge_text = build_knowledge_text()
    history: list[dict] = []
    recent: list[str] = []
    print(f"Pro4U, язык: {lang}. Пустая строка — выход.\n")
    while True:
        user_text = input("Вы: ").strip()
        if not user_text:
            break
        codes = catalog.relevant_programs(user_text, recent)
        details = catalog.program_details(codes) if codes else None
        messages = history + [{"role": "user", "content": with_details(user_text, details)}]
        answer, _cost = await ask_claude(knowledge_text, lang, messages)
        print(f"\n[программы в запросе: {codes}]\nPro4U: {answer}\n")
        history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": answer}]
        recent = (catalog.find_programs(answer) or codes[:2])[:4]


if __name__ == "__main__":
    asyncio.run(main())
