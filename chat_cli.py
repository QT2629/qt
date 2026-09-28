# Проверка бота прямо в терминале, без Telegram.
# Запуск: python chat_cli.py        (русский)
#         python chat_cli.py kz     (казахский)
# Выход: Ctrl+C или пустая строка.
import asyncio
import sys

from claude_client import ask_claude
from knowledge import build_knowledge_text


async def main() -> None:
    lang = sys.argv[1] if len(sys.argv) > 1 else "ru"
    knowledge_text = build_knowledge_text()
    history: list[dict] = []
    print(f"Pro4U, язык: {lang}. Пустая строка — выход.\n")
    while True:
        user_text = input("Вы: ").strip()
        if not user_text:
            break
        messages = history + [{"role": "user", "content": user_text}]
        answer = await ask_claude(knowledge_text, lang, messages)
        print(f"\nPro4U: {answer}\n")
        history = messages + [{"role": "assistant", "content": answer}]


if __name__ == "__main__":
    asyncio.run(main())
