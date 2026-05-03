"""Capa de persistencia: SQLite local. Sin ORM, queries directas."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_msg_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    text TEXT NOT NULL,
    classification TEXT NOT NULL,
    raw_payload TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    synced_at TEXT,
    UNIQUE (telegram_msg_id, chat_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

-- v2: recordatorios
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    fire_at TEXT NOT NULL,            -- ISO 8601 UTC
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | fired | cancelled
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    fired_at TEXT,
    synced_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reminders_status_fire ON reminders(status, fire_at);
CREATE INDEX IF NOT EXISTS idx_reminders_synced ON reminders(synced_at);
"""


def _ensure_dir(path: str) -> None:
    parent = Path(path).resolve().parent
    parent.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    _ensure_dir(config.DB_PATH)
    with _connect() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ---------- messages ----------

def insert_message(
    *,
    telegram_msg_id: int,
    chat_id: int,
    user_id: int,
    username: str | None,
    text: str,
    classification: str,
    raw_payload: dict[str, Any] | None = None,
) -> int | None:
    payload_json = json.dumps(raw_payload, ensure_ascii=False) if raw_payload else None
    with _connect() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO messages
                  (telegram_msg_id, chat_id, user_id, username, text, classification, raw_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (telegram_msg_id, chat_id, user_id, username, text, classification, payload_json),
            )
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def list_pending(limit: int = 500) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, telegram_msg_id, chat_id, user_id, username,
                   text, classification, status, created_at
            FROM messages
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_messages(limit: int = 100, offset: int = 0, status: str | None = None) -> list[dict[str, Any]]:
    with _connect() as conn:
        if status:
            rows = conn.execute(
                """SELECT id, text, classification, status, created_at, synced_at
                   FROM messages WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, text, classification, status, created_at, synced_at
                   FROM messages ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]


def update_message(msg_id: int, *, text: str | None = None, classification: str | None = None) -> int:
    sets, vals = [], []
    if text is not None:
        sets.append("text = ?")
        vals.append(text)
    if classification is not None:
        sets.append("classification = ?")
        vals.append(classification)
    if not sets:
        return 0
    vals.append(msg_id)
    with _connect() as conn:
        cur = conn.execute(f"UPDATE messages SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()
        return cur.rowcount


def delete_message(msg_id: int) -> int:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
        conn.commit()
        return cur.rowcount


def mark_synced(ids: list[int]) -> int:
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with _connect() as conn:
        cur = conn.execute(
            f"""UPDATE messages SET status='synced', synced_at=datetime('now')
                WHERE id IN ({placeholders}) AND status='pending'""",
            ids,
        )
        conn.commit()
        return cur.rowcount


def stats() -> dict[str, int]:
    with _connect() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM messages GROUP BY status").fetchall()
        out = {"pending": 0, "synced": 0, "total": 0}
        for r in rows:
            out[r["status"]] = r["n"]
            out["total"] += r["n"]
        # Recordatorios pendientes (no disparados) tampoco están en stats de mensajes;
        # los exponemos aparte:
        rrow = conn.execute(
            "SELECT COUNT(*) AS n FROM reminders WHERE status='pending'"
        ).fetchone()
        out["reminders_pending"] = rrow["n"] if rrow else 0
        return out


# ---------- reminders ----------

def insert_reminder(*, chat_id: int, user_id: int, text: str, fire_at_iso_utc: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO reminders (chat_id, user_id, text, fire_at)
               VALUES (?, ?, ?, ?)""",
            (chat_id, user_id, text, fire_at_iso_utc),
        )
        conn.commit()
        return cur.lastrowid or 0


def list_reminders_due(now_iso_utc: str, limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, chat_id, user_id, text, fire_at, created_at
               FROM reminders
               WHERE status='pending' AND fire_at <= ?
               ORDER BY fire_at ASC
               LIMIT ?""",
            (now_iso_utc, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def list_reminders_pending(user_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as conn:
        if user_id is not None:
            rows = conn.execute(
                """SELECT id, chat_id, user_id, text, fire_at, created_at
                   FROM reminders
                   WHERE status='pending' AND user_id = ?
                   ORDER BY fire_at ASC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, chat_id, user_id, text, fire_at, created_at
                   FROM reminders WHERE status='pending'
                   ORDER BY fire_at ASC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def list_reminders_unsynced(limit: int = 200) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, chat_id, user_id, text, fire_at, status, created_at, fired_at
               FROM reminders WHERE synced_at IS NULL
               ORDER BY created_at ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_reminder_fired(reminder_id: int) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE reminders SET status='fired', fired_at=datetime('now')
               WHERE id = ? AND status='pending'""",
            (reminder_id,),
        )
        conn.commit()
        return cur.rowcount


def cancel_reminder(reminder_id: int, user_id: int) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE reminders SET status='cancelled'
               WHERE id = ? AND user_id = ? AND status='pending'""",
            (reminder_id, user_id),
        )
        conn.commit()
        return cur.rowcount


def mark_reminders_synced(ids: list[int]) -> int:
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with _connect() as conn:
        cur = conn.execute(
            f"""UPDATE reminders SET synced_at=datetime('now')
                WHERE id IN ({placeholders}) AND synced_at IS NULL""",
            ids,
        )
        conn.commit()
        return cur.rowcount
