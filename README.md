# Torre Arachanes — Bot de Comunicados por WhatsApp

Bot de WhatsApp para administradores de edificios: transforma mensajes informales en comunicados formales y los publica automáticamente en el grupo de vecinos.

---

## ¿Qué hace?

El administrador le escribe al bot por WhatsApp como le sale natural. El bot:

1. **Reformatea** el texto con tono formal usando la API de Claude
2. **Muestra un borrador** al administrador para que lo revise
3. **Publica** en el grupo de vecinos cuando el administrador confirma con `ok`

Además, detecta automáticamente cuando el administrador menciona *"gastos comunes"*, exporta la planilla de Google Sheets como PDF y lo envía al grupo con la liquidación del mes.

```
Administrador → WhatsApp privado del bot
                       ↓
               WAHA (Docker) recibe el mensaje
                       ↓
               Backend FastAPI valida el remitente
                       ↓
               API de Claude reformatea el texto
                       ↓
               Bot le muestra el borrador al administrador
                       ↓
               Administrador dice "ok"
                       ↓
               WAHA publica en el grupo de vecinos
```

---

## Flujos soportados

| Acción del administrador | Respuesta del bot |
|---|---|
| Escribe cualquier texto | Muestra borrador formateado; publica al confirmar `ok` |
| Envía un PDF | Muestra vista previa; reenvía al grupo al confirmar `ok` |
| Escribe *"gastos comunes"* (o cualquier variante) | Exporta la planilla de Google Sheets como PDF, muestra vista previa; publica al confirmar `ok` |
| Responde `cancelar` | Descarta el borrador pendiente |

---

## Stack

| Componente | Tecnología |
|---|---|
| WhatsApp | [WAHA](https://waha.devlike.pro/) (NOWEB / Baileys) en Docker |
| Backend | Python 3.11 · FastAPI · uvicorn |
| Reformateo de texto | API de Claude (Anthropic) |
| Exportación de planilla | Google Sheets Export API · google-auth · pypdf |
| Base de datos | SQLite (pendientes de aprobación) |
| Infraestructura | Oracle Cloud Free Tier (1 GB RAM) |

---

## Instalación

### Prerrequisitos

- Docker y Docker Compose
- Un número de WhatsApp dedicado para el bot
- API key de Anthropic
- Cuenta de servicio de Google Cloud con acceso a la planilla (para el flujo de gastos comunes)

### 1. Clonar el repositorio

```bash
git clone <repo-url>
cd torre-arachanes
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env con los valores reales
```

Ver la tabla de variables más abajo.

### 3. Credenciales de Google Cloud (opcional)

Si usás el flujo de gastos comunes, descargá el JSON de la cuenta de servicio y colocalo fuera del repositorio:

```bash
# El archivo NO debe estar dentro del repo (está en .gitignore)
cp /ruta/a/cuenta-servicio.json ./credentials.json
```

### 4. Levantar los servicios

```bash
docker compose up -d --build
```

### 5. Vincular el número de WhatsApp

```bash
# Abrí el panel de WAHA y escaneá el QR
open http://localhost:3000/dashboard
```

Una vez vinculado, el backend se configura solo al reiniciarse.

---

## Variables de entorno

| Variable | Requerida | Descripción |
|---|---|---|
| `AUTHORIZED_NUMBER` | ✅ | JID(s) autorizados, separados por coma (`59891234567@c.us,59892345678@c.us`) |
| `AUTHORIZED_LID` | — | JID alternativo en formato `@lid` (algunos clientes de WhatsApp lo usan) |
| `GROUP_JID` | ✅ | JID del grupo de vecinos (obtenido via `GET /api/default/chats`) |
| `CLAUDE_API_KEY` | ✅ | API key de Anthropic |
| `WEBHOOK_SECRET` | ✅ | Token compartido entre WAHA y el backend (`openssl rand -hex 32`) |
| `WAHA_API_KEY` | — | API key de WAHA (si está configurada en el dashboard) |
| `SHEET_ID` | — | ID de la hoja de Google Sheets para gastos comunes |
| `SHEET_GIDS` | — | GIDs de las pestañas a exportar, separados por coma |
| `GOOGLE_CREDENTIALS_PATH` | — | Ruta al JSON de la cuenta de servicio (default: `/app/credentials.json`) |

---

## Uso

El administrador interactúa exclusivamente por WhatsApp privado con el número del bot:

```
Admin:  "el ascensor no funciona hasta el miércoles"
Bot:    [BORRADOR PARA EL GRUPO]

        Se informa a los vecinos que el *ascensor* se encuentra fuera
        de servicio hasta el *miércoles*.

        Respondé 'ok' para publicar o 'cancelar' para descartar.

Admin:  ok
Bot:    ✓ Publicado en el grupo.
```

```
Admin:  "gastos comunes"
Bot:    [PDF con la planilla adjunto]
        Se adjunta la liquidación de gastos comunes correspondiente
        al mes de *junio* 2026.

        Respondé 'ok' para publicar el PDF al grupo o 'cancelar' para descartar.

Admin:  ok
Bot:    ✓ PDF enviado al grupo.
```

---

## Desarrollo

```bash
# Instalar dependencias de desarrollo
pip install -r requirements-dev.txt

# Correr los tests
pytest tests/

# Correr el backend localmente (requiere .env configurado)
uvicorn app.main:app --reload
```

---

## Seguridad

- Solo mensajes del/los número(s) en `AUTHORIZED_NUMBER` son procesados; el resto se ignora silenciosamente.
- El webhook del backend requiere el header `X-Hook-Token` (configurado vía `WEBHOOK_SECRET`).
- El contenedor de Docker corre en red privada; el backend no está expuesto a internet directamente.
- Las credenciales de Google Cloud y el archivo `.env` están en `.gitignore` y nunca se commitean.
