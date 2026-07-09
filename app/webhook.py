"""Core webhook processing logic.

All functions are async and called from a FastAPI BackgroundTask,
so WAHA already received its 200 OK before any of this runs.
"""
import asyncio
import logging
import os
from zoneinfo import ZoneInfo

from datetime import datetime

from . import sheets, waha
from .claude import format_message
from .config import get_settings
from .db import (
    get_pending,
    insert_pending,
    resolve_pending,
    set_last_processed_at,
)

logger = logging.getLogger(__name__)

CONFIRM_KEYWORDS = {"ok", "si", "sí"}
CANCEL_KEYWORDS = {"cancelar", "cancel"}
_ARG_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


async def process_message(payload: dict) -> None:
    """Entry point called by the BackgroundTask for every validated webhook."""
    from_number: str = payload.get("from", "")
    msg_id: str = payload.get("id", "")
    body: str = payload.get("body", "") or ""
    has_media: bool = payload.get("hasMedia", False)
    mimetype: str = payload.get("mimetype", "") or ""
    media_url: str = payload.get("mediaUrl", "") or ""
    from_me: bool = payload.get("fromMe", False)
    timestamp: str = str(payload.get("timestamp", ""))

    if from_me:
        return

    settings = get_settings()

    authorized_ids = set(settings.AUTHORIZED_NUMBERS)
    if settings.AUTHORIZED_LID:
        authorized_ids.add(settings.AUTHORIZED_LID)

    if from_number not in authorized_ids:
        logger.info("Ignored message from %s (not authorized)", from_number)
        return

    try:
        if has_media:
            await _handle_media(msg_id, mimetype, media_url, from_number)
        else:
            await _handle_text(msg_id, body, from_number)
        if timestamp:
            set_last_processed_at(timestamp)
    except Exception:
        logger.exception("Unhandled error processing message %s", msg_id)
        # Do not update cursor — message will be retried on next startup recovery


# ─── Text flow ───────────────────────────────────────────────────────────────

async def _handle_text(msg_id: str, body: str, from_number: str) -> None:
    lower = body.strip().lower()

    if lower in CONFIRM_KEYWORDS:
        await _confirm(from_number)
        return

    if lower in CANCEL_KEYWORDS:
        await _cancel(from_number)
        return

    if "gastos comunes" in lower:
        await _handle_gastos_comunes(msg_id, from_number)
        return

    pending = get_pending()
    if pending:
        await waha.send_text(
            from_number,
            "Tenés un borrador pendiente. Respondé 'ok' para publicar o 'cancelar' para descartar.",
        )
        return

    await _new_text_draft(msg_id, body.strip(), from_number)


async def _new_text_draft(msg_id: str, raw_text: str, from_number: str) -> None:
    try:
        formatted = await format_message(raw_text)
    except (asyncio.TimeoutError, ValueError) as exc:
        logger.error("Claude failed for msg %s: %s | raw: %s", msg_id, exc, raw_text)
        await waha.send_text(
            from_number,
            "No pude reformatear el mensaje. Por favor reenviálo en unos minutos.",
        )
        return

    inserted = insert_pending(
        message_id=msg_id,
        msg_type="text",
        raw_text=raw_text,
        formatted_text=formatted,
    )
    if not inserted:
        logger.warning("Duplicate message_id %s — ignoring (WAHA retry?)", msg_id)
        return

    await waha.send_text(
        from_number,
        f"[BORRADOR para el grupo]\n\n{formatted}\n\nRespondé 'ok' para publicar o 'cancelar' para descartar.",
    )


# ─── Confirmation / cancellation ─────────────────────────────────────────────

async def _confirm(from_number: str) -> None:
    settings = get_settings()
    pending = get_pending()

    if not pending:
        await waha.send_text(from_number, "No hay borrador pendiente.")
        return

    if pending["type"] == "pdf":
        await _publish_pdf(from_number, pending, settings)
    else:
        await _publish_text(from_number, pending, settings)


async def _publish_text(from_number: str, pending: dict, settings) -> None:
    ok = await waha.send_text(settings.GROUP_JID, pending["formatted_text"])
    if ok:
        resolve_pending("published")
        await waha.send_text(from_number, "✓ Publicado en el grupo.")
    else:
        await waha.send_text(from_number, "Error al publicar en el grupo. Intentá de nuevo.")


