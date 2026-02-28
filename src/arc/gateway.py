"""Gateway and trigger handlers for the ARC agent framework.

Provides the inbound integration points that feed messages into the agent:

- **Telegram Bot** — receives user messages via the Telegram Bot API and
  relays agent responses back to the chat.
- **Heartbeat trigger** — periodically reads ``heartbeat.md`` and, if it
  contains actionable instructions, sends them to the agent.
- **Cron trigger** — a generic scheduled-prompt mechanism driven by
  APScheduler.
- **Unified handler** — a single ``handle_trigger`` entry-point that every
  gateway funnels through for consistent logging and routing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from arc import agent
from arc.config import get_settings

logger = logging.getLogger(__name__)

# Default placeholder text that ships with a fresh ``heartbeat.md``.
# When the file contains only this (or is empty) the heartbeat is a no-op.
_HEARTBEAT_PLACEHOLDER = "No current instructions."


# ---------------------------------------------------------------------------
# Unified handler
# ---------------------------------------------------------------------------


async def handle_trigger(
    source: str,
    payload: str,
    session_id: str | None = None,
) -> str:
    """Single entry-point for every inbound trigger.

    Logs the trigger, delegates to :func:`arc.agent.run_agent`, and
    returns the agent's response.

    Parameters
    ----------
    source:
        A short label identifying the origin (e.g. ``"telegram"``,
        ``"heartbeat"``, ``"cron"``).
    payload:
        The text to send to the agent.
    session_id:
        Optional session scope for conversation isolation.

    Returns
    -------
    str
        The agent's response text.
    """
    logger.info(
        "Trigger received — source=%s, session=%s, payload=%s",
        source,
        session_id,
        payload[:120] + ("…" if len(payload) > 120 else ""),
    )

    result: str = await agent.run_agent(
        payload,
        source=source,
        session_id=session_id,
    )

    logger.info(
        "Trigger complete — source=%s, response=%s",
        source,
        result[:120] + ("…" if len(result) > 120 else ""),
    )
    return result


# ---------------------------------------------------------------------------
# Telegram Bot
# ---------------------------------------------------------------------------


async def telegram_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle an incoming Telegram text message.

    Extracts the user's message, routes it through :func:`handle_trigger`,
    and sends the agent's reply back to the chat.  All exceptions are caught
    and logged so that a single bad message never crashes the bot.
    """
    if update.effective_message is None or update.effective_message.text is None:
        logger.debug("Ignoring non-text update (id=%s)", update.update_id)
        return

    text: str = update.effective_message.text
    chat_id: str = str(update.effective_chat.id) if update.effective_chat else "unknown"

    logger.info("Telegram message from chat %s: %s", chat_id, text[:80])

    try:
        response = await handle_trigger(
            source="telegram",
            payload=text,
            session_id=chat_id,
        )
    except Exception:
        logger.exception("Error processing Telegram message from chat %s", chat_id)
        response = "Sorry, something went wrong while processing your message."

    try:
        await update.effective_message.reply_text(response)
    except Exception:
        logger.exception("Failed to send Telegram reply to chat %s", chat_id)


def create_telegram_app() -> Application:  # type: ignore[type-arg]
    """Build and return a configured ``python-telegram-bot`` Application.

    Reads the bot token from :func:`arc.config.get_settings` and
    registers a :class:`MessageHandler` for all text messages.

    Returns
    -------
    Application
        A fully-configured application ready for ``.run_polling()`` or
        ``.initialize()`` / ``.start()``.
    """
    settings = get_settings()

    if not settings.telegram_bot_token:
        raise RuntimeError(
            "Telegram bot token is not configured. "
            "Set ARC_TELEGRAM_BOT_TOKEN in your environment or .env file."
        )

    app: Application = (  # type: ignore[type-arg]
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, telegram_message_handler),
    )

    logger.info("Telegram application created and handler registered")
    return app


# ---------------------------------------------------------------------------
# Heartbeat trigger
# ---------------------------------------------------------------------------


async def heartbeat_trigger() -> None:
    """Read ``heartbeat.md`` and, if it has actionable content, send it to the agent.

    Designed to be called periodically by APScheduler.  The heartbeat file is
    considered *empty* (no-op) when its content is blank, whitespace-only, or
    matches the default placeholder text.
    """
    settings = get_settings()
    heartbeat_path = Path(settings.heartbeat_path)

    try:
        content = heartbeat_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning("Heartbeat file not found at %s — skipping", heartbeat_path)
        return
    except OSError:
        logger.exception("Failed to read heartbeat file at %s", heartbeat_path)
        return

    if not content or content == _HEARTBEAT_PLACEHOLDER:
        logger.debug("Heartbeat file is empty or placeholder — no action taken")
        return

    logger.info("Heartbeat triggered with content (%d chars)", len(content))

    try:
        result = await handle_trigger(
            source="heartbeat",
            payload=f"[HEARTBEAT] {content}",
        )
        logger.info("Heartbeat result: %s", result[:200])
    except Exception:
        logger.exception("Heartbeat trigger failed")


# ---------------------------------------------------------------------------
# Cron trigger
# ---------------------------------------------------------------------------


async def cron_trigger(prompt: str, name: str = "cron") -> None:
    """Send a scheduled prompt to the agent.

    Intended to be invoked by APScheduler for recurring or one-shot scheduled
    tasks.

    Parameters
    ----------
    prompt:
        The text prompt to send to the agent.
    name:
        A human-readable label for this cron job (used in the message prefix
        and in log output).
    """
    logger.info("Cron trigger fired — name=%s", name)

    try:
        result = await handle_trigger(
            source="cron",
            payload=f"[CRON:{name}] {prompt}",
        )
        logger.info("Cron [%s] result: %s", name, result[:200])
    except Exception:
        logger.exception("Cron trigger '%s' failed", name)
