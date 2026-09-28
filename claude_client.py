# Всё общение с Claude API — в одном месте.
import anthropic

import config
from prompts import build_system

client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY, timeout=60.0)


class Refused(Exception):
    """Claude отказался отвечать на запрос."""


async def ask_claude(knowledge_text: str, lang: str, messages: list[dict]) -> str:
    """Отправляет историю диалога в Claude и возвращает текст ответа.

    Ошибки API (нет связи, неверный ключ и т.д.) не перехватываются здесь —
    их обрабатывает bot.py, чтобы показать пользователю понятное сообщение.
    """
    response = await client.beta.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=2000,
        system=build_system(knowledge_text, lang),
        messages=messages,
        # Если модель откажется отвечать по правилам безопасности,
        # запрос автоматически повторится на запасной модели.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    if response.stop_reason == "refusal":
        raise Refused()

    # Ответ состоит из «блоков»; берём только текстовые.
    return "".join(block.text for block in response.content if block.type == "text").strip()
