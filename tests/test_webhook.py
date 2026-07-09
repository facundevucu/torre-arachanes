"""Tests for the FastAPI /webhook endpoint and core message processing."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.db import get_pending, insert_pending


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _text_payload(body: str, from_number: str = "549TEST1@c.us", msg_id: str = "msg-001") -> dict:
    return {
        "event": "message",
        "payload": {
            "id": msg_id,
            "from": from_number,
            "fromMe": False,
            "body": body,
            "hasMedia": False,
            "mimetype": None,
            "mediaUrl": None,
            "timestamp": "1720547200",
        },
    }


def _pdf_payload(msg_id: str = "pdf-001", media_url: str = "http://waha-test:3000/media/pdf-001") -> dict:
    return {
        "event": "message",
        "payload": {
            "id": msg_id,
            "from": "549TEST1@c.us",
            "fromMe": False,
            "body": "",
            "hasMedia": True,
            "mimetype": "application/pdf",
            "mediaUrl": media_url,
            "timestamp": "1720547201",
        },
    }


# ─── Webhook auth ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_token_returns_401():
    from httpx import AsyncClient
    from app.main import app

    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post(
            "/webhook",
            json=_text_payload("hola"),
            headers={"x-hook-token": "wrong-token"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_missing_token_returns_401():
    from httpx import AsyncClient
    from app.main import app

    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post("/webhook", json=_text_payload("hola"))
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_returns_200():
    from httpx import AsyncClient
    from app.main import app

    with patch("app.webhook.waha.send_text", AsyncMock(return_value=True)), \
         patch("app.webhook.format_message", AsyncMock(return_value="Texto formal.")):
        async with AsyncClient(app=app, base_url="http://test") as client:
            r = await client.post(
                "/webhook",
                json=_text_payload("el ascensor no funciona"),
                headers={"x-hook-token": "test-secret"},
            )
    assert r.status_code == 200


# ─── Unauthorized sender ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unauthorized_sender_is_silently_ignored():
    from app.webhook import process_message

    with patch("app.webhook.waha.send_text", AsyncMock()) as mock_send:
        await process_message({
            "from": "OTHER_NUMBER@c.us",
            "fromMe": False,
            "id": "msg-002",
            "body": "hola",
            "hasMedia": False,
            "timestamp": "1720547300",
        })
    mock_send.assert_not_called()


# ─── New text message flow ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_new_text_no_pending_sends_draft_to_father():
    from app.webhook import process_message

    with patch("app.webhook.waha.send_text", AsyncMock(return_value=True)) as mock_send, \
         patch("app.webhook.format_message", AsyncMock(return_value="Texto formal.")) as mock_claude:
        await process_message(_text_payload("el ascensor no funciona")["payload"])

    mock_claude.assert_called_once_with("el ascensor no funciona")
    sent_text = mock_send.call_args[0][1]
    assert "[BORRADOR" in sent_text
    assert "Texto formal." in sent_text
    assert get_pending() is not None
    assert get_pending()["status"] == "pending"


@pytest.mark.asyncio
async def test_new_text_with_pending_returns_error():
    from app.webhook import process_message

    insert_pending("existing", "text", raw_text="prev", formatted_text="Prev formal.")

    with patch("app.webhook.waha.send_text", AsyncMock(return_value=True)) as mock_send, \
         patch("app.webhook.format_message", AsyncMock()) as mock_claude:
        await process_message(_text_payload("nuevo mensaje", msg_id="msg-002")["payload"])

    mock_claude.assert_not_called()
    sent_text = mock_send.call_args[0][1]
    assert "borrador pendiente" in sent_text.lower()


@pytest.mark.asyncio
async def test_claude_timeout_sends_error_to_father():
    from app.webhook import process_message

    with patch("app.webhook.waha.send_text", AsyncMock(return_value=True)) as mock_send, \
         patch("app.webhook.format_message", AsyncMock(side_effect=asyncio.TimeoutError)):
        await process_message(_text_payload("el ascensor no funciona")["payload"])

    sent_text = mock_send.call_args[0][1]
    assert "reenviálo" in sent_text
    assert get_pending() is None  # nothing saved on failure


@pytest.mark.asyncio
async def test_duplicate_message_id_is_idempotent():
    from app.webhook import process_message

    payload = _text_payload("el ascensor no funciona")["payload"]

    with patch("app.webhook.waha.send_text", AsyncMock(return_value=True)), \
         patch("app.webhook.format_message", AsyncMock(return_value="Texto formal.")):
        await process_message(payload)
        await process_message(payload)  # WAHA retry

    # Only one pending entry
    from app.db import _connect
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM pending_approvals").fetchone()[0]
    assert count == 1


# ─── Confirmation flow ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ok_with_pending_publishes_to_group():
    from app.webhook import process_message

    insert_pending("t1", "text", raw_text="raw", formatted_text="Texto formal.")

    with patch("app.webhook.waha.send_text", AsyncMock(return_value=True)) as mock_send:
        await process_message(_text_payload("ok", msg_id="msg-confirm")["payload"])

    calls = [c[0] for c in mock_send.call_args_list]
    group_calls = [c for c in calls if c[0] == "120363409010865500@g.us"]
    assert len(group_calls) == 1
    assert group_calls[0][1] == "Texto formal."
    assert get_pending() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("keyword", ["ok", "si", "sí", "OK", "SI", "SÍ"])
async def test_confirm_keywords(keyword):
    from app.webhook import process_message

    insert_pending("t1", "text", raw_text="raw", formatted_text="Formal.")
    with patch("app.webhook.waha.send_text", AsyncMock(return_value=True)):
        await process_message(_text_payload(keyword, msg_id=f"msg-{keyword}")["payload"])
    assert get_pending() is None


@pytest.mark.asyncio
async def test_ok_without_pending_replies_no_draft():
    from app.webhook import process_message

    with patch("app.webhook.waha.send_text", AsyncMock(return_value=True)) as mock_send:
        await process_message(_text_payload("ok")["payload"])

    assert "No hay borrador" in mock_send.call_args[0][1]


@pytest.mark.asyncio
async def test_cancel_with_pending_cancels():
    from app.webhook import process_message

    insert_pending("t1", "text", raw_text="raw", formatted_text="Formal.")
    with patch("app.webhook.waha.send_text", AsyncMock(return_value=True)):
        await process_message(_text_payload("cancelar")["payload"])

    from app.db import _connect
    with _connect() as conn:
        row = conn.execute("SELECT status FROM pending_approvals WHERE message_id='t1'").fetchone()
    assert row[0] == "cancelled"


@pytest.mark.asyncio
async def test_non_keyword_message_does_not_trigger_confirm():
    """'está todo ok' should NOT confirm — exact match only."""
    from app.webhook import process_message

    insert_pending("t1", "text", raw_text="raw", formatted_text="Formal.")
    with patch("app.webhook.waha.send_text", AsyncMock(return_value=True)) as mock_send, \
         patch("app.webhook.format_message", AsyncMock()):
        await process_message(_text_payload("está todo ok")["payload"])

    # Should have replied "tenés un borrador pendiente", NOT published to group
    calls = [c[0] for c in mock_send.call_args_list]
    group_calls = [c for c in calls if c[0] == "120363409010865500@g.us"]
    assert len(group_calls) == 0


# ─── Unsupported media (T6) ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unsupported_media_type_sends_error():
    from app.webhook import process_message

    with patch("app.webhook.waha.send_text", AsyncMock(return_value=True)) as mock_send:
        await process_message({
            "from": "549TEST1@c.us",
            "fromMe": False,
            "id": "voice-001",
            "body": "",
            "hasMedia": True,
            "mimetype": "audio/ogg",
            "mediaUrl": "http://waha-test:3000/media/voice-001",
            "timestamp": "1720547400",
        })

    assert mock_send.called
    assert "Solo acepto" in mock_send.call_args[0][1]


# ─── PDF flow ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pdf_received_downloads_and_creates_draft(isolated_db):
    from app.webhook import process_message

    with patch("app.webhook.waha.download_media", AsyncMock(return_value=True)) as mock_dl, \
         patch("app.webhook.waha.send_text", AsyncMock(return_value=True)) as mock_send:
        await process_message(_pdf_payload()["payload"])

    mock_dl.assert_called_once()
    pending = get_pending()
    assert pending is not None
    assert pending["type"] == "pdf"
    sent = mock_send.call_args[0][1]
    assert "gastos comunes" in sent.lower()


@pytest.mark.asyncio
async def test_pdf_confirm_publishes_to_group(isolated_db, tmp_path):
    """Father approves a PDF pending — sendFile called with the local file."""
    from app.webhook import process_message

    # Create a dummy PDF file
    pdf_path = str(tmp_path / "media" / "pdf-001.pdf")
    with open(pdf_path, "wb") as fh:
        fh.write(b"%PDF dummy content")

    insert_pending(
        "pdf-001",
        "pdf",
        formatted_text="Se adjunta la liquidación de gastos comunes correspondiente al mes de julio 2026.",
        local_pdf_path=pdf_path,
    )

    with patch("app.webhook.waha.send_file", AsyncMock(return_value=True)) as mock_send_file, \
         patch("app.webhook.waha.send_text", AsyncMock(return_value=True)):
        await process_message(_text_payload("ok", msg_id="confirm-pdf")["payload"])

    mock_send_file.assert_called_once()
    assert mock_send_file.call_args[0][0] == "120363409010865500@g.us"
    assert get_pending() is None


@pytest.mark.asyncio
async def test_pdf_confirm_file_missing_sends_error(isolated_db):
    """If PDF file was deleted from volume, father gets a clear error (cross-model tension fix)."""
    from app.webhook import process_message

    insert_pending(
        "pdf-002",
        "pdf",
        formatted_text="Se adjunta la liquidación...",
        local_pdf_path="/app/media/nonexistent.pdf",
    )

    with patch("app.webhook.waha.send_text", AsyncMock(return_value=True)) as mock_send, \
         patch("app.webhook.waha.send_file", AsyncMock()) as mock_send_file:
        await process_message(_text_payload("ok", msg_id="confirm-missing")["payload"])

    mock_send_file.assert_not_called()
    assert "ya no está disponible" in mock_send.call_args[0][1]
