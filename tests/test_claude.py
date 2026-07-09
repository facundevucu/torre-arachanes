"""Tests for the Claude integration — timeout and error handling."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_format_message_success():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Se informa a los vecinos que el ascensor no funciona.")]

    with patch("app.claude.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(return_value=mock_response)

        from app.claude import format_message
        result = await format_message("el ascensor no funciona")

    assert result == "Se informa a los vecinos que el ascensor no funciona."


@pytest.mark.asyncio
async def test_format_message_timeout_raises():
    with patch("app.claude.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(side_effect=asyncio.TimeoutError)

        from app.claude import format_message
        with pytest.raises(asyncio.TimeoutError):
            await format_message("el ascensor no funciona")


@pytest.mark.asyncio
async def test_format_message_empty_response_raises():
    mock_response = MagicMock()
    mock_response.content = []

    with patch("app.claude.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(return_value=mock_response)

        from app.claude import format_message
        with pytest.raises(ValueError, match="empty response"):
            await format_message("el ascensor no funciona")


@pytest.mark.asyncio
async def test_format_message_whitespace_only_raises():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="   ")]

    with patch("app.claude.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(return_value=mock_response)

        from app.claude import format_message
        with pytest.raises(ValueError):
            await format_message("el ascensor no funciona")
