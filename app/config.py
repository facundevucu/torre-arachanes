import os
from functools import lru_cache


class Settings:
    def __init__(self) -> None:
        self.AUTHORIZED_NUMBER: str = os.environ["AUTHORIZED_NUMBER"]
        self.GROUP_JID: str = os.environ["GROUP_JID"]
        self.CLAUDE_API_KEY: str = os.environ["CLAUDE_API_KEY"]
        self.WAHA_API_KEY: str = os.environ.get("WAHA_API_KEY", "")
        self.WAHA_BASE_URL: str = os.environ.get("WAHA_BASE_URL", "http://waha:3000")
        self.WEBHOOK_SECRET: str = os.environ["WEBHOOK_SECRET"]
        self.MEDIA_DIR: str = os.environ.get("MEDIA_DIR", "/app/media")
        self.DB_PATH: str = os.environ.get("DB_PATH", "/app/data/bot.db")


@lru_cache
def get_settings() -> Settings:
    return Settings()
