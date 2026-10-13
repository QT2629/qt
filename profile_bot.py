# Личная страница в боте: «👤 Мой профиль».
# Профиль заполняется один раз (имя, возраст, город, предметы ЕНТ, вуз и специальность, какое ЕНТ сдаёт),
# дальше бот помнит его и не спрашивает снова. Сюда же вносятся баллы пробных тестов и ЕНТ,
# отсюда — график роста и напоминания о регистрации и тестировании.
import logging
import re

from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup as Kb
from telegram.error import Forbidden
from telegram.ext import ContextTypes

import card
import profiles
import universities
from formatting import b, esc

logger = logging.getLogger("pro4u")

WIZARD = ("name", "age", "city", "ent_group", "target_uni", "target_program", "session")

T = {
    "ru": {
        "consent": (
            "👤 <b>Моя страница</b>\n\n"
            "Здесь я запомню твои цели и баллы, чтобы не спрашивать каждый раз: буду напоминать о регистрации на ЕНТ, "
            "считать, сколько дней осталось, и показывать рост баллов по пробным тестам.\n\n"
            "<b>Что сохраню:</b> имя, возраст, город, предметы ЕНТ, вуз и специальность, баллы.\n"
            "<b>Кто видит:</b> только ты. Вузам и другим людям данные не передаются. Для ответов ИИ использую город, "
            "предметы, цель и баллы — без имени и возраста.\n"
            "<b>Удалить всё:</b> в любой момент командой /delete_me.\n\n"
            "Если тебе меньше 18 — можно указать только имя без фамилии."
        ),
        "mocks_intro": (
            "📈 <b>Статистика пробных тестов</b>\n\n"
            "Вноси баллы каждого пробника — общий балл или по предметам. Я покажу:\n"
            "• <b>график роста</b> от первого теста до последнего;\n"
            "• <b>лучший балл</b> и на сколько вырос результат;\n"
            "• <b>где больше всего можно добрать</b> — какие предметы проседают;\n"
            "• <b>сколько не хватает до гранта</b> в выбранный вуз по баллам 2026 года;\n"
            "• раз в две недели напомню внести новый пробник.\n\n"
            "Для этого нужна твоя страница: нажми «Начать» — это займёт минуту."
        ),
        "mocks_start": "📈 Начать", "mocks_has": "📈 <b>Мои пробники</b>",
        "agree": "✅ Согласен(на), начать", "later": "Не сейчас",
        "later_ok": "Хорошо. Страница будет ждать — кнопка «👤 Мой профиль».",
        "q_name": "Как тебя зовут? Напиши имя (и фамилию, если хочешь).",
        "q_age": "Сколько тебе лет? Напиши число.",
        "q_city": "Из какого ты города (или района)?",
        "q_ent_group": "Какие у тебя профильные предметы ЕНТ?",
        "q_target_uni": "В какой вуз хочешь поступить? Если вуза нет в списке — нажми «Другой» и напиши название.",
        "q_target_uni_text": "Напиши название вуза.",
        "q_target_program": "На какую специальность? Напиши название, например: «IT», «Финансы», «Психология».",
        "q_session": "Какие ЕНТ будешь сдавать? Можно выбрать несколько — отметь все и нажми «Готово».",
        "q_ent_which": "Какое это было ЕНТ?", "s_other": "Другое / не помню", "done": "✅ Готово",
        "s_none": "не выбрано",
        "q_exam_date": "Напиши дату своего ЕНТ, например: 15.05 (дату и время видно в UTO после регистрации). "
                       "Если сдаёшь несколько ЕНТ — внеси каждую дату по очереди.",
        "b_clear_dates": "🗑 Очистить мои даты", "dates_cleared": "Даты ЕНТ удалены.",
        "q_score_mock": (
            "Внеси баллы пробного теста.\n\n"
            "Одним числом — общий балл, например: <b>104</b>\n"
            "Или по частям через пробел (мат. грамотность, чтение, история Казахстана, профиль 1, профиль 2): "
            "<b>8 9 15 38 34</b> — так я покажу, где больше всего можно добрать."
        ),
        "q_score_ent": (
            "Внеси баллы ЕНТ.\n\n"
            "Одним числом — общий балл, например: <b>118</b>\n"
            "Или по частям через пробел (мат. грамотность, чтение, история Казахстана, профиль 1, профиль 2): "
            "<b>9 9 17 42 41</b>"
        ),
        "bad_age": "Напиши возраст числом, например: 17",
        "bad_date": "Не понял дату. Напиши так: 15.05 или 15.05.2027",
        "bad_score": "Не понял баллы. Напиши общий балл (0–140) или пять чисел через пробел: 8 9 15 38 34 "
                     "(максимум 10, 10, 20, 50, 50).",
        "skip": "Пропустить", "other": "Другой вуз", "undecided": "Ещё не решил(а)",
        "s_jan": "Январское", "s_mar": "Мартовское", "s_main": "Основное (грантовое)", "s_unknown": "Пока не знаю",
        "saved": "Сохранено ✅",
        "title": "👤 <b>{name}</b>", "no_name": "Моя страница",
        "age": "{n} лет", "city": "г. {c}",
        "ent": "📝 ЕНТ: {v}", "target": "🎯 Цель: {v}",
        "grant_ok": "🏆 Грант 2026 в {uni} ({gop}): от {min} — твоего лучшего балла <b>{best}</b> хватило бы ✅",
        "grant_gap": "🏆 Грант 2026 в {uni} ({gop}): от {min} — до него <b>{gap}</b> {balls} (лучший балл {best})",
        "grant_only": "🏆 Грант 2026 в {uni} ({gop}): от {min}",
        "grant_none": "🏆 В 2026 году грантов в {uni} по этой группе не было (по стране от {kz})",
        "session_line": "📅 {name} — {status}", "approx": " <i>(ориентировочно)</i>",
        "st_before_reg": "регистрация откроется через {d} ({date})", "st_reg": "идёт регистрация, осталось {d} (до {date})",
        "st_reg_open": "идёт регистрация; тестирование с {date}", "st_before_test": "тестирование начнётся через {d} ({date})",
        "st_test": "идёт тестирование (до {date})", "st_done": "завершено",
        "exam": "🗓 Твоя дата ЕНТ: <b>{date}</b> — {left}", "exam_left": "через {d}", "exam_today": "сегодня! Удачи 🙌",
        "exam_past": "прошла",
        "scores": "📈 Пробных тестов: {n}{last}", "scores_last": ", последний — <b>{v}</b>{delta}",
        "scores_ent": "🎓 ЕНТ: <b>{v}</b>", "no_scores": "📈 Баллов пока нет — внеси пробный тест.",
        "remind_on": "🔔 Напоминания включены", "remind_off": "🔕 Напоминания выключены",
        "b_card": "🪪 Моя карточка",
        "c_ent": "Предметы ЕНТ", "c_target": "Цель", "c_grant": "Грант 2026 в {uni}", "c_best": "Баллы",
        "c_next": "Ближайший срок", "c_grant_ok": "от {min} — твоего балла хватает", "c_grant_gap": "от {min} — не хватает {gap}",
        "c_grant_only": "от {min}", "c_grant_none": "грантов в этот вуз не было", "c_best_v": "лучший {best} · последний {last}",
        "c_delta": " · {sign}{d} с первого", "c_spark": "Пробные тесты и ЕНТ", "c_footer": "Данные из профиля Pro4U · {date}",
        "c_reg": "{name}: регистрация {when}", "c_test": "{name}: тестирование {when}", "c_exam": "Моё ЕНТ: {date} ({when})",
        "c_in": "через {d}", "c_today": "сегодня",
        "b_mock": "➕ Пробный тест", "b_ent": "➕ Результат ЕНТ", "b_progress": "📈 Мой прогресс",
        "b_exam": "🗓 Дата моего ЕНТ", "b_edit": "✏️ Изменить данные", "b_remind_off": "🔕 Выключить напоминания",
        "b_remind_on": "🔔 Включить напоминания", "b_delete": "🗑 Удалить мои данные", "b_back": "↩️ К странице",
        "b_undo": "↩️ Удалить последний результат", "b_chance": "🎯 Шанс на грант с этим баллом",
        "edit_which": "Что изменить?",
        "f_name": "Имя", "f_age": "Возраст", "f_city": "Город", "f_ent_group": "Предметы ЕНТ", "f_target_uni": "Вуз",
        "f_target_program": "Специальность", "f_session": "Какое ЕНТ",
        "score_saved": "Записал: <b>{v}</b> {balls}{delta}.", "delta_up": " — на {d} больше, чем в прошлый раз 📈",
        "delta_down": " — на {d} меньше, чем в прошлый раз. Бывает — смотри, какой предмет просел.",
        "delta_same": " — как в прошлый раз",
        "progress_title": "📈 <b>Мой прогресс</b>", "progress_empty": "Пока нет баллов. Внеси первый пробный тест — "
                                                                   "дальше покажу рост.",
        "progress_one": "Пока один результат. Внеси ещё один — покажу график.",
        "k_mock": "пробный", "k_ent": "ЕНТ",
        "weak": "\n<b>Где больше всего можно добрать</b> (по последнему тесту с разбивкой):",
        "parts": ("Мат. грамотность", "Грамотность чтения", "История Казахстана", "Профильный 1", "Профильный 2"),
        "delete_q": "Удалить профиль и все баллы? Это нельзя отменить.", "delete_yes": "Да, удалить",
        "deleted": "Готово: профиль, баллы и напоминания удалены. Захочешь вернуться — «👤 Мой профиль».",
        "undone": "Последний результат удалён.",
        "r_reg_start_7": "📅 Через 7 дней ({date}) откроется регистрация на <b>{name}</b>.",
        "r_reg_start_1": "📅 Завтра ({date}) открывается регистрация на <b>{name}</b>.",
        "r_reg_start_0": "📅 Сегодня открылась регистрация на <b>{name}</b>.",
        "r_reg_end": "⏰ До конца регистрации на <b>{name}</b> — {d} (до {date}). Успей подать заявление.",
        "r_how": "\nЗаявление подаётся на app.testcenter.kz или в приложении UTO.",
        "r_test_start": "📝 Через неделю ({date}) начинается <b>{name}</b>. Укажи дату своего тестирования — напомню накануне.",
        "r_exam": "🗓 Твоё ЕНТ через {d} — <b>{date}</b>. Проверь в UTO время и адрес пункта тестирования, "
                  "возьми удостоверение личности.",
        "r_result": "🎓 Как прошло ЕНТ? Внеси баллы — посчитаю шанс на грант и добавлю в график.",
        "r_mock": "📈 Был пробный тест за последние две недели? Внеси баллы — покажу, как растёт результат.",
        "r_off_hint": "\n\nНапоминания можно выключить на странице «👤 Мой профиль».",
    },
    "kz": {
        "consent": (
            "👤 <b>Менің парақшам</b>\n\n"
            "Мұнда мақсаттарың мен баллдарыңды есте сақтаймын, қайта-қайта сұрамаймын: ҰБТ-ға тіркелу туралы еске саламын, "
            "қанша күн қалғанын есептеймін және сынақ тесттері бойынша баллдың өсуін көрсетемін.\n\n"
            "<b>Не сақталады:</b> аты-жөнің, жасың, қалаң, ҰБТ пәндері, ЖОО мен мамандық, баллдар.\n"
            "<b>Кім көреді:</b> тек сен. Деректер ЖОО-ларға және басқа адамдарға берілмейді. ЖИ жауаптары үшін қала, "
            "пәндер, мақсат және баллдар қолданылады — атың мен жасың жоқ.\n"
            "<b>Бәрін өшіру:</b> кез келген уақытта /delete_me командасымен.\n\n"
            "18-ге толмасаң — тек атыңды жазсаң жеткілікті."
        ),
        "mocks_intro": (
            "📈 <b>Сынақ тесттерінің статистикасы</b>\n\n"
            "Әр сынақтың баллын енгіз — жалпы баллды немесе пәндер бойынша. Мен көрсетемін:\n"
            "• алғашқы тесттен соңғысына дейінгі <b>өсу графигі</b>;\n"
            "• <b>ең жоғары балл</b> және нәтиже қаншаға өскені;\n"
            "• <b>қай жерден көбірек балл қосуға болады</b> — қай пәндер төмен;\n"
            "• таңдаған ЖОО-ңа 2026 жылғы баллдар бойынша <b>грантқа қанша жетпейді</b>;\n"
            "• екі апта сайын жаңа сынақты енгізуді еске саламын.\n\n"
            "Ол үшін сенің парақшаң керек: «Бастау» батырмасын бас — бір минут қана."
        ),
        "mocks_start": "📈 Бастау", "mocks_has": "📈 <b>Сынақ нәтижелерім</b>",
        "agree": "✅ Келісемін, бастау", "later": "Кейінірек",
        "later_ok": "Жарайды. Парақша сені күтеді — «👤 Менің профилім» батырмасы.",
        "q_name": "Атың кім? Атыңды (қаласаң, тегіңді де) жаз.",
        "q_age": "Жасың нешеде? Санмен жаз.",
        "q_city": "Қай қаладансың (немесе қай аудан)?",
        "q_ent_group": "ҰБТ бейіндік пәндерің қандай?",
        "q_target_uni": "Қай ЖОО-ға түскің келеді? Тізімде жоқ болса — «Басқа ЖОО» батырмасын басып, атауын жаз.",
        "q_target_uni_text": "ЖОО атауын жаз.",
        "q_target_program": "Қай мамандыққа? Атауын жаз, мысалы: «IT», «Қаржы», «Психология».",
        "q_session": "Қай ҰБТ-ларды тапсырасың? Бірнешеуін таңдауға болады — барлығын белгілеп, «Дайын» батырмасын бас.",
        "q_ent_which": "Бұл қай ҰБТ болды?", "s_other": "Басқа / есімде жоқ", "done": "✅ Дайын",
        "s_none": "таңдалмады",
        "q_exam_date": "ҰБТ күніңді жаз, мысалы: 15.05 (тіркелгеннен кейін күні мен уақыты UTO-да көрінеді). "
                       "Бірнеше ҰБТ тапсырсаң — әр күнді кезекпен енгіз.",
        "b_clear_dates": "🗑 Күндерімді өшіру", "dates_cleared": "ҰБТ күндері өшірілді.",
        "q_score_mock": (
            "Сынақ тестінің баллын енгіз.\n\n"
            "Бір санмен — жалпы балл, мысалы: <b>104</b>\n"
            "Немесе бөліктер бойынша бос орын арқылы (математикалық сауаттылық, оқу сауаттылығы, Қазақстан тарихы, "
            "1-бейіндік, 2-бейіндік): <b>8 9 15 38 34</b> — қай жерден көбірек балл қосуға болатынын көрсетемін."
        ),
        "q_score_ent": (
            "ҰБТ баллын енгіз.\n\n"
            "Бір санмен — жалпы балл, мысалы: <b>118</b>\n"
            "Немесе бөліктер бойынша бос орын арқылы (математикалық сауаттылық, оқу сауаттылығы, Қазақстан тарихы, "
            "1-бейіндік, 2-бейіндік): <b>9 9 17 42 41</b>"
        ),
        "bad_age": "Жасыңды санмен жаз, мысалы: 17",
        "bad_date": "Күнді түсінбедім. Былай жаз: 15.05 немесе 15.05.2027",
        "bad_score": "Баллды түсінбедім. Жалпы баллды (0–140) немесе бос орын арқылы бес сан жаз: 8 9 15 38 34 "
                     "(ең көбі 10, 10, 20, 50, 50).",
        "skip": "Өткізіп жіберу", "other": "Басқа ЖОО", "undecided": "Әлі шешпедім",
        "s_jan": "Қаңтардағы", "s_mar": "Наурыздағы", "s_main": "Негізгі (гранттық)", "s_unknown": "Әлі білмеймін",
        "saved": "Сақталды ✅",
        "title": "👤 <b>{name}</b>", "no_name": "Менің парақшам",
        "age": "{n} жаста", "city": "{c} қ.",
        "ent": "📝 ҰБТ: {v}", "target": "🎯 Мақсат: {v}",
        "grant_ok": "🏆 2026 жылғы грант, {uni} ({gop}): {min} бастап — ең жоғары баллың <b>{best}</b> жеткілікті болар еді ✅",
        "grant_gap": "🏆 2026 жылғы грант, {uni} ({gop}): {min} бастап — тағы <b>{gap}</b> балл керек (ең жоғары баллың {best})",
        "grant_only": "🏆 2026 жылғы грант, {uni} ({gop}): {min} бастап",
        "grant_none": "🏆 2026 жылы бұл топ бойынша {uni}-ға грант берілмеді (ел бойынша {kz} бастап)",
        "session_line": "📅 {name} — {status}", "approx": " <i>(болжамды)</i>",
        "st_before_reg": "тіркелу {d}нен кейін ашылады ({date})", "st_reg": "тіркелу жүріп жатыр, {d} қалды ({date} дейін)",
        "st_reg_open": "тіркелу жүріп жатыр; тестілеу {date} бастап", "st_before_test": "тестілеу {d}нен кейін басталады ({date})",
        "st_test": "тестілеу жүріп жатыр ({date} дейін)", "st_done": "аяқталды",
        "exam": "🗓 Сенің ҰБТ күнің: <b>{date}</b> — {left}", "exam_left": "{d}нен кейін", "exam_today": "бүгін! Сәттілік 🙌",
        "exam_past": "өтті",
        "scores": "📈 Сынақ тесттері: {n}{last}", "scores_last": ", соңғысы — <b>{v}</b>{delta}",
        "scores_ent": "🎓 ҰБТ: <b>{v}</b>", "no_scores": "📈 Әзірге балл жоқ — сынақ тестін енгіз.",
        "remind_on": "🔔 Еске салулар қосулы", "remind_off": "🔕 Еске салулар өшірулі",
        "b_card": "🪪 Менің карточкам",
        "c_ent": "ҰБТ пәндері", "c_target": "Мақсат", "c_grant": "{uni}: 2026 жылғы грант", "c_best": "Баллдар",
        "c_next": "Жақын мерзім", "c_grant_ok": "{min} бастап — баллың жетеді", "c_grant_gap": "{min} бастап — {gap} балл жетпейді",
        "c_grant_only": "{min} бастап", "c_grant_none": "бұл ЖОО-ға грант берілмеді", "c_best_v": "ең жоғары {best} · соңғы {last}",
        "c_delta": " · алғашқыдан {sign}{d}", "c_spark": "Сынақ тесттері мен ҰБТ", "c_footer": "Pro4U профилінің деректері · {date}",
        "c_reg": "{name}: тіркелу {when}", "c_test": "{name}: тестілеу {when}", "c_exam": "Менің ҰБТ-м: {date} ({when})",
        "c_in": "{d}нен кейін", "c_today": "бүгін",
        "b_mock": "➕ Сынақ тесті", "b_ent": "➕ ҰБТ нәтижесі", "b_progress": "📈 Менің прогресім",
        "b_exam": "🗓 ҰБТ күнім", "b_edit": "✏️ Деректерді өзгерту", "b_remind_off": "🔕 Еске салуды өшіру",
        "b_remind_on": "🔔 Еске салуды қосу", "b_delete": "🗑 Деректерімді өшіру", "b_back": "↩️ Парақшаға",
        "b_undo": "↩️ Соңғы нәтижені өшіру", "b_chance": "🎯 Осы баллмен грантқа мүмкіндік",
        "edit_which": "Нені өзгертеміз?",
        "f_name": "Аты", "f_age": "Жасы", "f_city": "Қала", "f_ent_group": "ҰБТ пәндері", "f_target_uni": "ЖОО",
        "f_target_program": "Мамандық", "f_session": "Қай ҰБТ",
        "score_saved": "Жазып алдым: <b>{v}</b> балл{delta}.", "delta_up": " — өткен жолдан {d} балл жоғары 📈",
        "delta_down": " — өткен жолдан {d} балл төмен. Болады — қай пән төмендегенін қара.",
        "delta_same": " — өткен жолғыдай",
        "progress_title": "📈 <b>Менің прогресім</b>", "progress_empty": "Әзірге балл жоқ. Алғашқы сынақ тестін енгіз — "
                                                                        "сосын өсуін көрсетемін.",
        "progress_one": "Әзірге бір нәтиже. Тағы біреуін енгіз — график көрсетемін.",
        "k_mock": "сынақ", "k_ent": "ҰБТ",
        "weak": "\n<b>Қай жерден көбірек балл қосуға болады</b> (бөліктері бар соңғы тест бойынша):",
        "parts": ("Мат. сауаттылық", "Оқу сауаттылығы", "Қазақстан тарихы", "1-бейіндік", "2-бейіндік"),
        "delete_q": "Профиль мен барлық баллдарды өшіреміз бе? Қайтару мүмкін емес.", "delete_yes": "Иә, өшіру",
        "deleted": "Дайын: профиль, баллдар және еске салулар өшірілді. Қайта келгің келсе — «👤 Менің профилім».",
        "undone": "Соңғы нәтиже өшірілді.",
        "r_reg_start_7": "📅 7 күннен кейін ({date}) <b>{name}</b> тіркелуі ашылады.",
        "r_reg_start_1": "📅 Ертең ({date}) <b>{name}</b> тіркелуі ашылады.",
        "r_reg_start_0": "📅 Бүгін <b>{name}</b> тіркелуі ашылды.",
        "r_reg_end": "⏰ <b>{name}</b> тіркелуі аяқталуына {d} қалды ({date} дейін). Өтінішті үлгеріп бер.",
        "r_how": "\nӨтініш app.testcenter.kz сайтында немесе UTO қосымшасында беріледі.",
        "r_test_start": "📝 Бір аптадан кейін ({date}) <b>{name}</b> басталады. Тестілеу күніңді жаз — бір күн бұрын еске саламын.",
        "r_exam": "🗓 Сенің ҰБТ-ң {d}нен кейін — <b>{date}</b>. UTO-да тестілеу пунктінің уақыты мен мекенжайын тексер, "
                  "жеке куәлігіңді ал.",
        "r_result": "🎓 ҰБТ қалай өтті? Баллыңды енгіз — грантқа мүмкіндікті есептеп, графикке қосамын.",
        "r_mock": "📈 Соңғы екі аптада сынақ тесті болды ма? Баллын енгіз — нәтиженің өсуін көрсетемін.",
        "r_off_hint": "\n\nЕске салуларды «👤 Менің профилім» парақшасында өшіруге болады.",
    },
}


