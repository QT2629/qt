# Всё общение с ИИ (Gemini или Claude) — в одном месте. Какой отвечает, задаёт config.AI_PROVIDER.
import re
import logging
from types import SimpleNamespace

import anthropic

try:
    from google import genai
    from google.genai import errors as genai_errors, types as genai_types
except ImportError:  # без google-genai бот работает на Claude
    genai = genai_errors = genai_types = None

import config
from prompts import build_system
from stats import request_cost

logger = logging.getLogger("pro4u")

client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY, timeout=60.0) if config.ANTHROPIC_API_KEY else None
gemini_client = (genai.Client(api_key=config.GEMINI_API_KEY, http_options=genai_types.HttpOptions(timeout=60_000))
                 if genai and config.GEMINI_API_KEY else None)

# Ошибки обоих ИИ — bot.py ловит их одним кортежем.
AI_ERRORS = (anthropic.AnthropicError,) + ((genai_errors.APIError,) if genai_errors else ())

# Модели, для которых включаем автоматическую запасную модель при отказе
# по правилам безопасности. Для остальных (например, Haiku) параметр не нужен.
FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5")


class Refused(Exception):
    """ИИ отказался отвечать на запрос."""


class NoApiKey(Exception):
    """Ключ выбранного ИИ не задан — ИИ не подключён."""


_SERVICE_TAG = re.compile(r"</?(?:program_details|student_profile|user_preferences|almau_details|universities)>")


def _hide_service_tags(text: str) -> str:
    """Служебные теги из промпта не должны попадать к человеку: заменяем на «моей базе»."""
    return _SERVICE_TAG.sub("моей базе", text)


async def ask_claude(knowledge_text: str, lang: str, messages: list[dict]) -> tuple[str, float]:
    """Отправляет историю диалога ИИ и возвращает (текст ответа, примерная стоимость в $).

    Название историческое: отвечает Gemini или Claude — смотря что выбрано в config.AI_PROVIDER.
    Ошибки API (нет связи, неверный ключ и т.д.) не перехватываются здесь —
    их обрабатывает bot.py, чтобы показать пользователю понятное сообщение.
    """
    if config.AI_PROVIDER == "gemini":
        return await _ask_gemini(knowledge_text, lang, messages)
    return await _ask_anthropic(knowledge_text, lang, messages)


def _gemini_config(system_text: str, thinking: bool):
    kwargs = dict(system_instruction=system_text, max_output_tokens=1500)
    if thinking and config.GEMINI_THINKING in ("minimal", "low", "medium", "high"):
        kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_level=config.GEMINI_THINKING)
    return genai_types.GenerateContentConfig(**kwargs)


async def _ask_gemini(knowledge_text: str, lang: str, messages: list[dict]) -> tuple[str, float]:
    if gemini_client is None:
        raise NoApiKey()
    # Общая часть (правила + база) идёт первой и одинакова у всех — Google кэширует её сам (неявный кэш).
    system_text = "\n\n".join(block["text"] for block in build_system(knowledge_text, lang))
    contents = [
        genai_types.Content(role="model" if m["role"] == "assistant" else "user",
                            parts=[genai_types.Part(text=m["content"])])
        for m in messages
    ]
    try:
        response = await gemini_client.aio.models.generate_content(
            model=config.GEMINI_MODEL, contents=contents, config=_gemini_config(system_text, thinking=True))
    except genai_errors.ClientError as e:
        # Эта модель не знает параметр «думания» — повторяем без него.
        if e.code == 400 and "thinking" in str(e).lower():
            logger.warning("Модель %s не приняла thinking_level, повторяю без него", config.GEMINI_MODEL)
            response = await gemini_client.aio.models.generate_content(
                model=config.GEMINI_MODEL, contents=contents, config=_gemini_config(system_text, thinking=False))
        else:
            raise

    meta = response.usage_metadata
    cached = (meta.cached_content_token_count or 0) if meta else 0
    prompt = (meta.prompt_token_count or 0) if meta else 0
    out = ((meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)) if meta else 0  # мысли оплачиваются как ответ
    usage = SimpleNamespace(input_tokens=prompt - cached, cache_read_input_tokens=cached,
                            cache_creation_input_tokens=0, output_tokens=out)
    cost = request_cost(config.GEMINI_MODEL, usage)
    logger.info("Токены Gemini: вход %s (из кэша %s), ответ+мысли %s — ~$%.4f", prompt, cached, out, cost)

    if not response.candidates:  # запрос заблокирован фильтрами Google
        raise Refused()
    finish = getattr(response.candidates[0], "finish_reason", None)
    answer = (response.text or "").strip()
    if not answer and finish is not None and "SAFETY" in str(finish).upper():
        raise Refused()
    return _hide_service_tags(answer), cost


async def _ask_anthropic(knowledge_text: str, lang: str, messages: list[dict]) -> tuple[str, float]:
    if client is None:
        raise NoApiKey()
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
    cost = request_cost(config.CLAUDE_MODEL, usage)
    logger.info(
        "Токены: вход %s (из кэша %s, запись в кэш %s), ответ %s — ~$%.4f",
        usage.input_tokens, usage.cache_read_input_tokens, usage.cache_creation_input_tokens,
        usage.output_tokens, cost,
    )

    if response.stop_reason == "refusal":
        raise Refused()

    # Ответ состоит из «блоков»; берём только текстовые.
    answer = "".join(block.text for block in response.content if block.type == "text").strip()
    return _hide_service_tags(answer), cost
