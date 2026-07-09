import asyncio
import logging

import anthropic

from .config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0
_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPT = """\
Sos el asistente de comunicaciones del administrador de un edificio residencial.
Tu tarea es reformatear mensajes informales como comunicados formales y breves
dirigidos a los vecinos.

Reglas:
- Preservá el contenido exactamente. No agregues, elimines, ni infieras información.
- Tono formal, tercera persona, presente o futuro según corresponda.
- Dirigite siempre a "los vecinos" (ej. "Se informa a los vecinos que...").
- Nunca menciones el nombre del edificio.
- Sé breve: una o dos oraciones como máximo.
- Usá *asterisco simple* para resaltar palabras clave y fechas importantes \
(este es el formato de negrita de WhatsApp).
- Prohibido: **doble asterisco**, listas con guión, bloques de código, \
emojis, signos de exclamación, lenguaje coloquial.
- La respuesta es solo el texto reformateado. Sin explicaciones ni metacomentarios.

Ejemplo:
Input: "el ascensor no funciona hasta el miercoles"
Output: "Se informa a los vecinos que el *ascensor* se encuentra fuera de servicio \
hasta el *miércoles*."
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