def t(lang: str, key: str) -> str:
    return T.get(lang, T["ru"])[key]


def days_word(n: int, lang: str) -> str:
    if lang == "kz":
        return f"{n} күн"
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    return f"{n} дня" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else f"{n} дней"


def balls_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "балл"
    return "балла" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "баллов"


def fmt_date(d) -> str:
    return d.strftime("%d.%m.%Y")


# ---------------------------------------------------------------------------
# Клавиатуры
# ---------------------------------------------------------------------------
def page_keyboard(p: dict, lang: str) -> Kb:
    return Kb([
        [Btn(t(lang, "b_mock"), callback_data="pf:addmock"), Btn(t(lang, "b_ent"), callback_data="pf:addent")],
        [Btn(t(lang, "b_progress"), callback_data="pf:progress"), Btn(t(lang, "b_exam"), callback_data="pf:examdate")],
        [Btn(t(lang, "b_card"), callback_data="pf:card"), Btn(t(lang, "b_edit"), callback_data="pf:edit")],
        [Btn(t(lang, "b_remind_off" if p.get("reminders") else "b_remind_on"), callback_data="pf:remind")],
        [Btn(t(lang, "b_delete"), callback_data="pf:delete")],
    ])


def back_keyboard(lang: str) -> Kb:
    return Kb([[Btn(t(lang, "b_back"), callback_data="pf:show")]])


