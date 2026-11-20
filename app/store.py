"""SQLite storage: conversation history, negotiation state, processed message ids."""
from __future__ import annotations

import json
import sqlite3
import threading

from app import config

_lock = threading.Lock()
config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_db = sqlite3.connect(config.DB_PATH, check_same_thread=False)
_db.executescript(
    """
    CREATE TABLE IF NOT EXISTS conversations (
        customer_id TEXT PRIMARY KEY,
        messages TEXT NOT NULL,
        customer_name TEXT DEFAULT '',
        paused INTEGER DEFAULT 0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS negotiations (
        customer_id TEXT, car_id TEXT, start_date TEXT, end_date TEXT,
        step INTEGER DEFAULT 0, agreed_total REAL,
        PRIMARY KEY (customer_id, car_id, start_date, end_date)
    );
    CREATE TABLE IF NOT EXISTS processed_messages (
        message_id TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """
)
_db.commit()


# ---------- conversations ----------
def load_messages(customer_id: str) -> list[dict]:
    row = _db.execute("SELECT messages FROM conversations WHERE customer_id = ?", (customer_id,)).fetchone()
    return json.loads(row[0]) if row else []


def save_messages(customer_id: str, messages: list[dict], customer_name: str = "") -> None:
    with _lock:
        _db.execute(
            """INSERT INTO conversations (customer_id, messages, customer_name) VALUES (?,?,?)
               ON CONFLICT(customer_id) DO UPDATE SET messages = excluded.messages,
               customer_name = CASE WHEN excluded.customer_name != '' THEN excluded.customer_name
                                    ELSE conversations.customer_name END,
               updated_at = CURRENT_TIMESTAMP""",
            (customer_id, json.dumps(messages, ensure_ascii=False), customer_name),
        )
        _db.commit()


def reset_conversation(customer_id: str) -> None:
    with _lock:
        _db.execute("DELETE FROM conversations WHERE customer_id = ?", (customer_id,))
        _db.execute("DELETE FROM negotiations WHERE customer_id = ?", (customer_id,))
        _db.commit()


def is_paused(customer_id: str) -> bool:
    row = _db.execute("SELECT paused FROM conversations WHERE customer_id = ?", (customer_id,)).fetchone()
    return bool(row and row[0])


def set_paused(customer_id: str, paused: bool) -> None:
    """Paused = a human took over this customer; the bot stays silent."""
    with _lock:
        _db.execute(
            """INSERT INTO conversations (customer_id, messages, paused) VALUES (?, '[]', ?)
               ON CONFLICT(customer_id) DO UPDATE SET paused = excluded.paused""",
            (customer_id, int(paused)),
        )
        _db.commit()


# ---------- negotiations ----------
def get_negotiation(customer_id: str, car_id: str, start: str, end: str) -> tuple[int, float | None]:
    row = _db.execute(
        "SELECT step, agreed_total FROM negotiations WHERE customer_id=? AND car_id=? AND start_date=? AND end_date=?",
        (customer_id, car_id, start, end),
    ).fetchone()
    return (row[0], row[1]) if row else (0, None)


def set_negotiation(customer_id: str, car_id: str, start: str, end: str, step: int, agreed_total: float | None) -> None:
    with _lock:
        _db.execute(
            """INSERT INTO negotiations (customer_id, car_id, start_date, end_date, step, agreed_total)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(customer_id, car_id, start_date, end_date)
               DO UPDATE SET step = excluded.step, agreed_total = excluded.agreed_total""",
            (customer_id, car_id, start, end, step, agreed_total),
        )
        _db.commit()


# ---------- webhook de-duplication ----------
def mark_processed(message_id: str) -> bool:
    """Returns False if this message id was already handled (Meta retries webhooks)."""
    with _lock:
        try:
            _db.execute("INSERT INTO processed_messages (message_id) VALUES (?)", (message_id,))
            _db.commit()
            return True
        except sqlite3.IntegrityError:
            return False
