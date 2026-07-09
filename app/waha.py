import base64
import logging
from typing import Optional

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)

_SEND_TIMEOUT = 15.0
_DOWNLOAD_TIMEOUT = 30.0


def _headers() -> dict:
    key = get_settings().WAHA_API_KEY
    return {"X-Api-Key": key} if key else {}


def _base_url() -> str:
    return get_settings().WAHA_BASE_URL


async def send_text(chat_id: str, text: str) -> bool:
    async with httpx.AsyncClient(timeout=_SEND_TIMEOUT) as client:
        try:
            r = await client.post(
                f"{_base_url()}/api/sendText",
                json={"session": "default", "chatId": chat_id, "text": text},
                headers=_headers(),
            )
            r.raise_for_status()
            return True
        except Exception as exc:
            logger.error("sendText to %s failed: %s", chat_id, exc)
            return False


async def send_file(chat_id: str, file_path: str, caption: str) -> bool:
    """Send a local file to a WhatsApp chat using WAHA sendFile API.

    Encodes the file as base64 — WAHA Core NOWEB does not support multipart upload.
    """
    try:
        with open(file_path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode()
    except OSError as exc:
        logger.error("Cannot open file %s: %s", file_path, exc)
        return False

    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as client:
        try:
            r = await client.post(
                f"{_base_url()}/api/sendFile",
                json={
                    "session": "default",
                    "chatId": chat_id,
                    "caption": caption,
                    "file": {
                        "mimetype": "application/pdf",
                        "filename": "gastos_comunes.pdf",
                        "data": data,
                    },
                },
                headers=_headers(),
            )
            r.raise_for_status()
            return True
        except Exception as exc:
            logger.error("sendFile to %s failed: %s", chat_id, exc)
            return False


async def download_media(media_url: str, dest_path: str) -> bool:
    """Download media from a WAHA mediaUrl into dest_path."""
    import os
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as client:
        try:
            r = await client.get(media_url, headers=_headers())
            r.raise_for_status()
            with open(dest_path, "wb") as fh:
                fh.write(r.content)
            return True
        except Exception as exc:
            logger.error("download_media from %s failed: %s", media_url, exc)
            return False


async def get_session_status() -> str:
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(
                f"{_base_url()}/api/sessions/default",
                headers=_headers(),
            )
            r.raise_for_status()
            return r.json().get("status", "UNKNOWN")
        except Exception as exc:
            logger.error("get_session_status failed: %s", exc)
            return "UNKNOWN"


async def get_messages_since(from_timestamp: Optional[str]) -> list:
    """Fetch recent messages for the default session.

    Returns an empty list on any error (best-effort — T3).
    """
    params: dict = {"limit": 100, "downloadMedia": "false"}
    if from_timestamp:
        params["fromTimestamp"] = from_timestamp

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(
                f"{_base_url()}/api/default/messages",
                params=params,
                headers=_headers(),
            )
            r.raise_for_status()
            return r.json() or []
        except Exception as exc:
            logger.warning("get_messages_since failed: %s", exc)
            return []