def skip_keyboard(lang: str) -> Kb:
    return Kb([[Btn(t(lang, "skip"), callback_data="pf:skip")]])


def groups_keyboard(lang: str) -> Kb:
    rows = [[Btn(universities.ENT_LABELS[g][lang], callback_data=f"pf:g:{g}")] for g in universities.all_groups()]
    return Kb(rows + [[Btn(t(lang, "skip"), callback_data="pf:skip")]])


def unis_keyboard(lang: str) -> Kb:
    btns = [Btn(u["short"], callback_data=f"pf:u:{slug}") for slug, u in universities.UNIS.items()]
    rows = [btns[i:i + 3] for i in range(0, len(btns), 3)]
    return Kb(rows + [[Btn(t(lang, "other"), callback_data="pf:u:other"),
                       Btn(t(lang, "undecided"), callback_data="pf:u:none")]])


def sessions_keyboard(lang: str, selected: list[str]) -> Kb:
    """Можно отметить несколько ЕНТ: январское, мартовское и основное — в любом сочетании."""
    mark = lambda k: ("✅ " if k in selected else "▫️ ") + t(lang, f"s_{k}")
    return Kb([[Btn(mark(k), callback_data=f"pf:s:{k}")] for k in profiles.SESSION_ORDER]
              + [[Btn(t(lang, "s_unknown"), callback_data="pf:s:unknown"), Btn(t(lang, "done"), callback_data="pf:s:done")]])


