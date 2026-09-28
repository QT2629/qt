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
    return conn


def _user_hash(user_id: int) -> str:
    return hashlib.sha256(f"pro4u:{user_id}".encode()).hexdigest()[:16]


def log_event(user_id: int, kind: str, detail: str = "", cost: float = 0.0) -> None:
    """kind: button, ai, quiz_done, limit, feedback_up, feedback_down, error."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
            (datetime.now(ALMATY_TZ).isoformat(), _user_hash(user_id), kind, detail, cost),
        )


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
        ai_users = one("SELECT COUNT(DISTINCT user) FROM events WHERE ts >= ? AND kind = 'ai'")
        ai = one("SELECT COUNT(*) FROM events WHERE ts >= ? AND kind = 'ai'")
        cost = one("SELECT SUM(cost) FROM events WHERE ts >= ?")
        quiz = one("SELECT COUNT(*) FROM events WHERE ts >= ? AND kind = 'quiz_done'")
        limit = one("SELECT COUNT(DISTINCT user) FROM events WHERE ts >= ? AND kind = 'limit'")
        up = one("SELECT COUNT(*) FROM events WHERE ts >= ? AND kind = 'feedback_up'")
        down = one("SELECT COUNT(*) FROM events WHERE ts >= ? AND kind = 'feedback_down'")
        errors = one("SELECT COUNT(*) FROM events WHERE ts >= ? AND kind = 'error'")
        buttons = conn.execute(
            "SELECT detail, COUNT(*) FROM events WHERE ts >= ? AND kind = 'button' "
            "GROUP BY detail ORDER BY 2 DESC", (since,)
        ).fetchall()

    period = "сегодня (24 ч)" if days == 1 else f"за {days} дней"
    lines = [
        f"📊 Статистика {period}",
        f"Людей: {users:.0f} (задавали вопросы ИИ: {ai_users:.0f})",
        f"Вопросов к ИИ: {ai:.0f}" + (f", в среднем {ai / ai_users:.1f} на человека" if ai_users else ""),
        f"Анкет пройдено: {quiz:.0f}",
        f"Расходы на Claude: ~${cost:.2f}" + (f" (~${cost / users:.3f} на человека)" if users else ""),
        f"Упёрлись в дневной лимит: {limit:.0f} чел.",
        f"Оценки ответов: 👍 {up:.0f} / 👎 {down:.0f}",
        f"Ошибки: {errors:.0f}",
    ]
    if buttons:
        lines.append("\nКнопки без ИИ:")
        lines += [f"• {name}: {count}" for name, count in buttons]
    return "\n".join(lines)
