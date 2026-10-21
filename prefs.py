# Человек передумал: «не хочу в КазНУ», «передумала про юриста», «теперь сдаю биологию и химию», «выбрала SDU».
# Бот запоминает это (context.user_data["prefs"]) и сразу подстраивается:
#  • вузы и направления, от которых отказались, не предлагает, пока человек сам о них не спросит;
#  • новый выбор (вуз, специальность, предметы ЕНТ) записывает в личную страницу, если она есть;
#  • ИИ получает эти предпочтения в блоке <user_preferences>.
import re

import profiles
import universities

_NEG = re.compile(r"\b(не\s+хоч\w*|не\s+буду|не\s+пойду|не\s+интерес\w*|не\s+нрав\w*|не\s+подход\w*|не\s+рассматрива\w*|"
                  r"не\s+надо|не\s+нужн\w*|не\s+предлагай\w*|не\s+советуй\w*|не\s+показывай\w*|хватит\s+(?:про|о|об|предлаг\w*|совет\w*)|передумал\w*|"
                  r"разонравил\w*|расхотел\w*|отказал\w*|кроме|без|убери\w*|не\s+хо\b|"
                  r"қаламаймын|керек\s+емес|ұнамайды)", re.I)
_WANT = re.compile(r"\b(хочу|хотела?\s+бы|буду\s+поступать|поступаю|решил\w*|выбрал\w*|мой\s+выбор|теперь|"
                   r"интересует|нравится|склоняюсь|думаю\s+про|лучше|барғым\s+келеді|таңдадым)", re.I)
_ENT_VERB = re.compile(r"\b(сда\w*|буду\s+сдавать|сдавать|выбрал\w*|поменял\w*|теперь|предмет\w*|профил\w*|"
                       r"тапсыр\w*|ауыстыр\w*)", re.I)
# После «хочу на / стать / учиться на» — направление: «хочу на медицину», «хочу стать программистом».
_WANT_TOPIC = re.compile(r"\b(?:хочу|буду\s+поступать|поступаю|решил\w*|выбрал\w*|теперь)\s+(?:\w+\s+)?"
                         r"(?:на|стать|учиться\s+на|в\s+сферу|по)\s+([а-яёa-z][а-яёa-z\- ]{2,40})", re.I)
_CLAUSES = re.compile(r"[.!?;,\n]+|\s+(?:но|однако|зато|а)\s+", re.I)
_ASK = re.compile(r"\?|\b(что|какие|какой|какая|покажи|подбери|посоветуй|есть|варианты|расскажи|сколько|где|"
                  r"қандай|бар\s+ма|көрсет)\b", re.I)
_TOPIC_STOP = {"быть", "учиться", "поступать", "идти", "туда", "больше", "вообще", "совсем", "уже", "вуз", "вуза", "вузы", "университет", "универ", "туда", "этот", "эту", "это", "него", "неё", "нее",
               "платно", "платное", "грант", "далеко", "дорого", "город"}


def get(context) -> dict:
    return context.user_data.setdefault("prefs", {"no_unis": [], "no_topics": []})


def _topic_stems(clause: str) -> list[str]:
    words = [w for w in re.findall(r"[а-яёa-z\-]+", clause.lower()) if w not in _TOPIC_STOP]
    return [s for s in universities._stems(" ".join(words)) if len(s) >= 4]


def update(context, chat_id: int, text: str) -> dict:
    """Разбирает сообщение и обновляет предпочтения и личную страницу. Возвращает, что изменилось."""
    prefs = get(context)
    for k in ("just_rejected", "just_topics", "query"):
        prefs.pop(k, None)
    changed: dict = {}
    rejected_now: list[str] = []
    kept = []  # части сообщения без отказов — по ним и ищем программы («не хочу в КазНУ, там большой конкурс» → ничего)
    profile = profiles.get(chat_id)
    for clause in (c for c in _CLAUSES.split(text) if c and c.strip()):
        slugs = universities.mentioned_unis(clause)
        neg, want = _NEG.search(clause), _WANT.search(clause)
        # По каким частям сообщения искать программы: «кроме Нархоза … по финансам», «хочу на маркетинг»,
        # вопрос. Причину отказа («там слишком большой конкурс») не берём.
        if (neg and re.search(r"\b(кроме|без)\b", neg.group(0), re.I)) or (not neg and (want or _ASK.search(clause))):
            kept.append(clause)
        if slugs and neg:                                            # «не хочу в КазНУ», «кроме Нархоза»
            rejected_now.extend(slugs)
            for s in slugs:
                if s not in prefs["no_unis"]:
                    prefs["no_unis"].append(s)
                    changed.setdefault("no_unis", []).append(s)
            if profile and profile.get("target_uni") in slugs:       # отказался от цели — убираем её со страницы
                profiles.update(chat_id, target_uni=None)
                changed["target_uni"] = None
        elif slugs and want:                                         # «хочу в SDU», «выбрала КБТУ»
            for s in slugs:
                if s in prefs["no_unis"]:
                    prefs["no_unis"].remove(s)
            if len(slugs) == 1 and profile and profile.get("target_uni") != slugs[0]:
                profiles.update(chat_id, target_uni=slugs[0])
                changed["target_uni"] = slugs[0]
        elif neg:                                                    # «передумала про юриста», «не хочу в медицину»
            stems = _topic_stems(_NEG.sub(" ", clause))
            for st in stems:
                if st not in prefs["no_topics"]:
                    prefs["no_topics"].append(st)
                    changed.setdefault("no_topics", []).append(st)
        m = _WANT_TOPIC.search(clause)
        if m and not neg and not slugs:                              # «теперь хочу на медицину»
            stems = _topic_stems(m.group(1))
            prefs["no_topics"] = [x for x in prefs["no_topics"] if x not in stems]
            if profile and stems:
                profiles.update(chat_id, target_program=m.group(1).strip()[:80])
                changed["target_program"] = m.group(1).strip()
        groups = universities._groups(clause)                        # «теперь сдаю биологию и химию»
        if len(groups) == 1 and _ENT_VERB.search(clause) and not neg:
            g = next(iter(groups))
            if profile and profile.get("ent_group") != g:
                profiles.update(chat_id, ent_group=g)
            if context.user_data.get("ent_group") != g:
                context.user_data["ent_group"] = g
                changed["ent_group"] = g
    if rejected_now or changed.get("no_topics"):
        prefs["query"] = " ".join(kept)
    if rejected_now:
        prefs["just_rejected"] = list(dict.fromkeys(rejected_now))
    if changed.get("no_topics"):
        prefs["just_topics"] = changed["no_topics"]
    prefs["no_unis"] = prefs["no_unis"][-15:]
    prefs["no_topics"] = prefs["no_topics"][-20:]
    return changed


def for_ai(context, lang: str = "ru") -> str | None:
    """Блок для ИИ: от чего человек отказался и что выбрал недавно."""
    prefs = get(context)
    parts = []
    if prefs["no_unis"]:
        parts.append("не хочет в эти вузы (не предлагай их, пока сам не спросит): "
                     + ", ".join(universities.UNIS[s]["short"] for s in prefs["no_unis"] if s in universities.UNIS))
    if prefs["no_topics"]:
        parts.append("отказался от направлений со словами: " + ", ".join(prefs["no_topics"]))
    if context.user_data.get("ent_group"):
        parts.append("предметы ЕНТ сейчас: " + universities.ENT_LABELS[context.user_data["ent_group"]]["ru"])
    return "; ".join(parts) or None
