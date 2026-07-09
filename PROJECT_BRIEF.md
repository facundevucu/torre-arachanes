# Torre Arachanes — Bot de Comunicados por WhatsApp

## Resumen en una línea

Bot de WhatsApp que recibe mensajes informales de texto (y un archivo mensual de gastos comunes) de parte del administrador del edificio, los reformatea/reenvía con un tono formal, y los publica en el grupo de WhatsApp de vecinos.

## Contexto

Mi padre es el administrador de **Torre Arachanes**, un edificio de apartamentos. Hoy comunica novedades a los vecinos a mano, escribiendo directamente en el grupo de WhatsApp de administración del edificio. Quiero automatizar el paso de "mensaje informal → mensaje formal publicado en el grupo" para que él pueda seguir escribiendo como le sale natural, y el bot se encargue de darle formato antes de publicarlo.

No es un bot conversacional ni de atención al público. Es un **pipeline de un solo sentido**: mi padre (única persona autorizada) → bot → grupo del edificio. Volumen bajísimo: como máximo 1 mensaje por día, más un envío puntual el día 1 de cada mes.

## Actores

- **Emisor autorizado**: mi padre, el administrador. Único número cuyos mensajes el bot procesa. Cualquier otro remitente se ignora (o se loguea, a definir).
- **Destino**: el grupo de WhatsApp "administración del edificio / Torre Arachanes" (vecinos).
- **Operador técnico**: yo, dueño del servidor Oracle donde corre todo.

## Casos de uso

### Caso 1 — Comunicado puntual (uso diario, máximo 1/día)

1. Mi padre le escribe al número del bot (chat privado) algo informal, ej:
   > "el ascensor no funciona hasta el miercoles"
2. El bot toma ese texto, lo reformatea con tono formal/institucional usando la API de Claude, ej:
   > "Se informa a los vecinos que el ascensor se encuentra fuera de servicio y se estima su reparación para el día miércoles."
3. El bot publica el mensaje formateado en el grupo de administración.

### Caso 2 — Gastos comunes (mensual, día 1 de cada mes)

1. Mi padre le manda al bot un archivo (PDF o imagen, a confirmar) con los gastos comunes del mes.
2. El bot lo reenvía (o lo acompaña con un texto formal generado, ej. "Se adjunta la liquidación de gastos comunes correspondiente al mes de [mes/año].") al grupo.

## Requisitos funcionales

- [ ] El bot debe distinguir mensajes de mi padre (por número) de cualquier otro remitente.
- [ ] Reformateo de texto informal → formal vía API de Claude, preservando el contenido, sin inventar información.
- [ ] Envío del mensaje formateado al grupo de WhatsApp correcto.
- [ ] Manejo del envío mensual de gastos comunes (archivo adjunto).
- [ ] Registro/log de cada mensaje procesado y enviado (para poder auditar qué se publicó y cuándo).
- [ ] Persistencia de la sesión de WhatsApp entre reinicios del servidor (no debería requerir re-escanear QR cada vez que se reinicia el contenedor).

## Requisitos no funcionales

- **Volumen**: máx. 1 mensaje/día + 1 archivo/mes. Esto es importante para el diseño anti-baneo: nada de colas, reintentos agresivos ni broadcast.
- **Número dedicado**: el bot debe correr sobre un número de WhatsApp distinto al personal de mi padre (chip aparte). No usar el número personal de nadie para el bot.
- **Sin spam / sin ráfagas**: un solo envío por evento, sin reintentos en loop.
- **Confiabilidad ante caídas**: si el bot está caído cuando llega un mensaje, no debe perderlo silenciosamente — debe quedar algo para reintentarlo manualmente o loguearlo como fallido.
- **Simplicidad de operación**: mi padre no es técnico. Cero fricción de su lado: solo manda el mensaje al chat privado del bot como si fuera cualquier contacto.

## Arquitectura propuesta

```
Padre (WhatsApp, chat privado con el número del bot)
   → WAHA (Docker, en servidor Oracle) recibe el mensaje vía sesión WhatsApp Web
   → Webhook POST → Backend Python (FastAPI)
   → Backend valida remitente == número autorizado
   → Backend llama a la API de Claude para reformatear el texto
   → Backend llama a WAHA (POST /api/sendText o similar) para publicar en el grupo
```

