"""Tests for startup recovery. The rule under test: a restart must never publish
to the group or answer a message twice."""
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app import startup, waha
from app.db import get_pending, insert_pending, set_last_processed_at
from app.webhook import process_message

FATHER = "549TEST1@c.us"
LID = "1234@lid"


def _msg(msg_id: str, body: str, ts: int, sender: str = FATHER, from_me: bool = False) -> dict:
    return {
        "id": msg_id,
        "from": sender,
        "fromMe": from_me,
        "body": body,
        "hasMedia": False,
        "timestamp": ts,
    }


def _run_recovery(history: list):
    """Patch WAHA so recovery sees `history`; returns the patches to assert on."""
    return (
        patch("app.waha.get_session_status", AsyncMock(return_value="WORKING")),
        patch("app.waha.get_messages_since", AsyncMock(return_value=history)),
        patch("app.waha.send_text", AsyncMock(return_value=True)),
        patch("app.webhook.format_message", AsyncMock(return_value="formateado")),
    )


async def test_last_processed_message_is_not_replayed():
    """The cursor message itself comes back from a `gte` filter."""
    set_last_processed_at("1000")
    status, history, send, claude = _run_recovery([_msg("m1", "aviso", 1000)])
    with status, history, send as send_text, claude as format_message:
        await startup.run_startup_recovery()
    send_text.assert_not_called()
    format_message.assert_not_called()


async def test_older_messages_are_not_replayed_even_if_waha_ignores_the_filter():
    set_last_processed_at("1000")
    status, history, send, claude = _run_recovery([_msg("m1", "viejo", 500)])
    with status, history, send as send_text, claude:
        await startup.run_startup_recovery()
    send_text.assert_not_called()


@pytest.mark.parametrize("keyword", ["ok", "OK ", "si", "sí", "cancelar", "cancel"])
async def test_recovery_never_replays_commands(keyword):
    """An old 'ok' must not publish a draft nobody has seen."""
    set_last_processed_at("1000")
    status, history, send, claude = _run_recovery([_msg("m1", keyword, 1001)])
    with status, history, send as send_text, claude:
        await startup.run_startup_recovery()
    send_text.assert_not_called()


async def test_draft_followed_by_ok_stops_at_the_draft():
    set_last_processed_at("1000")
    missed = [_msg("m1", "aviso nuevo", 1001), _msg("m2", "ok", 1002)]
    status, history, send, claude = _run_recovery(missed)
    with status, history, send as send_text, claude:
        await startup.run_startup_recovery()
    assert get_pending() is not None
    assert send_text.await_count == 1
    assert send_text.await_args.args[0] == FATHER


async def test_same_message_from_both_chat_ids_is_replayed_once(monkeypatch):
    """WAHA returns the same messages for the @c.us and the @lid chat."""
    monkeypatch.setenv("AUTHORIZED_LID", LID)
    from app.config import get_settings
    get_settings.cache_clear()
    set_last_processed_at("1000")
    status, history, send, claude = _run_recovery([_msg("m1", "aviso", 1001, sender=LID)])
    with status, history, send as send_text, claude as format_message:
        await startup.run_startup_recovery()
    assert format_message.await_count == 1
    assert send_text.await_count == 1


async def test_message_already_handled_by_webhook_is_not_replayed():
    set_last_processed_at("1000")
    status, history, send, claude = _run_recovery([_msg("m1", "aviso", 1001)])
    with status, history, send as send_text, claude:
        await process_message(_msg("m1", "aviso", 1001))
        # The webhook moved the cursor; force it back to prove dedupe works alone.
        set_last_processed_at("1000")
        send_text.reset_mock()
        await startup.run_startup_recovery()
    send_text.assert_not_called()


async def test_fresh_database_does_not_replay_history():
    """No cursor means we cannot tell old from new: notify, replay nothing."""
    status, history, send, claude = _run_recovery([_msg("m1", "viejo", 1)])
    with status, history as get_messages, send as send_text, claude as format_message:
        await startup.run_startup_recovery()
    format_message.assert_not_called()
    get_messages.assert_not_called()
    assert send_text.await_count == 1
    assert "reiniciado" in send_text.await_args.args[1]


async def test_no_messages_with_cursor_is_silent():
    set_last_processed_at("1000")
    status, history, send, claude = _run_recovery([])
    with status, history, send as send_text, claude:
        await startup.run_startup_recovery()
    send_text.assert_not_called()


async def test_pending_draft_blocks_replay():
    set_last_processed_at("1000")
    insert_pending("p1", "text", raw_text="r", formatted_text="f")
    status, history, send, claude = _run_recovery([_msg("m1", "aviso", 1001)])
    with status, history, send as send_text, claude as format_message:
        await startup.run_startup_recovery()
    format_message.assert_not_called()
    assert send_text.await_count == 1


async def test_session_not_working_stops_recovery():
    with patch("app.waha.get_session_status", AsyncMock(return_value="FAILED")), \
         patch("app.waha.get_messages_since", AsyncMock()) as get_messages:
        await startup.run_startup_recovery()
    get_messages.assert_not_called()


# ─── waha.get_messages_since ─────────────────────────────────────────────────

def _client_with(handler):
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    return patch("app.waha.httpx.AsyncClient", factory)


async def test_get_messages_since_queries_the_chat():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=[{"id": "m1"}])

    with _client_with(handler):
        result = await waha.get_messages_since(FATHER, "1000")

    assert result == [{"id": "m1"}]
    assert seen["path"] == "/api/messages"
    assert seen["params"]["chatId"] == FATHER
    assert seen["params"]["session"] == "default"
    assert seen["params"]["filter.timestamp.gte"] == "1000"


async def test_get_messages_since_returns_empty_on_error():
    with _client_with(lambda request: httpx.Response(404)):
        assert await waha.get_messages_since(FATHER, "1000") == []
