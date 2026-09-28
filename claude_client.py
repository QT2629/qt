# Всё общение с Claude API — в одном месте.
import logging

import anthropic

import config
from prompts import build_system

logger = logging.getLogger("pro4u")

client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY, timeout=60.0)

# Модели, для которых включаем автоматическую запасную модель при отказе
# по правилам безопасности. Для остальных (например, Haiku) параметр не нужен.
FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5")


class Refused(Exception):
    """Claude отказался отвечать на запрос."""


async def ask_claude(knowledge_text: str, lang: str, messages: list[dict]) -> str:
    """Отправляет историю диалога в Claude и возвращает текст ответа.

    Ошибки API (нет связи, неверный ключ и т.д.) не перехватываются здесь —
    их обрабатывает bot.py, чтобы показать пользователю понятное сообщение.
    """
    params = dict(
        model=config.CLAUDE_MODEL,
        max_tokens=1500,
        system=build_system(knowledge_text, lang),
        messages=messages,
    )
    if config.CLAUDE_MODEL.startswith(FALLBACK_MODELS):
        response = await client.beta.messages.create(
            **params, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
        )
    else:
        response = await client.messages.create(**params)

    usage = response.usage
    logger.info(
        "Токены: вход %s (из кэша %s, запись в кэш %s), ответ %s",
        usage.input_tokens, usage.cache_read_input_tokens, usage.cache_creation_input_tokens,
        usage.output_tokens,
    )

    if response.stop_reason == "refusal":
        raise Refused()

    # Ответ состоит из «блоков»; берём только текстовые.
    return "".join(block.text for block in response.content if block.type == "text").strip()
