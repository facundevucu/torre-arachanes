"""Startup recovery: session check + replay missed messages."""
import logging

from . import waha
from .config import get_settings
from .db import get_last_processed_at, get_pending
from .webhook import process_message

logger = logging.getLogger(__name__)


async def run_startup_recovery() -> None:
    settings = get_settings()

    # 1. Session health check
    status = await waha.get_session_status()
    if status != "WORKING":
        logger.error("WAHA session status is %s (expected WORKING). Halting startup recovery.", status)
        return

    logger.info("WAHA session is WORKING.")

    # 2. Load cursor
    last_ts = get_last_processed_at()
    logger.info("Last processed timestamp: %s", last_ts or "never")

    # 3. Fetch missed messages (best-effort — T3)
    messages = await waha.get_messages_since(last_ts)

    # Filter to authorized sender only, exclude fromMe
    authorized = settings.AUTHORIZED_NUMBER
    missed = [
        m for m in messages
        if m.get("from") == authorized and not m.get("fromMe", False)
    ]

    if not missed:
        if last_ts:
            # Had previous messages but nothing new — clean start
            logger.info("No missed messages since last run.")
        else:
            # First ever run or empty history
            await waha.send_text(
                authorized,
                "Bot reiniciado. Si mandaste mensajes mientras estaba caído, reenviálos.",
            )
        return

    logger.info("Found %d missed message(s) from %s.", len(missed), authorized)

    # 4. Check for pending draft
    pending = get_pending()
    if pending:
        logger.info("Pending draft exists (id=%s). Notifying father.", pending["message_id"])
        await waha.send_text(
            authorized,
            "El bot reinició y hay un borrador pendiente. "
            "Respondé 'ok' para publicar o 'cancelar' para descartar antes de continuar.",
        )
        return

    # 5. Replay missed messages in order
    logger.info("Replaying %d missed message(s).", len(missed))
    for msg in missed:
        await process_message(msg)
