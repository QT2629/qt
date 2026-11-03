# Статистика бота в маленькой базе SQLite (файл data/stats.db).
# Хранит только события, без текстов сообщений. Вместо Telegram ID — его хеш,
# чтобы в базе не было личных данных.
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config

DB_PATH = Path(config.DATA_DIR) / "stats.db"
ALMATY_TZ = timezone(timedelta(hours=5))

# Цены за 1 млн токенов, $: (вход, ответ, чтение кэша, запись кэша на 1 час).
PRICES = {
    "claude-haiku-4-5": (1.0, 5.0, 0.10, 2.0),
    "claude-sonnet-5": (2.0, 10.0, 0.20, 4.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 10.0),
}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS events (
            ts TEXT, user TEXT, kind TEXT, detail TEXT, cost REAL DEFAULT 0
        )"""
    )
    # Напоминания шлёт бот, а не человек, поэтому они отдельно: иначе каждый получатель считался бы активным.
    conn.execute("CREATE TABLE IF NOT EXISTS reminders (ts TEXT, user TEXT, kind TEXT)")
    return conn


def _user_hash(user_id: int) -> str:
    return hashlib.sha256(f"pro4u:{user_id}".encode()).hexdigest()[:16]


def log_event(user_id: int, kind: str, detail: str = "", cost: float = 0.0) -> None:
    """kind: start, button, ai, chance, card, ref_join, src_join, quiz_done, limit, error."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
            (datetime.now(ALMATY_TZ).isoformat(), _user_hash(user_id), kind, detail, cost),
        )


