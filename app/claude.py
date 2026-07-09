import asyncio
import logging

import anthropic

from .config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0
_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPT = """\
Sos el asistente de comunicaciones del administrador del edificio Torre Arachanes.
Tu tarea es reformatear mensajes informales como comunicados formales e institucionales
dirigidos a los vecinos del edificio.

Reglas:
- Preservá el contenido exactamente. No agregues, elimines, ni infieras información.
- Usá tono formal, tercera persona, presente o futuro según corresponda.
- Comenzá con una frase que contextualice al lector (quién comunica qué).
- No uses emojis, signos de exclamación, ni lenguaje coloquial.
- No uses formato markdown (sin asteriscos, sin listas con guión, sin código). Solo texto plano.
- La respuesta es solo el texto reformateado. Sin explicaciones ni metacomentarios.

Ejemplo:
Input: "el ascensor no funciona hasta el miercoles"
Output: "Se informa a los vecinos que el servicio de ascensor se encuentra temporalmente \
fuera de servicio. Se estima la reparación para el día miércoles."
"""


async def format_message(raw_text: str) -> str:
    """Call Claude to reformat an informal message.

    Raises asyncio.TimeoutError on timeout, ValueError on empty response.
    """
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.CLAUDE_API_KEY, timeout=_TIMEOUT)

    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=_MODEL,
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": raw_text}],
            ),
            timeout=_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error("Claude timed out for text: %s", raw_text[:100])
        raise

    text = response.content[0].text.strip() if response.content else ""
    if not text:
        logger.error("Claude returned empty response for text: %s", raw_text[:100])
        raise ValueError("Claude returned empty response")

    return text
