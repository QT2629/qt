# Главная фотография вуза для его карточки.
# 1) Своя фотография: assets/universities/<вуз>.jpg (или .png) — если положить файл, бот возьмёт его.
# 2) Иначе — главная фотография статьи о вузе в Википедии. Под фото — только название вуза.
#    Авторов фото лицензия требует где-то указать — они в команде /credits (под фото их нет).
#    Логотипы и гербы не берём. Статья должна быть именно про этот вуз (проверяем по названию).
# Найденное запоминаем в data/photos.json (Telegram file_id), чтобы не искать заново.
import html
import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

import httpx

import config
import universities

logger = logging.getLogger("pro4u")

OWN_DIR = Path(__file__).parent / "assets" / "universities"
CACHE_PATH = Path(config.DATA_DIR) / "photos.json"
WIKI_API = "https://{lang}.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "Pro4U-bot/1.0 (Telegram bot for applicants in Kazakhstan)"}
RETRY_AFTER_DAYS = 30           # не нашли фото — попробуем снова через месяц
_LOGO = re.compile(r"logo|лого|emblem|эмблем|герб|coat|seal|печать|flag|флаг|icon|symbol|\.svg$", re.I)


def _cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def own_photo(slug: str) -> Path | None:
    for ext in ("jpg", "jpeg", "png", "webp"):
        path = OWN_DIR / f"{slug}.{ext}"
        if path.exists():
            return path
    return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


async def _wiki_photo(slug: str) -> dict | None:
    """Ищет статью о вузе в Википедии (русской, потом английской) и её главную фотографию."""
    u = universities.UNIS[slug]
    queries = [(lang, q) for lang in ("ru", "en") for q in (u["name_ru"], u["short"], u.get("name_en", "")) if q]
    async with httpx.AsyncClient(timeout=10, headers=HEADERS, follow_redirects=True) as client:
        for lang, q in queries:
            r = await client.get(WIKI_API.format(lang=lang), params={
                "action": "query", "format": "json", "generator": "search", "gsrsearch": q, "gsrlimit": 3,
                "prop": "pageimages", "piprop": "original|name", "pilicense": "free"})
            pages = sorted((r.json().get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
            for page in pages:
                # Статья должна быть про этот вуз: по её названию бот узнаёт именно его.
                if slug not in universities.mentioned_unis(page.get("title", "")):
                    continue
                name, img = page.get("pageimage", ""), (page.get("original") or {}).get("source", "")
                if not img or _LOGO.search(name) or _LOGO.search(img):
                    # Главная картинка — логотип: берём первое фото (jpg) из той же статьи.
                    lst = await client.get(WIKI_API.format(lang=lang), params={
                        "action": "query", "format": "json", "titles": page["title"], "prop": "images", "imlimit": 30})
                    files = [im["title"].split(":", 1)[1] for p in (lst.json().get("query") or {}).get("pages", {}).values()
                             for im in p.get("images", [])]
                    name = next((f for f in files if re.search(r"\.jpe?g$", f, re.I) and not _LOGO.search(f)), "")
                    if not name:
                        continue
                info = await client.get(WIKI_API.format(lang=lang), params={
                    "action": "query", "format": "json", "titles": f"File:{name}", "prop": "imageinfo",
                    "iiprop": "url|extmetadata", "iiurlwidth": 1280})
                ii = next(iter((info.json().get("query") or {}).get("pages", {}).values()), {}).get("imageinfo", [{}])[0]
                meta = ii.get("extmetadata") or {}
                author = _clean((meta.get("Artist") or {}).get("value", ""))[:80]
                lic = _clean((meta.get("LicenseShortName") or {}).get("value", ""))
                return {"url": ii.get("thumburl") or img, "credit": ", ".join(x for x in (author, lic) if x)}
    return None


async def send_uni_photo(bot, chat_id: int, slug: str, lang: str) -> None:
    """Отправляет главное фото вуза над его карточкой. Ничего не нашли или ошибка — просто без фото."""
    u = universities.UNIS[slug]
    title = f"🏛 {u['name_kz' if lang == 'kz' else 'name_ru']}"
    cache = _cache()
    item = cache.get(slug) or {}
    try:
        own = own_photo(slug)
        if own:
            if item.get("own") and item.get("file_id"):
                await bot.send_photo(chat_id, item["file_id"], caption=html.escape(title))
                return
            with own.open("rb") as f:
                msg = await bot.send_photo(chat_id, f, caption=html.escape(title))
            cache[slug] = {"own": True, "file_id": msg.photo[-1].file_id}
            _save(cache)
            return
        if item.get("file_id"):
            await bot.send_photo(chat_id, item["file_id"], caption=html.escape(title))
            return
        if item.get("none") and date.fromisoformat(item["checked"]) > date.today() - timedelta(days=RETRY_AFTER_DAYS):
            return
        found = await _wiki_photo(slug)
        if not found:
            cache[slug] = {"none": True, "checked": date.today().isoformat()}
            _save(cache)
            return
        msg = await bot.send_photo(chat_id, found["url"], caption=html.escape(title))
        cache[slug] = {"file_id": msg.photo[-1].file_id, "credit": found["credit"], "checked": date.today().isoformat()}
        _save(cache)
    except Exception as e:  # фото — дополнение: из-за него карточка вуза не должна ломаться
        logger.warning("Фото вуза %s не отправлено: %s", slug, e)


def credits_text() -> str:
    """Авторы фотографий из Википедии (для команды /credits)."""
    cache = _cache()
    lines = [f"• {universities.UNIS[s]['short']}: {item['credit']}" for s, item in cache.items()
             if item.get("credit") and s in universities.UNIS]
    if not lines:
        return "Фотографии вузов — из открытых источников."
    return "Фотографии вузов (Wikimedia Commons, свободные лицензии):\n" + "\n".join(lines)
