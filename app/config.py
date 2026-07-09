import os
from functools import lru_cache


class Settings:
    def __init__(self) -> None:
        self.AUTHORIZED_NUMBERS: frozenset[str] = frozenset(
            n.strip() for n in os.environ["AUTHORIZED_NUMBER"].split(",") if n.strip()
        )
        self.GROUP_JID: str = os.environ["GROUP_JID"]
        self.CLAUDE_API_KEY: str = os.environ["CLAUDE_API_KEY"]
        self.WAHA_API_KEY: str = os.environ.get("WAHA_API_KEY", "")
        self.WAHA_BASE_URL: str = os.environ.get("WAHA_BASE_URL", "http://waha:3000")
        self.WEBHOOK_SECRET: str = os.environ["WEBHOOK_SECRET"]
        self.MEDIA_DIR: str = os.environ.get("MEDIA_DIR", "/app/media")
        self.DB_PATH: str = os.environ.get("DB_PATH", "/app/data/bot.db")
        self.WEBHOOK_ENDPOINT_URL: str = os.environ.get(
            "WEBHOOK_ENDPOINT_URL", "http://backend:8000/webhook"
        )
        # WhatsApp sometimes identifies senders via @lid (Linked ID) instead of @c.us.
        # If set, messages from this identifier are also accepted as authorized.
        self.AUTHORIZED_LID: str = os.environ.get("AUTHORIZED_LID", "")
        self.GOOGLE_CREDENTIALS_PATH: str = os.environ.get("GOOGLE_CREDENTIALS_PATH", "")
        self.SHEET_ID: str = os.environ.get("SHEET_ID", "")
        # Comma-separated GIDs of the sheet tabs to export (e.g. "1280341714,54283447").
        # If empty, exports the whole document in one request (may include blank pages).
        self.SHEET_GIDS: list[str] = [
            g.strip() for g in os.environ.get("SHEET_GIDS", "").split(",") if g.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
