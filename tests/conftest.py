"""Shared test fixtures."""
import os
import tempfile

import pytest

# Set required env vars before any app module is imported
os.environ.setdefault("AUTHORIZED_NUMBER", "549TEST1@c.us")
os.environ.setdefault("GROUP_JID", "120363409010865500@g.us")
os.environ.setdefault("CLAUDE_API_KEY", "sk-ant-test")
os.environ.setdefault("WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("WAHA_API_KEY", "test-waha-key")
os.environ.setdefault("WAHA_BASE_URL", "http://waha-test:3000")


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Each test gets a fresh SQLite database in a temp directory."""
    db_path = str(tmp_path / "test_bot.db")
    media_dir = str(tmp_path / "media")
    os.makedirs(media_dir, exist_ok=True)

    # Clear lru_cache so Settings picks up patched env vars
    from app.config import get_settings
    get_settings.cache_clear()

    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("MEDIA_DIR", media_dir)

    from app.db import init_db
    init_db()

    yield tmp_path

    get_settings.cache_clear()