async def _publish_pdf(from_number: str, pending: dict, settings) -> None:
    path = pending.get("local_pdf_path", "")

    # File-existence check (T2 / cross-model tension resolved)
    if not path or not os.path.exists(path):
        resolve_pending("error")
        await waha.send_text(
            from_number,
            "El PDF ya no está disponible. Por favor reenviálo.",
        )
        return

    caption = pending["formatted_text"]  # caption was stored in formatted_text for PDFs
    ok = await waha.send_file(settings.GROUP_JID, path, caption)
    if ok:
        resolve_pending("published")
        await waha.send_text(from_number, "✓ PDF enviado al grupo.")
    else:
        await waha.send_text(from_number, "Error al enviar el PDF. Intentá de nuevo.")


async def _cancel(from_number: str) -> None:
    pending = get_pending()
    if not pending:
        await waha.send_text(from_number, "No hay borrador pendiente.")
        return
    resolve_pending("cancelled")
    await waha.send_text(from_number, "Descartado. Podés mandar otro mensaje cuando quieras.")


# ─── Google Sheets flow ──────────────────────────────────────────────────────

async def _handle_gastos_comunes(msg_id: str, from_number: str) -> None:
    settings = get_settings()

    pending = get_pending()
    if pending:
        await waha.send_text(
            from_number,
            "Tenés un borrador pendiente. Respondé 'ok' para publicar o 'cancelar' para descartar.",
        )
        return

    if not settings.GOOGLE_CREDENTIALS_PATH or not settings.SHEET_ID:
        logger.error("Google Sheets not configured — GOOGLE_CREDENTIALS_PATH or SHEET_ID missing")
        await waha.send_text(from_number, "La integración con Google Sheets no está configurada.")
        return

    try:
        pdf_bytes = await sheets.export_sheet_as_pdf(settings.SHEET_ID, settings.GOOGLE_CREDENTIALS_PATH, settings.SHEET_GIDS)
    except Exception as exc:
        logger.error("Google Sheets export failed: %s", exc)
        await waha.send_text(
            from_number,
            "No pude obtener la planilla de Google Sheets. "
            "Revisá que esté compartida con la cuenta de servicio y volvé a mandar 'gastos comunes'.",
        )
        return

    pdf_path = os.path.join(settings.MEDIA_DIR, f"{msg_id}.pdf")
    with open(pdf_path, "wb") as fh:
        fh.write(pdf_bytes)

    now = datetime.now(_ARG_TZ)
    billing_month = now.month - 1 if now.month > 1 else 12
    billing_year = now.year if now.month > 1 else now.year - 1
    caption = (
        f"Se adjunta la liquidación de gastos comunes correspondiente "
        f"al mes de *{_spanish_month(billing_month)}* {billing_year}."
    )

    inserted = insert_pending(
        message_id=msg_id,
        msg_type="pdf",
        local_pdf_path=pdf_path,
        formatted_text=caption,
    )
    if not inserted:
        logger.warning("Duplicate message_id %s — ignoring", msg_id)
        return

    await waha.send_file(from_number, pdf_path, caption)
    await waha.send_text(
        from_number,
        "Respondé 'ok' para publicar el PDF al grupo o 'cancelar' para descartar.",
    )


# ─── Media flow (PDF only) ───────────────────────────────────────────────────

async def _handle_media(
    msg_id: str, mimetype: str, media_url: str, from_number: str
) -> None:
    if mimetype != "application/pdf":
        await waha.send_text(
            from_number,
            "Solo acepto texto o el PDF de gastos comunes. "
            "Este tipo de archivo no está soportado.",
        )
        return

    pending = get_pending()
    if pending:
        await waha.send_text(
            from_number,
            "Tenés un borrador pendiente. Respondé 'ok' para publicar o 'cancelar' para descartar.",
        )
        return

    settings = get_settings()
    download_dest = os.path.join(settings.MEDIA_DIR, f"{msg_id}.pdf")

    ok = await waha.download_media(media_url, download_dest)
    if not ok:
        await waha.send_text(from_number, "No pude descargar el archivo. Por favor reenviálo.")
        return

    now = datetime.now(_ARG_TZ)
    billing_month = now.month - 1 if now.month > 1 else 12
    billing_year = now.year if now.month > 1 else now.year - 1
    caption = (
        f"Se adjunta la liquidación de gastos comunes correspondiente "
        f"al mes de *{_spanish_month(billing_month)}* {billing_year}."
    )

    inserted = insert_pending(
        message_id=msg_id,
        msg_type="pdf",
        local_pdf_path=download_dest,
        formatted_text=caption,
    )
    if not inserted:
        logger.warning("Duplicate media message_id %s — ignoring", msg_id)
        return

    await waha.send_text(
        from_number,
        f"[BORRADOR PARA EL GRUPO]\n\n{caption}\n\n"
        "Respondé 'ok' para reenviar el PDF al grupo o 'cancelar' para descartar.",
    )


def _spanish_month(month: int) -> str:
    return [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ][month - 1]