**Stack:**
- **WAHA** (`devlikeapro/waha`, Docker) — capa REST sobre una sesión no oficial de WhatsApp Web. Tier gratuito (Core) alcanza si el archivo mensual se termina resolviendo como reenvío directo del archivo original (Core no manda multimedia generada por el bot, pero sí puede reenviar lo recibido — a confirmar en el diseño técnico).
- **Backend Python (FastAPI)** — recibe webhooks de WAHA, valida remitente, llama a la API de Claude, llama de vuelta a WAHA para publicar.
- **API de Claude** — reformateo de texto informal a formal.
- **Servidor Oracle** ya disponible — corre WAHA (contenedor) + backend Python.

## Fuera de alcance (por ahora)

- Interacción bidireccional / bot conversacional.
- Múltiples administradores o múltiples edificios.
- Confirmación manual antes de publicar (a decidir si se quiere o no — ver "Preguntas abiertas").
- Panel de administración web.

## Preguntas abiertas para resolver antes/durante el diseño

Estas son decisiones de producto/arquitectura que conviene forzar antes de escribir código (ideal para `/office-hours`):

1. **¿Confirmación previa o publicación directa?** ¿El bot publica directo al grupo, o le manda el borrador formateado a mi padre por privado primero y él confirma con un "sí" antes de publicar? (Reduce riesgo de que un error de formateo se publique sin revisión.)
2. **Formato del archivo de gastos comunes**: ¿PDF, imagen, Excel? ¿Siempre el mismo formato?
3. **¿El bot reenvía el archivo tal cual, o necesita extraer datos y generar un mensaje nuevo con contenido (ej. total, fecha límite de pago)?**
4. **¿Qué pasa si llega un mensaje de un número no autorizado?** ¿Se ignora en silencio, se loguea, se le responde algo?
5. **¿Cómo se identifica el JID del grupo de destino?** Hay que obtenerlo una vez vía la API de WAHA (`GET /api/{session}/chats`) y hardcodearlo/configurarlo.
6. **¿Qué pasa si la API de Claude falla o devuelve algo raro?** ¿Se aborta el envío, se manda el texto original sin formatear, se notifica a mi padre?
7. **Tono exacto del formateo**: ¿siempre arranca con "Se informa a los vecinos que..." o varía según el tipo de mensaje?

## Riesgos conocidos (investigados previamente)

- **Riesgo de baneo de WhatsApp**: cualquier librería no oficial (WAHA/Baileys por debajo) opera fuera de los TOS de WhatsApp. El volumen bajísimo de este proyecto (1 msg/día) es el escenario de menor riesgo posible, pero no es cero. Mitigación: número dedicado, sin ráfagas, sin reintentos agresivos.
- **Pérdida de sesión al reiniciar el contenedor**: hay que persistir el volumen de credenciales de WAHA (`-v waha_data:/app/.sessions`) para no tener que re-escanear el QR en cada deploy/reinicio.
- **Tier gratuito de WAHA no manda multimedia**: si el archivo de gastos comunes necesita procesamiento (no solo reenvío), puede requerir WAHA Plus (~$19/mes) o resolver el envío de archivo por otra vía.

## Criterio de éxito

El proyecto está listo cuando:
- Mi padre le manda un mensaje de texto informal al bot y aparece formateado en el grupo en menos de ~10 segundos, sin intervención mía.
- El día 1 de cada mes, el archivo de gastos comunes llega al grupo sin que yo tenga que hacer nada manual.
- El sistema sobrevive un reinicio del servidor sin perder la sesión de WhatsApp.

## Cómo arrancar con gstack

Con el repo ya clonado y gstack instalado, el flujo sugerido es:

1. `/office-hours` — para forzar las decisiones de la sección "Preguntas abiertas" antes de escribir código, usando este documento como input.
2. `/plan-eng-review` — para trazar el flujo de datos (webhook → validación → Claude API → WAHA), casos de error, y el plan de tests.
3. Implementación (WAHA en Docker + backend FastAPI).
4. `/review` antes de dar por cerrado cualquier cambio grande.
5. `/ship` cuando esté listo para correr en el servidor Oracle.

Este documento es el input inicial — no reemplaza el design doc que generen `/office-hours` y `/plan-eng-review`, es el contexto de negocio detrás del pedido.
