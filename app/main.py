import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

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
    await run_startup_recovery()
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hook_token: str = Header(default=""),
) -> dict:
    from .config import get_settings

    if x_hook_token != get_settings().WEBHOOK_SECRET:
        logger.warning("Webhook received with invalid token.")
        raise HTTPException(status_code=401, detail="Unauthorized")

    body = await request.json()

    # Only process incoming messages (not status events, not sent-by-bot)
    if body.get("event") != "message":
        return {"status": "ignored"}

    payload = body.get("payload", {})
    background_tasks.add_task(process_message, payload)

    # T1: return 200 immediately — Claude runs in background
    return {"status": "queued"}