def sessions_label(p: dict, lang: str) -> str:
    chosen = profiles.user_sessions(p)
    return ", ".join(t(lang, f"s_{k}") for k in chosen) if chosen else t(lang, "s_none")


def edit_keyboard(lang: str) -> Kb:
    btns = [Btn(t(lang, f"f_{f}"), callback_data=f"pf:e:{f}") for f in WIZARD]
    return Kb([btns[i:i + 2] for i in range(0, len(btns), 2)] + [[Btn(t(lang, "b_back"), callback_data="pf:show")]])


# ---------------------------------------------------------------------------
# Страница
# ---------------------------------------------------------------------------
def target_grant(p: dict) -> dict | None:
    """Грант 2026 по цели: вуз из базы + специальность (или предметы ЕНТ)."""
    slug = p.get("target_uni")
    if slug not in universities.UNIS:
        return None
    pool = list(universities.UNIS[slug]["programs"].values())
    if p.get("ent_group"):
        pool = [x for x in pool if p["ent_group"] in x["ent_groups"]] or pool
    stems = universities._stems(p.get("target_program") or "")
    if stems:
        scored = sorted(pool, key=lambda x: -universities._score(x, stems))
        if universities._score(scored[0], stems):
            pool = scored[:1]
    grants = [x["grant_2026"] for x in pool if x.get("grant_2026")]
    if not grants:
        return None
    with_count = [g for g in grants if g.get("count")]
    g = min(with_count, key=lambda g: g["min"]) if with_count else grants[0]
    return {"uni": universities.UNIS[slug]["short"], "gop": g["gop"].split()[0], "min": g.get("min") if g.get("count") else None,
            "kz_min": g["kz_min"], "program": pool[0]["name_ru"] if len(pool) == 1 else None}