def log_reminder(user_id: int, kind: str) -> None:
    """Напоминание отправлено. kind: mock, а также виды сроков ЕНТ из profiles.due_reminders."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO reminders VALUES (?, ?, ?)",
            (datetime.now(ALMATY_TZ).isoformat(), _user_hash(user_id), kind),
        )


def ref_code(user_id: int) -> str:
    """Код для пригласительной ссылки: тот же хеш, что в статистике, — Telegram ID наружу не попадает."""
    return _user_hash(user_id)


def request_cost(model: str, usage) -> float:
    """Примерная стоимость одного запроса к Claude в долларах."""
    price_in, price_out, price_read, price_write = PRICES.get(model, PRICES["claude-opus-5"])
    return (
        usage.input_tokens * price_in
        + usage.output_tokens * price_out
        + (usage.cache_read_input_tokens or 0) * price_read
        + (usage.cache_creation_input_tokens or 0) * price_write
    ) / 1_000_000


def report(days: int) -> str:
    since = (datetime.now(ALMATY_TZ) - timedelta(days=days)).isoformat()
    with _connect() as conn:
        def one(sql: str) -> float:
            return conn.execute(sql, (since,)).fetchone()[0] or 0

        users = one("SELECT COUNT(DISTINCT user) FROM events WHERE ts >= ?")
        new = one("SELECT COUNT(*) FROM (SELECT user FROM events GROUP BY user HAVING MIN(ts) >= ?)")
        ai_users = one("SELECT COUNT(DISTINCT user) FROM events WHERE ts >= ? AND kind = 'ai'")
        ai = one("SELECT COUNT(*) FROM events WHERE ts >= ? AND kind = 'ai'")
        cost = one("SELECT SUM(cost) FROM events WHERE ts >= ?")
        chances = one("SELECT COUNT(*) FROM events WHERE ts >= ? AND kind = 'chance'")
        refs = one("SELECT COUNT(*) FROM events WHERE ts >= ? AND kind = 'ref_join'")
        top_ref = conn.execute(
            "SELECT detail, COUNT(*) FROM events WHERE ts >= ? AND kind = 'ref_join' "
            "GROUP BY detail ORDER BY 2 DESC LIMIT 1", (since,)
        ).fetchone()
        sources = conn.execute(
            "SELECT detail, COUNT(*) FROM events WHERE ts >= ? AND kind = 'src_join' "
            "GROUP BY detail ORDER BY 2 DESC", (since,)
        ).fetchall()
        quiz = one("SELECT COUNT(*) FROM events WHERE ts >= ? AND kind = 'quiz_done'")
        limit = one("SELECT COUNT(DISTINCT user) FROM events WHERE ts >= ? AND kind = 'limit'")
        errors = one("SELECT COUNT(*) FROM events WHERE ts >= ? AND kind = 'error'")
        reminders = one("SELECT COUNT(*) FROM reminders WHERE ts >= ?")
        mock_sent = one("SELECT COUNT(*) FROM reminders WHERE ts >= ? AND kind = 'mock'")
        clicks = one("SELECT COUNT(*) FROM events WHERE ts >= ? AND kind = 'reminder_click'")
        mock_clicks = one("SELECT COUNT(*) FROM events WHERE ts >= ? AND kind = 'reminder_click' AND detail = 'addmock'")
        buttons = conn.execute(
            "SELECT detail, COUNT(*) FROM events WHERE ts >= ? AND kind = 'button' "
            "GROUP BY detail ORDER BY 2 DESC", (since,)
        ).fetchall()

    period = f"за {days} дней"
    lines = [
        f"📊 Статистика {period}",
        f"Людей: {users:.0f} — впервые за период {new:.0f}, пришли ещё до него {users - new:.0f} "
        f"(задавали вопросы ИИ: {ai_users:.0f}). Возвраты внутри периода — в блоке «Удержание».",
        f"Вопросов к ИИ: {ai:.0f}" + (f", в среднем {ai / ai_users:.1f} на человека" if ai_users else ""),
        f"Анкет пройдено: {quiz:.0f}",
        f"Расходы на Claude: ~${cost:.2f}" + (f" (~${cost / users:.3f} на человека)" if users else ""),
        f"Расчётов «Шанс на грант»: {chances:.0f}",
        f"Пришли по приглашению: {refs:.0f}" + (f" (больше всех привёл один человек: {top_ref[1]})" if top_ref else ""),
        f"Упёрлись в дневной лимит: {limit:.0f} чел.",
        f"Ошибки: {errors:.0f}",
        f"Напоминаний отправлено: {reminders:.0f}, нажали кнопку под ними: {clicks:.0f}; "
        f"про пробник — {mock_sent:.0f}, из них нажали «внести баллы»: {mock_clicks:.0f}",
    ]
    if sources:
        lines.append("\nПришли по ссылкам партнёров:")
        lines += [f"• {name}: {count}" for name, count in sources]
    if buttons:
        lines.append("\nКнопки без ИИ:")
        lines += [f"• {name}: {count}" for name, count in buttons]
    return "\n".join(lines)


def retention() -> str:
    """Удержание: вернулся ли человек в другой день после первого. Дни — по Алматы, от первого события человека."""
    today = datetime.now(ALMATY_TZ).date()
    with _connect() as conn:
        rows = conn.execute("SELECT DISTINCT user, substr(ts, 1, 10) FROM events").fetchall()
        sources = dict(conn.execute("SELECT user, detail FROM events WHERE kind = 'src_join'").fetchall())

    active_days: dict[str, list] = {}
    for user, day in rows:
        active_days.setdefault(user, []).append(datetime.strptime(day, "%Y-%m-%d").date())
    # user -> (сколько дней назад пришёл, на какие дни после первого заходил)
    people = {}
    for user, days in active_days.items():
        first = min(days)
        people[user] = ((today - first).days, sorted((d - first).days for d in days if d != first))

    def share(min_age: int, came_back) -> str:
        base = [offsets for age, offsets in people.values() if age >= min_age]
        if not base:
            return "пока мало данных"
        n = sum(1 for offsets in base if came_back(offsets))
        return f"{n} из {len(base)} ({n / len(base):.0%})"

    lines = [
        "🔁 Удержание (по людям, у кого прошло достаточно дней):",
        f"• пришли снова в любой другой день: {share(1, lambda o: bool(o))}",
        f"• пришли снова в первые 7 дней: {share(7, lambda o: any(1 <= d <= 7 for d in o))}",
        f"• пришли снова позже недели: {share(14, lambda o: any(d > 7 for d in o))}",
    ]
    by_source: dict[str, list[int]] = {}
    for user, name in sources.items():
        if user in people and people[user][0] >= 1:
            by_source.setdefault(name, []).append(1 if people[user][1] else 0)
    if by_source:
        lines.append("\nПо ссылкам партнёров (вернулись / пришли):")
        lines += [f"• {name}: {sum(v)} / {len(v)}" for name, v in sorted(by_source.items())]
    return "\n".join(lines)


MONTHS_RU = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь",
             "ноябрь", "декабрь"]


def overview(months: int = 6) -> str:
    """Сколько людей пользуется ботом: за 30 дней и по календарным месяцам."""
    now = datetime.now(ALMATY_TZ)
    with _connect() as conn:
        def active(days: int) -> int:
            since = (now - timedelta(days=days)).isoformat()
            return conn.execute("SELECT COUNT(DISTINCT user) FROM events WHERE ts >= ?", (since,)).fetchone()[0]

        # Месяц — по времени Алматы (ts хранится с поясом +05:00, первые 7 символов — «ГГГГ-ММ»).
        by_month = dict((m, (u, 0)) for m, u in conn.execute(
            "SELECT substr(ts, 1, 7), COUNT(DISTINCT user) FROM events GROUP BY 1").fetchall())
        for m, n in conn.execute(
                "SELECT substr(first, 1, 7), COUNT(*) FROM (SELECT MIN(ts) AS first FROM events GROUP BY user) GROUP BY 1"):
            by_month[m] = (by_month.get(m, (0, 0))[0], n)

    lines = ["👥 Пользователи", f"За 30 дней: {active(30)}", "", "По месяцам (активные / из них новые):"]
    for i in range(months):
        y, m = now.year, now.month - i
        while m <= 0:
            y, m = y - 1, m + 12
        key = f"{y}-{m:02d}"
        users, new = by_month.get(key, (0, 0))
        lines.append(f"• {MONTHS_RU[m - 1]} {y}{' (идёт сейчас)' if i == 0 else ''}: {users} / {new}")
    return "\n".join(lines)

