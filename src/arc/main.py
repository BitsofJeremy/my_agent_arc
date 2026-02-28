"""ARC entry point — wires together the Telegram bot, admin dashboard, and scheduler.

Starts three subsystems concurrently:

1. **Telegram bot** — long-polling for user messages.
2. **APScheduler** — periodic heartbeat trigger.
3. **Uvicorn** — serves the FastAPI admin dashboard.

All subsystems are torn down gracefully on ``SIGINT`` / ``SIGTERM`` or
``KeyboardInterrupt``.
"""

from __future__ import annotations

import asyncio
import logging
import signal

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from arc.admin import create_admin_app
from arc.config import get_settings
from arc.database import init_db
from arc.gateway import create_telegram_app, heartbeat_trigger

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Async entry point
# ---------------------------------------------------------------------------


async def start() -> None:
    """Initialise all subsystems and run until interrupted."""
    settings = get_settings()
    logger.info("ARC starting — admin on %s:%s", settings.admin_host, settings.admin_port)

    # -- Database -----------------------------------------------------------
    await init_db()

    # -- Telegram bot -------------------------------------------------------
    telegram_app = create_telegram_app()

    # -- FastAPI admin ------------------------------------------------------
    admin_app = create_admin_app()

    # -- APScheduler --------------------------------------------------------
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        heartbeat_trigger,
        "interval",
        minutes=settings.heartbeat_interval_minutes,
        id="heartbeat",
    )
    scheduler.start()
    logger.info(
        "Scheduler started — heartbeat every %d min",
        settings.heartbeat_interval_minutes,
    )

    # -- Start Telegram polling (non-blocking) ------------------------------
    await telegram_app.initialize()
    await telegram_app.start()
    if telegram_app.updater is None:
        raise RuntimeError("Telegram application was built without an Updater.")
    await telegram_app.updater.start_polling()
    logger.info("Telegram bot polling started")

    # -- Uvicorn (blocks until server shuts down) ---------------------------
    server_config = uvicorn.Config(
        admin_app,
        host=settings.admin_host,
        port=settings.admin_port,
        log_level="info",
    )
    server = uvicorn.Server(server_config)

    try:
        await server.serve()
    finally:
        # -- Graceful shutdown (runs even on SIGINT / SIGTERM) --------------
        logger.info("Shutting down ARC …")

        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

        if telegram_app.updater is not None:
            await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()
        logger.info("Telegram bot stopped")

        logger.info("ARC shutdown complete")


# ---------------------------------------------------------------------------
# Synchronous wrapper
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point — runs the async ``start()`` coroutine."""
    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        logger.info("Interrupted — goodbye")


if __name__ == "__main__":
    main()
