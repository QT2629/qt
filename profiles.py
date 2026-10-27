# Личная страница пользователя: профиль, баллы пробных тестов и ЕНТ, напоминания о сроках.
# Хранится в маленькой базе SQLite (data/profiles.db) — переживает перезапуски бота на Railway.
# Данные личные: сохраняем только после согласия пользователя, удаляются командой /delete_me.
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import config

DB_PATH = Path(config.DATA_DIR) / "profiles.db"
SCHEDULE_PATH = Path(__file__).parent / "knowledge" / "ent_schedule.json"
ALMATY_TZ = timezone(timedelta(hours=5))

FIELDS = ("name", "age", "city", "ent_group", "target_uni", "target_program", "quota", "session", "exam_date")
# Баллы ЕНТ по частям: (поле, максимум). Сумма — 140.
PARTS = (("math_lit", 10), ("reading", 10), ("history", 20), ("prof1", 50), ("prof2", 50))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER PRIMARY KEY, lang TEXT, name TEXT, age INTEGER, city TEXT, ent_group TEXT,
            target_uni TEXT, target_program TEXT, session TEXT, exam_date TEXT,
            reminders INTEGER DEFAULT 1, consent_at TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, taken_on TEXT, total INTEGER,
            math_lit INTEGER, reading INTEGER, history INTEGER, prof1 INTEGER, prof2 INTEGER, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS reminders_sent (user_id INTEGER, key TEXT, sent_at TEXT, PRIMARY KEY (user_id, key));
    """)
    if "session" not in {r[1] for r in conn.execute("PRAGMA table_info(scores)")}:  # какое это было ЕНТ
        conn.execute("ALTER TABLE scores ADD COLUMN session TEXT")
    if "quota" not in {r[1] for r in conn.execute("PRAGMA table_info(profiles)")}:  # квоты: «r,large_family»
        conn.execute("ALTER TABLE profiles ADD COLUMN quota TEXT")
    return conn


SESSION_ORDER = ("jan", "mar", "main")


def user_sessions(p: dict) -> list[str]:
    """Какие ЕНТ человек сдаёт — можно несколько: январское, мартовское, основное (хранится как «jan,main»)."""
    chosen = set((p.get("session") or "").split(","))
    return [k for k in SESSION_ORDER if k in chosen]


def exam_dates(p: dict) -> list[date]:
    """Личные даты тестирования — по одной на каждое ЕНТ (хранятся через запятую)."""
    return sorted({date.fromisoformat(x) for x in (p.get("exam_date") or "").split(",") if x})


def add_exam_date(user_id: int, d: date) -> None:
    p = get(user_id) or {}
    dates = sorted({*exam_dates(p), d})
    update(user_id, exam_date=",".join(x.isoformat() for x in dates))


def today() -> date:
    return datetime.now(ALMATY_TZ).date()


def _now() -> str:
    return datetime.now(ALMATY_TZ).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Профиль
# ---------------------------------------------------------------------------
def get(user_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def create(user_id: int, lang: str) -> None:
    """Пользователь согласился хранить данные — заводим пустой профиль."""
    with _connect() as conn:
        conn.execute("INSERT OR IGNORE INTO profiles (user_id, lang, consent_at, created_at, updated_at) "
                     "VALUES (?, ?, ?, ?, ?)", (user_id, lang, _now(), _now(), _now()))


def update(user_id: int, **values) -> None:
    values = {k: v for k, v in values.items() if k in FIELDS + ("lang", "reminders")}
    if not values:
        return
    sets = ", ".join(f"{k} = ?" for k in values)
    with _connect() as conn:
        conn.execute(f"UPDATE profiles SET {sets}, updated_at = ? WHERE user_id = ?",
                     (*values.values(), _now(), user_id))


def delete(user_id: int) -> None:
    """Удаляет профиль, все баллы и историю напоминаний."""
    with _connect() as conn:
        for table in ("profiles", "scores", "reminders_sent"):
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))


def counts() -> dict:
    """Для /stats: сколько человек завели страницу, внесли баллы, получают напоминания."""
    with _connect() as conn:
        one = lambda sql: conn.execute(sql).fetchone()[0]
        return {"profiles": one("SELECT COUNT(*) FROM profiles"),
                "with_scores": one("SELECT COUNT(DISTINCT user_id) FROM scores"),
                "scores": one("SELECT COUNT(*) FROM scores"),
                "reminders": one("SELECT COUNT(*) FROM profiles WHERE reminders = 1")}


def score_stats() -> str:
    """Только для /stats (видит администратор): баллы пользователей в целом, без имён и без сравнения людей между собой."""
    with _connect() as conn:
        rows = conn.execute("SELECT user_id, kind, total FROM scores ORDER BY user_id, taken_on, id").fetchall()
    if not rows:
        return "📈 Баллы: пока никто не внёс."
    by_user: dict[int, list] = {}
    for r in rows:
        by_user.setdefault(r["user_id"], []).append(r)
    last = [rs[-1]["total"] for rs in by_user.values()]
    growth = [rs[-1]["total"] - rs[0]["total"] for rs in by_user.values() if len(rs) >= 2]
    ent = [r["total"] for r in rows if r["kind"] == "ent"]
    buckets = (("до 60", 0, 59), ("60–79", 60, 79), ("80–99", 80, 99), ("100–119", 100, 119), ("120+", 120, 140))
    lines = [f"📈 Баллы ({len(by_user)} чел.): последний результат в среднем {sum(last) / len(last):.0f}",
             "Распределение последних баллов: " + ", ".join(
                 f"{name} — {sum(lo <= v <= hi for v in last)}" for name, lo, hi in buckets)]
    if growth:
        lines.append(f"Рост с первого теста (у {len(growth)} чел. с 2+ тестами): в среднем {sum(growth) / len(growth):+.0f}")
    if ent:
        lines.append(f"Настоящее ЕНТ внесли {len(ent)} раз, средний балл {sum(ent) / len(ent):.0f}")
    return "\n".join(lines)


def all_with_reminders() -> list[dict]:
    with _connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM profiles WHERE reminders = 1")]


# ---------------------------------------------------------------------------
# Баллы
# ---------------------------------------------------------------------------
def parse_score(text: str) -> dict | None:
    """«112» — общий балл; «8 9 15 40 38» — по частям (мат. грамотность, чтение, история, профиль 1, профиль 2)."""
    nums = [int(x) for x in text.replace(",", " ").replace("/", " ").split() if x.isdigit()]
    if len(nums) == 1 and 0 <= nums[0] <= 140:
        return {"total": nums[0]}
    if len(nums) == len(PARTS) and all(0 <= n <= mx for n, (_, mx) in zip(nums, PARTS)):
        parts = {name: n for n, (name, _) in zip(nums, PARTS)}
        return {"total": sum(nums), **parts}
    return None


def add_score(user_id: int, kind: str, score: dict, taken_on: date | None = None, session: str | None = None) -> None:
    """kind: mock — пробный тест, ent — настоящее ЕНТ (session — какое: jan, mar, main)."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO scores (user_id, kind, taken_on, total, math_lit, reading, history, prof1, prof2, created_at, session) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, kind, (taken_on or today()).isoformat(), score["total"],
             *(score.get(name) for name, _ in PARTS), _now(), session))


