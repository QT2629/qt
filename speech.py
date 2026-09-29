# Распознавание голосовых сообщений (голос → текст) через OpenAI.
# Claude не принимает звук, поэтому голос сначала превращаем в текст, а дальше он идёт в Claude
# как обычный вопрос.
import logging

import openai

import config

logger = logging.getLogger("pro4u")

client = openai.AsyncOpenAI(api_key=config.OPENAI_API_KEY, timeout=60.0) if config.OPENAI_API_KEY else None

# Подсказка распознаванию: слова, которые часто звучат в вопросах абитуриентов (рус / қаз).
HINT = ("Вопрос абитуриента университету AlmaU. ЕНТ, ҰБТ, грант, специальность, мамандық, "
        "бакалавриат, творческий экзамен, шығармашылық емтихан, Data Science, CMDA, IT.")


class NoSpeechKey(Exception):
    """OPENAI_API_KEY не задан — голосовые сообщения не распознаём."""


async def transcribe(audio: bytes, filename: str = "voice.ogg") -> str:
    """Возвращает текст голосового сообщения. Ошибки OpenAI обрабатывает bot.py."""
    if client is None:
        raise NoSpeechKey()
    result = await client.audio.transcriptions.create(
        model=config.VOICE_MODEL,
        file=(filename, audio),
        prompt=HINT,
    )
    return (result.text or "").strip()


def voice_cost(seconds: int) -> float:
    """Примерная стоимость распознавания в долларах (цена за минуту)."""
    per_minute = 0.006 if config.VOICE_MODEL == "gpt-4o-transcribe" else 0.003
    return per_minute * seconds / 60
