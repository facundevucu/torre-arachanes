import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from .config import get_settings


def init_db() -> None:
    settings = get_settings()
    os.makedirs(os.path.dirname(settings.DB_PATH), exist_ok=True)
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pending_approvals (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id      TEXT    UNIQUE NOT NULL,
                type            TEXT    NOT NULL CHECK(type IN ('text', 'pdf')),
                raw_text        TEXT,
                formatted_text  TEXT,
                local_pdf_path  TEXT,
                status          TEXT    NOT NULL DEFAULT 'pending'
                                CHECK(status IN ('pending','published','cancelled','error')),
                created_at      TEXT    NOT NULL,
                resolved_at     TEXT
            );
            CREATE TABLE IF NOT EXISTS bot_state (
                id                  INTEGER PRIMARY KEY CHECK(id = 1),
                last_processed_at   TEXT
            );
            INSERT OR IGNORE INTO bot_state(id, last_processed_at) VALUES(1, NULL);
            CREATE TABLE IF NOT EXISTS processed_messages (
                message_id    TEXT PRIMARY KEY,
                processed_at  TEXT NOT NULL
            );
        """)


@contextmanager
def _connect():
    settings = get_settings()
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_pending() -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM pending_approvals WHERE status='pending' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def insert_pending(
    message_id: str,
    msg_type: str,
    raw_text: Optional[str] = None,
    formatted_text: Optional[str] = None,
    local_pdf_path: Optional[str] = None,
) -> bool:
    """Returns False if message_id already exists (idempotency guard — T1)."""
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO pending_approvals
                   (message_id, type, raw_text, formatted_text, local_pdf_path, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    message_id,
                    msg_type,
                    raw_text,
                    formatted_text,
                    local_pdf_path,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def resolve_pending(pending_id: int, status: str) -> None:
    """Resolve one draft. Never resolve by status alone: that would mark drafts
    that were not sent as published."""
    with _connect() as conn:
        conn.execute(
            "UPDATE pending_approvals SET status=?, resolved_at=? WHERE id=? AND status='pending'",
            (status, datetime.now(timezone.utc).isoformat(), pending_id),
        )


def is_processed(message_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_messages WHERE message_id=?", (message_id,)
        ).fetchone()
        return row is not None


def mark_processed(message_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO processed_messages(message_id, processed_at) VALUES(?, ?)",
            (message_id, datetime.now(timezone.utc).isoformat()),
        )


def get_last_processed_at() -> Optional[str]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT last_processed_at FROM bot_state WHERE id=1"
        ).fetchone()
        return row["last_processed_at"] if row else None


def set_last_processed_at(ts: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE bot_state SET last_processed_at=? WHERE id=1", (ts,))