def scores(user_id: int) -> list[dict]:
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM scores WHERE user_id = ? ORDER BY taken_on, id", (user_id,))]


def delete_last_score(user_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT id FROM scores WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        if row:
            conn.execute("DELETE FROM scores WHERE id = ?", (row["id"],))
        return bool(row)


# ---------------------------------------------------------------------------
# Сроки ЕНТ и напоминания
# ---------------------------------------------------------------------------
def schedule() -> dict:
    return json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def parse_date(text: str) -> date | None:
    """«15.05», «15.05.2027», «2027-05-15» → дата (без года — ближайшая будущая)."""
    text = text.strip().replace("/", ".").replace("-", ".")
    parts = [p for p in text.split(".") if p]
    try:
        if len(parts) == 3 and len(parts[0]) == 4:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 3:
            year = int(parts[2]) + (2000 if len(parts[2]) == 2 else 0)
            return date(year, int(parts[1]), int(parts[0]))
        if len(parts) == 2:
            d = date(today().year, int(parts[1]), int(parts[0]))
            return d if d >= today() else d.replace(year=d.year + 1)
    except ValueError:
        return None
    return None


def stage(session_key: str, on: date | None = None) -> dict | None:
    """Где сейчас сессия ЕНТ: до регистрации / регистрация / ждём тестирования / тестирование / прошла."""
    s = schedule()["sessions"].get(session_key)
    if not s:
        return None
    on = on or today()
    rs, re_, ts, te = _d(s["reg_start"]), _d(s["reg_end"]), _d(s["test_start"]), _d(s["test_end"])
    if rs and on < rs:
        return {"stage": "before_reg", "days": (rs - on).days, "date": rs, **s}
    if re_ and on <= re_:
        return {"stage": "reg", "days": (re_ - on).days, "date": re_, **s}
    if not re_ and ts and on < ts:   # конец регистрации неизвестен
        return {"stage": "reg_open", "days": (ts - on).days, "date": ts, **s}
    if ts and on < ts:
        return {"stage": "before_test", "days": (ts - on).days, "date": ts, **s}
    if te and on <= te:
        return {"stage": "test", "days": (te - on).days, "date": te, **s}
    return {"stage": "done", "days": 0, "date": te, **s}


def due_reminders(p: dict, on: date | None = None) -> list[tuple[str, str, dict]]:
    """Какие напоминания пора отправить пользователю сегодня: (ключ для «уже отправлено», вид, данные)."""
    on = on or today()
    out = []
    mine = exam_dates(p)
    for sk in user_sessions(p):
        s = schedule()["sessions"][sk]
        rs, re_, ts, te = _d(s["reg_start"]), _d(s["reg_end"]), _d(s["test_start"]), _d(s["test_end"])
        has_date = any(ts <= d <= te for d in mine) if ts and te else False
        for days in (7, 1, 0):
            if rs and (rs - on).days == days:
                out.append((f"{sk}:reg_start:{rs}:{days}", "reg_start", {"days": days, "date": rs, **s}))
        for days in (3, 1):
            if re_ and (re_ - on).days == days:
                out.append((f"{sk}:reg_end:{re_}:{days}", "reg_end", {"days": days, "date": re_, **s}))
        if ts and (ts - on).days == 7 and not has_date:
            out.append((f"{sk}:test_start:{ts}", "test_start", {"days": 7, "date": ts, **s}))
        if te and (on - te).days == 3 and not has_date:   # дату не указал — спросим баллы после сессии
            out.append((f"{sk}:ask_result:{te}", "ask_result", s))
    for exam in mine:
        for days in (7, 3, 1):
            if (exam - on).days == days:
                out.append((f"exam:{exam}:{days}", "exam", {"days": days, "date": exam}))
        if (on - exam).days == 1:
            out.append((f"exam_result:{exam}", "ask_result", {"date": exam}))
    return out


def mark_sent(user_id: int, key: str) -> bool:
    """True — если напоминание ещё не отправлялось (и теперь помечено как отправленное)."""
    with _connect() as conn:
        cur = conn.execute("INSERT OR IGNORE INTO reminders_sent VALUES (?, ?, ?)", (user_id, key, _now()))
        return cur.rowcount == 1


def mock_nudge_due(user_id: int, every_days: int = 14) -> bool:
    """Раз в две недели спрашиваем про пробные тесты (пока не прошли все выбранные ЕНТ — это проверяет бот)."""
    rows = scores(user_id)
    last = max([date.fromisoformat(r["taken_on"]) for r in rows if r["kind"] == "mock"], default=None)
    key = f"mock_nudge:{today().isocalendar()[0]}-{today().isocalendar()[1] // 2}"
    if last and (today() - last).days < every_days:
        return False
    return mark_sent(user_id, key)