def uni_label(p: dict) -> str:
    slug = p.get("target_uni") or ""
    if slug in universities.UNIS:
        return universities.UNIS[slug]["short"]
    return slug[6:] if slug.startswith("other:") else ""


def page_text(p: dict, lang: str) -> str:
    rows = profiles.scores(p["user_id"])
    lines = [t(lang, "title").format(name=esc(p.get("name") or t(lang, "no_name")))]
    info = [t(lang, "age").format(n=p["age"]) if p.get("age") else "", t(lang, "city").format(c=esc(p["city"])) if p.get("city") else ""]
    if any(info):
        lines.append(" · ".join(x for x in info if x))
    lines.append("")
    if p.get("ent_group") in universities.ENT_LABELS:
        lines.append(t(lang, "ent").format(v=b(universities.ENT_LABELS[p["ent_group"]][lang])))
    target = " — ".join(b(x) for x in (uni_label(p), p.get("target_program") or "") if x)
    if target:
        lines.append(t(lang, "target").format(v=target))
    best = max((r["total"] for r in rows), default=None)
    g = target_grant(p)
    if g:
        if g["min"] is None:
            lines.append(t(lang, "grant_none").format(uni=g["uni"], kz=g["kz_min"]))
        elif best is None:
            lines.append(t(lang, "grant_only").format(uni=g["uni"], gop=g["gop"], min=g["min"]))
        elif best >= g["min"]:
            lines.append(t(lang, "grant_ok").format(uni=g["uni"], gop=g["gop"], min=g["min"], best=best))
        else:
            gap = g["min"] - best
            lines.append(t(lang, "grant_gap").format(uni=g["uni"], gop=g["gop"], min=g["min"], gap=gap, best=best,
                                                     balls=balls_word(gap)))
    for sk in profiles.user_sessions(p):
        st = profiles.stage(sk)
        status = t(lang, f"st_{st['stage']}").format(d=days_word(st["days"], lang), date=st["date"].strftime("%d.%m"))
        approx = t(lang, "approx") if not profiles.schedule().get("confirmed") and st["stage"] != "done" else ""
        lines.append(t(lang, "session_line").format(name=b(st["name_kz" if lang == "kz" else "name_ru"]), status=status) + approx)
    for exam in profiles.exam_dates(p):
        left = (exam - profiles.today()).days
        when = t(lang, "exam_today") if left == 0 else t(lang, "exam_past") if left < 0 else \
            t(lang, "exam_left").format(d=days_word(left, lang))
        lines.append(t(lang, "exam").format(date=fmt_date(exam), left=when))
    lines.append("")
    mocks = [r for r in rows if r["kind"] == "mock"]
    ents = [r for r in rows if r["kind"] == "ent"]
    if mocks:
        delta = mocks[-1]["total"] - mocks[0]["total"] if len(mocks) > 1 else 0
        dtext = f" ({'+' if delta > 0 else ''}{delta} с первого)" if lang != "kz" and len(mocks) > 1 else \
            (f" (алғашқыдан {'+' if delta > 0 else ''}{delta})" if len(mocks) > 1 else "")
        lines.append(t(lang, "scores").format(n=len(mocks), last=t(lang, "scores_last").format(v=mocks[-1]["total"], delta=dtext)))
    if ents:
        lines.append(t(lang, "scores_ent").format(v=ents[-1]["total"]))
    if not rows:
        lines.append(t(lang, "no_scores"))
    lines.append(t(lang, "remind_on" if p.get("reminders") else "remind_off"))
    return "\n".join(lines)


def card_info(p: dict, lang: str) -> dict:
    """Что показать на карточке пользователя — только главное."""
    rows_db = profiles.scores(p["user_id"])
    info = {"name": p.get("name") or t(lang, "no_name").replace("<b>", "").replace("</b>", ""), "rows": [],
            "totals": [r["total"] for r in rows_db]}
    sub = [t(lang, "age").format(n=p["age"]) if p.get("age") else "", t(lang, "city").format(c=p["city"]) if p.get("city") else ""]
    info["sub"] = " · ".join(x for x in sub if x)
    if p.get("ent_group") in universities.ENT_LABELS:
        info["rows"].append((t(lang, "c_ent"), universities.ENT_LABELS[p["ent_group"]][lang], None))
    target = " — ".join(x for x in (uni_label(p), p.get("target_program") or "") if x)
    slug = p.get("target_uni")
    if target and slug in universities.UNIS:
        target += f" ({universities.UNIS[slug]['city'].split(' (')[0]})"
    if target:
        info["rows"].append((t(lang, "c_target"), target, None))
    best = max(info["totals"], default=None)
    g = target_grant(p)
    if g:
        label = t(lang, "c_grant").format(uni=g["uni"])
        if g["min"] is None:
            info["rows"].append((label, t(lang, "c_grant_none"), None))
        elif best is None:
            info["rows"].append((label, t(lang, "c_grant_only").format(min=g["min"]), None))
        elif best >= g["min"]:
            info["rows"].append((label, t(lang, "c_grant_ok").format(min=g["min"]), "green"))
        else:
            info["rows"].append((label, t(lang, "c_grant_gap").format(min=g["min"], gap=g["min"] - best), "amber"))
    if rows_db:
        first, last = rows_db[0]["total"], rows_db[-1]["total"]
        v = t(lang, "c_best_v").format(best=best, last=last)
        if len(rows_db) > 1:
            v += t(lang, "c_delta").format(sign="+" if last >= first else "", d=last - first)
        info["rows"].append((t(lang, "c_best"), v, None))
    # ближайший срок: регистрация, тестирование или своя дата
    events = []
    today = profiles.today()
    for sk in profiles.user_sessions(p):
        st = profiles.stage(sk)
        name = st["name_kz" if lang == "kz" else "name_ru"]
        when = lambda days, dt: (t(lang, "c_today") if days == 0 else t(lang, "c_in").format(d=days_word(days, lang))) + f", {dt:%d.%m}"
        if st["stage"] == "before_reg":
            events.append((st["days"], t(lang, "c_reg").format(name=name, when=when(st["days"], st["date"]))))
        elif st["stage"] in ("before_test", "reg_open"):
            events.append((st["days"], t(lang, "c_test").format(name=name, when=when(st["days"], st["date"]))))
        elif st["stage"] == "reg":
            events.append((st["days"], t(lang, "st_reg").format(d=days_word(st["days"], lang), date=f"{st['date']:%d.%m}") + f" — {name}"))
    for exam in profiles.exam_dates(p):
        left = (exam - today).days
        if left >= 0:
            events.append((left, t(lang, "c_exam").format(date=f"{exam:%d.%m}",
                                                           when=t(lang, "c_today") if left == 0 else t(lang, "c_in").format(d=days_word(left, lang)))))
    if events:
        info["rows"].append((t(lang, "c_next"), min(events)[1], None))
    info["spark_label"] = t(lang, "c_spark")
    info["footer"] = t(lang, "c_footer").format(date=f"{today:%d.%m.%Y}")
    return info


