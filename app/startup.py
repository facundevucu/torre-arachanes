"""Startup recovery: session check + replay missed messages."""
import asyncio
import logging

from . import waha
from .config import get_settings
from .db import get_last_processed_at, get_pending
from .webhook import process_message

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

    # 2. Register webhook on the WAHA session (idempotent — survives session recreation).
    #    Uses customHeaders to send exactly X-Hook-Token, avoiding WHATSAPP_HOOK_TOKEN
    #    header-name ambiguity across WAHA versions.
    await waha.configure_session_webhook(settings.WEBHOOK_ENDPOINT_URL, settings.WEBHOOK_SECRET)

    # 3. Load cursor
    last_ts = get_last_processed_at()
    logger.info("Last processed timestamp: %s", last_ts or "never")

    # 3. Fetch missed messages (best-effort — T3)
    messages = await waha.get_messages_since(last_ts)

    # Filter to authorized sender only (accept both @c.us and @lid), exclude fromMe
    authorized_ids = {settings.AUTHORIZED_NUMBER}
    if settings.AUTHORIZED_LID:
        authorized_ids.add(settings.AUTHORIZED_LID)
    missed = [
        m for m in messages
        if m.get("from") in authorized_ids and not m.get("fromMe", False)
    ]

    if not missed:
        if last_ts:
            # Had previous messages but nothing new — clean start
            logger.info("No missed messages since last run.")
        else:
            # First ever run or empty history
            await waha.send_text(
                settings.AUTHORIZED_NUMBER,
                "Bot reiniciado. Si mandaste mensajes mientras estaba caído, reenviálos.",
            )
        return

    logger.info("Found %d missed message(s) from %s.", len(missed), authorized)

    # 4. Check for pending draft
    pending = get_pending()
    if pending:
        logger.info("Pending draft exists (id=%s). Notifying father.", pending["message_id"])
        await waha.send_text(
            settings.AUTHORIZED_NUMBER,
            "El bot reinició y hay un borrador pendiente. "
            "Respondé 'ok' para publicar o 'cancelar' para descartar antes de continuar.",
        )
        return

    # 5. Replay missed messages in order
    logger.info("Replaying %d missed message(s).", len(missed))
    for msg in missed:
        await process_message(msg)
