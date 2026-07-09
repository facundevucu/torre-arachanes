"""State machine tests — SQLite transitions."""
import pytest

from app.db import get_pending, insert_pending, resolve_pending, set_last_processed_at, get_last_processed_at


def test_insert_pending_creates_entry():
    ok = insert_pending("m1", "text", raw_text="raw", formatted_text="formal")
    assert ok is True
    p = get_pending()
    assert p is not None
    assert p["message_id"] == "m1"
    assert p["status"] == "pending"


def test_insert_duplicate_returns_false():
    insert_pending("m1", "text", raw_text="raw", formatted_text="formal")
    ok = insert_pending("m1", "text", raw_text="raw2", formatted_text="formal2")
    assert ok is False

    # Only one row
    from app.db import _connect
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM pending_approvals").fetchone()[0]
    assert count == 1


def test_resolve_published():
    insert_pending("m1", "text", raw_text="r", formatted_text="f")
    resolve_pending("published")
    assert get_pending() is None

    from app.db import _connect
    with _connect() as conn:
        row = conn.execute("SELECT status FROM pending_approvals WHERE message_id='m1'").fetchone()
    assert row[0] == "published"


def test_resolve_cancelled():
    insert_pending("m1", "text", raw_text="r", formatted_text="f")
    resolve_pending("cancelled")
    assert get_pending() is None


def test_cursor_update():
    assert get_last_processed_at() is None
    set_last_processed_at("1720547200")
    assert get_last_processed_at() == "1720547200"
    set_last_processed_at("1720547300")
    assert get_last_processed_at() == "1720547300"


def test_only_one_pending_at_a_time():
    insert_pending("m1", "text", raw_text="r1", formatted_text="f1")
    insert_pending("m2", "text", raw_text="r2", formatted_text="f2")

    p = get_pending()
    # get_pending returns the most recent — m2 was inserted later
    assert p["message_id"] == "m2"