async def send_card(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str) -> None:
    p = profiles.get(chat_id)
    if p:
        await context.bot.send_photo(chat_id, card.profile_card(card_info(p, lang), lang))


async def show_page(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str, query=None, with_card: bool = False) -> None:
    p = profiles.get(chat_id)
    if not p:
        kb = Kb([[Btn(t(lang, "agree"), callback_data="pf:consent")], [Btn(t(lang, "later"), callback_data="pf:later")]])
        await context.bot.send_message(chat_id, t(lang, "consent"), reply_markup=kb)
        return
    if with_card:
        try:
            await send_card(context, chat_id, lang)
        except Exception:  # карточка — дополнение; страница всё равно придёт текстом
            logger.exception("Не получилось нарисовать карточку пользователя")
    text, kb = page_text(p, lang), page_keyboard(p, lang)
    if query:
        try:
            await query.edit_message_text(text, reply_markup=kb)
            return
        except Exception:  # сообщение слишком старое или не изменилось — отправим новое
            pass
    await context.bot.send_message(chat_id, text, reply_markup=kb)


# ---------------------------------------------------------------------------
# Пошаговое заполнение и ввод текста
# ---------------------------------------------------------------------------
async def ask(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str, field: str) -> None:
    """Задаёт вопрос по полю профиля (или для ввода баллов/даты) и ждёт ответа."""
    context.user_data["pf_await"] = field
    if field == "ent_group":
        await context.bot.send_message(chat_id, t(lang, "q_ent_group"), reply_markup=groups_keyboard(lang))
    elif field == "target_uni":
        await context.bot.send_message(chat_id, t(lang, "q_target_uni"), reply_markup=unis_keyboard(lang))
    elif field == "session":
        selected = profiles.user_sessions(profiles.get(chat_id) or {})
        await context.bot.send_message(chat_id, t(lang, "q_session"), reply_markup=sessions_keyboard(lang, selected))
    elif field in ("mock", "ent"):
        await context.bot.send_message(chat_id, t(lang, f"q_score_{field}"), reply_markup=back_keyboard(lang))
    elif field == "exam_date":
        kb = [[Btn(t(lang, "b_back"), callback_data="pf:show")]]
        if profiles.exam_dates(profiles.get(chat_id) or {}):
            kb.insert(0, [Btn(t(lang, "b_clear_dates"), callback_data="pf:clrdates")])
        await context.bot.send_message(chat_id, t(lang, "q_exam_date"), reply_markup=Kb(kb))
    elif field == "uni_text":
        await context.bot.send_message(chat_id, t(lang, "q_target_uni_text"))
    else:
        kb = None if field == "name" else skip_keyboard(lang)
        await context.bot.send_message(chat_id, t(lang, f"q_{field}"), reply_markup=kb)


async def next_step(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str, done: str) -> None:
    """После ответа: в анкете — следующий вопрос, при правке одного поля — обратно на страницу."""
    if context.user_data.get("pf_wizard") and done in WIZARD and WIZARD.index(done) + 1 < len(WIZARD):
        await ask(context, chat_id, lang, WIZARD[WIZARD.index(done) + 1])
        return
    context.user_data.pop("pf_wizard", None)
    context.user_data.pop("pf_await", None)
    await show_page(context, chat_id, lang)


async def on_text(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str, text: str) -> bool:
    """Ответ на вопрос профиля. False — если сейчас ничего не ждём (тогда это обычный вопрос боту)."""
    field = context.user_data.get("pf_await")
    if not field or not profiles.get(chat_id):
        return False
    text = (text or "").strip()
    if field == "name":
        profiles.update(chat_id, name=text[:60])
    elif field == "age":
        m = re.search(r"\d{1,2}", text)
        if not m or not 10 <= int(m.group()) <= 60:
            await context.bot.send_message(chat_id, t(lang, "bad_age"), reply_markup=skip_keyboard(lang))
            return True
        profiles.update(chat_id, age=int(m.group()))
    elif field == "city":
        profiles.update(chat_id, city=text[:60])
    elif field == "uni_text":
        profiles.update(chat_id, target_uni="other:" + text[:60])
        field = "target_uni"
    elif field == "target_program":
        profiles.update(chat_id, target_program=text[:80])
    elif field == "exam_date":
        d = profiles.parse_date(text)
        if not d:
            await context.bot.send_message(chat_id, t(lang, "bad_date"), reply_markup=back_keyboard(lang))
            return True
        profiles.add_exam_date(chat_id, d)
    elif field in ("mock", "ent"):
        score = profiles.parse_score(text)
        if not score:
            await context.bot.send_message(chat_id, t(lang, "bad_score"), reply_markup=back_keyboard(lang))
            return True
        prev = profiles.scores(chat_id)
        profiles.add_score(chat_id, field, score, session=context.user_data.pop("pf_session", None) if field == "ent" else None)
        context.user_data.pop("pf_await", None)
        await send_score_saved(context, chat_id, lang, score["total"], prev[-1]["total"] if prev else None)
        return True
    else:  # кнопочные поля (предметы, вуз, ЕНТ) — текст не принимаем, напоминаем вопрос
        await ask(context, chat_id, lang, field)
        return True
    await next_step(context, chat_id, lang, field)
    return True


