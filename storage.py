import os
import sqlite3
from pathlib import Path

# Keep the existing default database location for compatibility. For persistent
# hosting storage, set DATA_DIR to the host's persistent directory and copy the
# existing vocab.db there before switching this setting.
DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).resolve().parent / "data"))).expanduser()
DB_PATH = DATA_DIR / "vocab.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            korean TEXT NOT NULL,
            uzbek TEXT NOT NULL,
            deck TEXT NOT NULL DEFAULT 'default',
            UNIQUE(user_id, korean, deck)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_meta (
            user_id INTEGER PRIMARY KEY,
            day2_seeded INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS lesson_progress (
            user_id INTEGER NOT NULL, lesson_id INTEGER NOT NULL,
            best_score INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id, lesson_id)
        )"""
    )
    conn.commit()
    return conn


def ensure_day2_seeded(user_id: int) -> int:
    from data.day2 import DAY2_WORDS

    conn = _connect()
    try:
        row = conn.execute("SELECT day2_seeded FROM user_meta WHERE user_id = ?", (user_id,)).fetchone()
        if row and row["day2_seeded"]:
            return 0
        added = 0
        for korean, uzbek in DAY2_WORDS:
            cur = conn.execute(
                "INSERT OR IGNORE INTO words (user_id, korean, uzbek, deck) VALUES (?, ?, ?, ?)",
                (user_id, korean, uzbek, "Day 2"),
            )
            added += cur.rowcount
        conn.execute(
            """INSERT INTO user_meta (user_id, day2_seeded) VALUES (?, 1)
               ON CONFLICT(user_id) DO UPDATE SET day2_seeded = 1""",
            (user_id,),
        )
        conn.commit()
        return added
    finally:
        conn.close()


def add_word(user_id: int, korean: str, uzbek: str, deck: str = "my words") -> bool:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO words (user_id, korean, uzbek, deck) VALUES (?, ?, ?, ?)",
            (user_id, korean.strip(), uzbek.strip(), deck),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def list_words(user_id: int, deck: str | None = None) -> list[dict]:
    conn = _connect()
    try:
        if deck:
            rows = conn.execute(
                "SELECT korean, uzbek, deck FROM words WHERE user_id = ? AND deck = ? ORDER BY id",
                (user_id, deck),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT korean, uzbek, deck FROM words WHERE user_id = ? ORDER BY deck, id",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def count_words(user_id: int) -> int:
    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM words WHERE user_id = ?", (user_id,)).fetchone()["c"]
    finally:
        conn.close()


def get_all_words(user_id: int) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, korean, uzbek FROM words WHERE user_id = ? ORDER BY RANDOM()", (user_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def existing_korean(user_id: int, deck: str = "my words") -> set[str]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT korean FROM words WHERE user_id = ? AND deck = ?", (user_id, deck)
        ).fetchall()
        return {row["korean"].strip().casefold() for row in rows}
    finally:
        conn.close()


def add_words_bulk(user_id: int, pairs: list[tuple[str, str]], deck: str = "my words") -> tuple[int, int]:
    """Add many pairs in one transaction; return (added, skipped)."""
    conn = _connect()
    added = skipped = 0
    try:
        for korean, uzbek in pairs:
            korean, uzbek = korean.strip(), uzbek.strip()
            if not korean or not uzbek:
                skipped += 1
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO words (user_id, korean, uzbek, deck) VALUES (?, ?, ?, ?)",
                (user_id, korean, uzbek, deck),
            )
            if cur.rowcount:
                added += 1
            else:
                skipped += 1
        conn.commit()
        return added, skipped
    finally:
        conn.close()


def record_lesson_result(user_id: int, lesson_id: int, correct: int, total: int) -> None:
    """Record a lesson quiz; mark complete at 75% or better."""
    completed = int(total > 0 and correct / total >= 0.75)
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO lesson_progress(user_id, lesson_id, best_score, attempts, completed)
               VALUES (?, ?, ?, 1, ?)
               ON CONFLICT(user_id, lesson_id) DO UPDATE SET
                 best_score = MAX(best_score, excluded.best_score),
                 attempts = attempts + 1, completed = MAX(completed, excluded.completed)""",
            (user_id, lesson_id, correct, completed),
        )
        conn.commit()
    finally:
        conn.close()

def get_lesson_progress(user_id: int) -> dict[int, dict]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT lesson_id, best_score, attempts, completed FROM lesson_progress WHERE user_id = ?", (user_id,)).fetchall()
        return {row['lesson_id']: dict(row) for row in rows}
    finally:
        conn.close()
