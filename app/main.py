import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Request

from .db import init_db
from .startup import run_startup_recovery
from .webhook import process_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialized.")
    # Run recovery in background so the /webhook endpoint is available immediately.
    # Recovery polls WAHA up to 120s; webhooks from WAHA must not be blocked during that wait.
    asyncio.create_task(run_startup_recovery())
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    # No token auth: backend has no external port — Docker internal network is
    # the security boundary. WAHA Core global-env webhooks don't send auth headers.
    body = await request.json()

    # Only process incoming messages (not status events, not sent-by-bot)
    if body.get("event") != "message":
        return {"status": "ignored"}

    payload = body.get("payload", {})
    background_tasks.add_task(process_message, payload)

    # T1: return 200 immediately — Claude runs in background
    return {"status": "queued"}