async def send_score_saved(context, chat_id: int, lang: str, total: int, prev: int | None) -> None:
    if prev is None:
        delta = ""
    elif total > prev:
        delta = t(lang, "delta_up").format(d=total - prev)
    elif total < prev:
        delta = t(lang, "delta_down").format(d=prev - total)
    else:
        delta = t(lang, "delta_same")
    p = profiles.get(chat_id)
    rows = [[Btn(t(lang, "b_progress"), callback_data="pf:progress")]]
    if p and p.get("ent_group") in universities.ENT_LABELS:
        rows.append([Btn(t(lang, "b_chance"), callback_data=f"pf:chance:{total}")])
    rows += [[Btn(t(lang, "b_undo"), callback_data="pf:undo")], [Btn(t(lang, "b_back"), callback_data="pf:show")]]
    await context.bot.send_message(chat_id, t(lang, "score_saved").format(v=total, balls=balls_word(total), delta=delta),
                                   reply_markup=Kb(rows))


async def send_progress(context, chat_id: int, lang: str) -> None:
    rows = profiles.scores(chat_id)
    p = profiles.get(chat_id) or {}
    if not rows:
        await context.bot.send_message(chat_id, t(lang, "progress_empty"),
                                       reply_markup=Kb([[Btn(t(lang, "b_mock"), callback_data="pf:addmock")]]))
        return
    lines = [t(lang, "progress_title"), ""]
    for r in rows:
        parts = [r[name] for name, _ in profiles.PARTS]
        detail = f" ({'/'.join(str(x) for x in parts)})" if all(x is not None for x in parts) else ""
        kind = t(lang, "k_ent" if r["kind"] == "ent" else "k_mock")
        if r["kind"] == "ent" and r.get("session") in profiles.SESSION_ORDER:
            kind += f" ({t(lang, 's_' + r['session']).lower()})"
        lines.append(f"• {r['taken_on'][8:10]}.{r['taken_on'][5:7]} · {kind} · <b>{r['total']}</b>{detail}")
    full = [r for r in rows if all(r[name] is not None for name, _ in profiles.PARTS)]
    if full:
        last = full[-1]
        names = list(t(lang, "parts"))
        if p.get("ent_group") in universities.ENT_LABELS:
            pair = universities.ENT_LABELS[p["ent_group"]][lang].split(" + ")
            if len(pair) == 2:
                names[3], names[4] = pair
        lost = sorted(((mx - last[name], names[i], last[name], mx) for i, (name, mx) in enumerate(profiles.PARTS)),
                      reverse=True)
        lines.append(t(lang, "weak"))
        lines += [f"• {esc(n)}: {v}/{mx} — {'можно добрать' if lang != 'kz' else 'қосуға болады'} {gap}"
                  for gap, n, v, mx in lost[:3] if gap > 0]
    if len(rows) == 1:
        lines.append("\n" + t(lang, "progress_one"))
    await context.bot.send_message(chat_id, "\n".join(lines), reply_markup=back_keyboard(lang))
    g = target_grant(p) if p else None
    png = card.progress_chart(rows, lang, {"uni": g["uni"], "min": g["min"]} if g and g.get("min") else None)
    if png:
        await context.bot.send_photo(chat_id, png)


# ---------------------------------------------------------------------------
# Кнопки pf:*
# ---------------------------------------------------------------------------
async def on_callback(update, context: ContextTypes.DEFAULT_TYPE, lang: str, send_chances) -> None:
    query = update.callback_query
    data = query.data
    chat_id = update.effective_chat.id
    p = profiles.get(chat_id)

    if data == "pf:consent":
        profiles.create(chat_id, lang)
        context.user_data["pf_wizard"] = True
        await query.edit_message_reply_markup(reply_markup=None)
        await ask(context, chat_id, lang, "name")
        return
    if data == "pf:mocks_start":  # из «Мои пробники» → согласие и анкета
        await query.edit_message_reply_markup(reply_markup=None)
        await show_page(context, chat_id, lang)
        return
    if data == "pf:later":
        await query.edit_message_text(t(lang, "later_ok"))
        return
    if not p:  # профиль удалён, а кнопки остались
        await show_page(context, chat_id, lang)
        return

    if data == "pf:show":
        context.user_data.pop("pf_await", None)
        context.user_data.pop("pf_wizard", None)
        await show_page(context, chat_id, lang, query)
    elif data == "pf:skip":
        field = context.user_data.get("pf_await")
        if field:
            await next_step(context, chat_id, lang, field)
    elif data.startswith("pf:g:"):
        profiles.update(chat_id, ent_group=data[5:])
        await query.edit_message_text(f"{t(lang, 'q_ent_group')}\n{b(universities.ENT_LABELS[data[5:]][lang])}")
        await next_step(context, chat_id, lang, "ent_group")
    elif data.startswith("pf:u:"):
        choice = data[5:]
        if choice == "other":
            await ask(context, chat_id, lang, "uni_text")
            return
        profiles.update(chat_id, target_uni=None if choice == "none" else choice)
        label = t(lang, "undecided") if choice == "none" else universities.UNIS[choice]["short"]
        await query.edit_message_text(f"{t(lang, 'q_target_uni').split('?')[0]}?\n{b(label)}")
        await next_step(context, chat_id, lang, "target_uni")
    elif data.startswith("pf:s:"):
        choice = data[5:]
        selected = profiles.user_sessions(p)
        if choice in profiles.SESSION_ORDER:      # отметить / снять
            selected = [k for k in selected if k != choice] if choice in selected else selected + [choice]
            profiles.update(chat_id, session=",".join(selected) or None)
            await query.edit_message_reply_markup(reply_markup=sessions_keyboard(lang, profiles.user_sessions(profiles.get(chat_id))))
            return
        if choice == "unknown":
            profiles.update(chat_id, session=None)
        p = profiles.get(chat_id)
        await query.edit_message_text(f"{t(lang, 'q_session').split('?')[0]}?\n{b(sessions_label(p, lang))}")
        await next_step(context, chat_id, lang, "session")
    elif data == "pf:addmock":
        await ask(context, chat_id, lang, "mock")
    elif data == "pf:addent":
        options = profiles.user_sessions(p) or list(profiles.SESSION_ORDER)
        kb = [[Btn(t(lang, f"s_{k}"), callback_data=f"pf:es:{k}")] for k in options]
        kb.append([Btn(t(lang, "s_other"), callback_data="pf:es:other")])
        await context.bot.send_message(chat_id, t(lang, "q_ent_which"), reply_markup=Kb(kb))
    elif data.startswith("pf:es:"):
        context.user_data["pf_session"] = None if data[6:] == "other" else data[6:]
        await ask(context, chat_id, lang, "ent")
    elif data == "pf:clrdates":
        profiles.update(chat_id, exam_date=None)
        await query.edit_message_text(t(lang, "dates_cleared"), reply_markup=back_keyboard(lang))
    elif data == "pf:examdate":
        await ask(context, chat_id, lang, "exam_date")
    elif data == "pf:card":
        await send_card(context, chat_id, lang)
    elif data == "pf:progress":
        await send_progress(context, chat_id, lang)
    elif data == "pf:edit":
        await query.edit_message_text(t(lang, "edit_which"), reply_markup=edit_keyboard(lang))
    elif data.startswith("pf:e:"):
        context.user_data.pop("pf_wizard", None)
        await ask(context, chat_id, lang, data[5:])
    elif data == "pf:remind":
        profiles.update(chat_id, reminders=0 if p.get("reminders") else 1)
        await show_page(context, chat_id, lang, query)
    elif data == "pf:undo":
        profiles.delete_last_score(chat_id)
        await query.edit_message_text(t(lang, "undone"), reply_markup=back_keyboard(lang))
    elif data == "pf:delete":
        await query.edit_message_text(t(lang, "delete_q"), reply_markup=Kb(
            [[Btn(t(lang, "delete_yes"), callback_data="pf:delete_yes")], [Btn(t(lang, "b_back"), callback_data="pf:show")]]))
    elif data == "pf:delete_yes":
        profiles.delete(chat_id)
        context.user_data.pop("pf_await", None)
        await query.edit_message_text(t(lang, "deleted"))
    elif data.startswith("pf:chance:") and p.get("ent_group") in universities.ENT_LABELS:
        await send_chances(context, chat_id, lang, p["ent_group"], int(data.split(":")[2]))


