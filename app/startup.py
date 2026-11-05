"""Startup recovery: session check + replay missed messages."""
import asyncio
import logging

from . import waha
from .config import get_settings
from .db import get_last_processed_at, get_pending, is_processed
from .webhook import CANCEL_KEYWORDS, CONFIRM_KEYWORDS, process_message

logger = logging.getLogger(__name__)

# WAHA takes ~60s to connect to WhatsApp after container start.
# Poll until it reaches a terminal state or we time out.
_MAX_WAIT_SECS = 120
_POLL_INTERVAL_SECS = 5
# States that mean WAHA is still starting up or unreachable — keep polling.
_TRANSIENT_STATES = {"UNKNOWN", "STARTING", "CONNECTING", "OPENING", "SYNCING"}


async def _wait_for_waha() -> str:
    """Poll WAHA up to _MAX_WAIT_SECS until session reaches a non-transient state."""
    elapsed = 0
    while elapsed < _MAX_WAIT_SECS:
        status = await waha.get_session_status()
        if status not in _TRANSIENT_STATES:
            return status
        logger.info(
            "WAHA session: %s — waiting %ds for it to be WORKING (%ds elapsed)...",
            status, _POLL_INTERVAL_SECS, elapsed,
        )
        await asyncio.sleep(_POLL_INTERVAL_SECS)
        elapsed += _POLL_INTERVAL_SECS
    # Last attempt
    return await waha.get_session_status()


async def run_startup_recovery() -> None:
    settings = get_settings()

    # 1. Wait for WAHA to be ready (backend starts before WAHA HTTP server is up).
    logger.info("Startup recovery: waiting for WAHA to be ready...")
    status = await _wait_for_waha()

    if status != "WORKING":
        logger.error("WAHA session status is %s (expected WORKING). Halting startup recovery.", status)
        return

    logger.info("WAHA session is WORKING.")

    # The webhook is registered globally via the WHATSAPP_HOOK_URL env var (set in
    # the server's .env); WAHA delivers `message` events to /webhook with no auth
    # header, which is exactly what app.main.webhook expects. We deliberately do NOT
    # also register a per-session webhook — that would double-deliver every message.

    # 2. Load cursor. Without one we cannot tell old messages from missed ones, so
    #    replaying would re-answer the whole chat history.
    last_ts = get_last_processed_at()
    logger.info("Last processed timestamp: %s", last_ts or "never")

    if not last_ts:
        for jid in settings.AUTHORIZED_NUMBERS:
            await waha.send_text(
                jid,
                "Bot reiniciado. Si mandaste mensajes mientras estaba caído, reenviálos.",
            )
        return

    # 3. Fetch missed messages (best-effort — T3)
    missed = await _collect_missed(settings, last_ts)

    if not missed:
        logger.info("No missed messages since last run.")
        return

    logger.info("Found %d missed message(s).", len(missed))

    # 4. Check for pending draft
    pending = get_pending()
    if pending:
        logger.info("Pending draft exists (id=%s). Notifying.", pending["message_id"])
        for jid in settings.AUTHORIZED_NUMBERS:
            await waha.send_text(
                jid,
                "El bot reinició y hay un borrador pendiente. "
                "Respondé 'ok' para publicar o 'cancelar' para descartar antes de continuar.",
            )
        return

    # 5. Replay missed messages in order
    logger.info("Replaying %d missed message(s).", len(missed))
    for msg in missed:
        await process_message(msg)


async def _collect_missed(settings, last_ts: str) -> list:
    """Return the messages to replay, oldest first.

    WAHA's GET /api/messages requires a chatId. The @c.us and @lid chats return the
    same messages, so results are deduplicated by id. Its timestamp filter is `gte`,
    so the cursor message comes back too and is dropped here.
    """
    authorized_ids = set(settings.AUTHORIZED_NUMBERS)
    if settings.AUTHORIZED_LID:
        authorized_ids.add(settings.AUTHORIZED_LID)

    by_id: dict = {}
    for chat_id in sorted(authorized_ids):
        for message in await waha.get_messages_since(chat_id, last_ts):
            by_id[message.get("id")] = message

    cursor = float(last_ts)
    missed = [
        m for m in by_id.values()
        if m.get("from") in authorized_ids
        and not m.get("fromMe", False)
        and float(m.get("timestamp") or 0) > cursor
        and not is_processed(m.get("id") or "")
        and not _is_command(m)
    ]
    return sorted(missed, key=lambda m: float(m.get("timestamp") or 0))


def _is_command(message: dict) -> bool:
    """Commands answer a draft the sender saw at the time. Replaying one after a
    restart could publish a draft nobody has read, so they are never replayed."""
    body = (message.get("body") or "").strip().lower()
    return body in CONFIRM_KEYWORDS or body in CANCEL_KEYWORDS