async def show_mocks(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str) -> None:
    """Кнопка «📈 Мои пробники»: нет страницы — объясняем, что умеет статистика; есть — показываем прогресс."""
    if not profiles.get(chat_id):
        await context.bot.send_message(chat_id, t(lang, "mocks_intro"),
                                       reply_markup=Kb([[Btn(t(lang, "mocks_start"), callback_data="pf:mocks_start")]]))
        return
    if profiles.scores(chat_id):
        await send_progress(context, chat_id, lang)
    await context.bot.send_message(chat_id, t(lang, "mocks_has"), reply_markup=Kb([
        [Btn(t(lang, "b_mock"), callback_data="pf:addmock"), Btn(t(lang, "b_ent"), callback_data="pf:addent")],
        [Btn(t(lang, "b_back"), callback_data="pf:show")]]))


async def delete_me(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str) -> None:
    """/delete_me — удалить все личные данные."""
    profiles.delete(chat_id)
    context.user_data.pop("pf_await", None)
    await context.bot.send_message(chat_id, t(lang, "deleted"))


def ai_context(chat_id: int) -> str | None:
    """Что ИИ знает о человеке (без имени и возраста) — чтобы советовать лично и не переспрашивать."""
    p = profiles.get(chat_id)
    if not p:
        return None
    rows = profiles.scores(chat_id)
    facts = []
    if p.get("city"):
        region = universities.region_of(p["city"])
        near = (f"в базе есть вузы этого города ({universities.REGION_NAMES[region]})" if region
                else "в его городе вузов из базы нет — учёба будет в другом городе (Алматы или Астана)")
        facts.append(f"город: {p['city']} ({near})")
    if p.get("ent_group") in universities.ENT_LABELS:
        facts.append(f"профильные предметы ЕНТ: {universities.ENT_LABELS[p['ent_group']]['ru']}")
    if uni_label(p):
        facts.append(f"хочет поступить в: {uni_label(p)}")
    if p.get("target_program"):
        facts.append(f"специальность: {p['target_program']}")
    chosen = profiles.user_sessions(p)
    if chosen:
        facts.append("сдаёт ЕНТ: " + ", ".join(profiles.schedule()["sessions"][k]["name_ru"] for k in chosen))
    if rows:
        facts.append("баллы (дата, вид, общий): " + "; ".join(
            f"{r['taken_on']} {'ЕНТ' if r['kind'] == 'ent' else 'пробный'} {r['total']}" for r in rows[-8:]))
    return "; ".join(facts) or None


# ---------------------------------------------------------------------------
# Ежедневные напоминания
# ---------------------------------------------------------------------------
def reminder_text(kind: str, data: dict, lang: str, confirmed: bool) -> tuple[str, Kb | None]:
    name = data.get("name_kz" if lang == "kz" else "name_ru", "")
    d = data.get("date")
    date_s = d.strftime("%d.%m") if d else ""
    approx = "" if confirmed or kind in ("exam", "ask_result") else t(lang, "approx")
    if kind == "reg_start":
        text = t(lang, f"r_reg_start_{data['days']}").format(date=date_s, name=name) + approx + t(lang, "r_how")
        kb = None
    elif kind == "reg_end":
        text = t(lang, "r_reg_end").format(name=name, d=days_word(data["days"], lang), date=date_s) + approx + t(lang, "r_how")
        kb = None
    elif kind == "test_start":
        text = t(lang, "r_test_start").format(date=date_s, name=name) + approx
        kb = Kb([[Btn(t(lang, "b_exam"), callback_data="pf:examdate")]])
    elif kind == "exam":
        text = t(lang, "r_exam").format(d=days_word(data["days"], lang), date=fmt_date(d))
        kb = None
    else:  # ask_result
        text = t(lang, "r_result")
        kb = Kb([[Btn(t(lang, "b_ent"), callback_data="pf:addent")]])
    return text + t(lang, "r_off_hint"), kb


async def daily_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запускается раз в день (10:00 по Алматы): сроки ЕНТ, дата экзамена, просьба внести баллы."""
    confirmed = bool(profiles.schedule().get("confirmed"))
    sent = 0
    for p in profiles.all_with_reminders():
        lang = p.get("lang") or "ru"
        messages = []
        for key, kind, data in profiles.due_reminders(p):
            if profiles.mark_sent(p["user_id"], key):
                messages.append(reminder_text(kind, data, lang, confirmed))
        chosen = profiles.user_sessions(p)
        all_done = bool(chosen) and all(profiles.stage(k)["stage"] == "done" for k in chosen)
        new = (profiles.today() - profiles._d(p["created_at"][:10])).days < 7
        if not messages and not new and not all_done and profiles.mock_nudge_due(p["user_id"]):
            messages.append((t(lang, "r_mock") + t(lang, "r_off_hint"),
                             Kb([[Btn(t(lang, "b_mock"), callback_data="pf:addmock")]])))
        for text, kb in messages:
            try:
                await context.bot.send_message(p["user_id"], text, reply_markup=kb)
                sent += 1
            except Forbidden:  # пользователь остановил бота — больше не пишем
                profiles.update(p["user_id"], reminders=0)
                break
            except Exception:
                logger.exception("Не отправилось напоминание пользователю")
    logger.info("Напоминания: отправлено %s", sent)
