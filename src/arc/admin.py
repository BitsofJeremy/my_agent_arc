"""ARC admin dashboard — FastAPI + Jinja2 web interface.

Provides a lightweight admin panel for monitoring the agent: viewing database
stats, browsing recent messages, live-streaming logs, editing soul/heartbeat
configuration files, and manually triggering heartbeat/cron/compaction.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from jinja2 import Environment, FileSystemLoader

from arc.config import PROJECT_ROOT, get_settings
from arc.context_manager import maybe_compact
from arc.database import get_db
from arc.gateway import cron_trigger, heartbeat_trigger
from arc.mcp_client import get_mcp_manager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Template setup
# ---------------------------------------------------------------------------

_template_env = Environment(
    loader=FileSystemLoader(str(PROJECT_ROOT / "templates")),
    autoescape=True,
)


def _render(template_name: str, **context: object) -> HTMLResponse:
    """Render a Jinja2 template and return it as an ``HTMLResponse``."""
    template = _template_env.get_template(template_name)
    html = template.render(**context)
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# SSE log handler — broadcasts log records to connected clients
# ---------------------------------------------------------------------------

_LOG_QUEUES: set[asyncio.Queue[str]] = set()


class _SSELogHandler(logging.Handler):
    """Logging handler that enqueues formatted records for SSE broadcast.

    Each connected SSE client registers its own :class:`asyncio.Queue`.
    When a log record is emitted, the formatted line is placed into every
    registered queue so all clients receive it.
    """

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        stale_queues: list[asyncio.Queue[str]] = []
        for queue in _LOG_QUEUES:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                stale_queues.append(queue)
        # Remove any queues that are full (client likely disconnected).
        for q in stale_queues:
            _LOG_QUEUES.discard(q)


def _install_sse_handler() -> None:
    """Attach the SSE log handler to the root ``arc`` logger."""
    handler = _SSELogHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s — %(message)s")
    )
    root_logger = logging.getLogger("arc")
    # Avoid duplicate handlers on repeated calls.
    if not any(isinstance(h, _SSELogHandler) for h in root_logger.handlers):
        root_logger.addHandler(handler)


async def _log_event_generator() -> AsyncGenerator[str, None]:
    """Yield SSE-formatted log events from a per-client queue."""
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
    _LOG_QUEUES.add(queue)
    try:
        while True:
            line = await queue.get()
            yield f"data: {line}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        _LOG_QUEUES.discard(queue)


# ---------------------------------------------------------------------------
# Allowed editor filenames
# ---------------------------------------------------------------------------

_EDITABLE_FILES: dict[str, str] = {
    "soul": "soul_path",
    "heartbeat": "heartbeat_path",
}


def _resolve_editable_path(filename: str) -> Path:
    """Return the filesystem path for an editable file, or raise 404."""
    settings_attr = _EDITABLE_FILES.get(filename)
    if settings_attr is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown file: {filename!r}. Must be one of {list(_EDITABLE_FILES)}.",
        )
    settings = get_settings()
    return Path(getattr(settings, settings_attr))


# ---------------------------------------------------------------------------
# Route definitions
# ---------------------------------------------------------------------------


def _register_routes(app: FastAPI) -> None:  # noqa: C901 — route registration
    """Define all admin routes on *app*."""

    # -- Dashboard ----------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        """Show database stats and recent messages."""
        settings = get_settings()
        db_path = Path(settings.sqlite_db_path)

        # DB file size
        try:
            db_size_bytes = os.path.getsize(db_path)
        except OSError:
            db_size_bytes = 0

        # Message count + compacted node count + recent messages
        async with get_db() as db:
            row = await (await db.execute("SELECT COUNT(*) AS cnt FROM messages")).fetchone()
            message_count: int = row["cnt"] if row else 0  # type: ignore[index]

            row = await (
                await db.execute("SELECT COUNT(*) AS cnt FROM compacted_nodes")
            ).fetchone()
            compacted_count: int = row["cnt"] if row else 0  # type: ignore[index]

            cursor = await db.execute(
                """
                SELECT id, role, content, created_at
                FROM   messages
                ORDER BY created_at DESC
                LIMIT  20
                """
            )
            recent_messages = [dict(r) for r in await cursor.fetchall()]

        # MCP server info
        mcp_info: list[dict[str, Any]] = []
        manager = get_mcp_manager()
        if manager is not None:
            for name, conn in manager.servers.items():
                mcp_info.append({
                    "name": name,
                    "tool_count": len(conn.tools),
                    "tools": [t["function"]["name"] for t in conn.tools],
                })

        return _render(
            "dashboard.html",
            db_size_bytes=db_size_bytes,
            message_count=message_count,
            compacted_count=compacted_count,
            recent_messages=recent_messages,
            mcp_servers=mcp_info,
        )

    # -- Live logs page -----------------------------------------------------

    @app.get("/logs", response_class=HTMLResponse)
    async def logs_page(request: Request) -> HTMLResponse:
        """Render the log viewer with message history and live stream."""
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT id, role, content, tool_name, session_id, created_at
                FROM   messages
                ORDER BY created_at DESC
                LIMIT  100
                """
            )
            messages = [dict(r) for r in await cursor.fetchall()]
        return _render("logs.html", messages=messages)

    # -- SSE log stream -----------------------------------------------------

    @app.get("/api/logs/stream")
    async def log_stream(request: Request) -> StreamingResponse:
        """Stream log records as Server-Sent Events."""
        return StreamingResponse(
            _log_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # -- Editor (GET) -------------------------------------------------------

    @app.get("/editor/{filename}", response_class=HTMLResponse)
    async def editor_page(filename: str) -> HTMLResponse:
        """Show a textarea editor for *soul.md* or *heartbeat.md*."""
        file_path = _resolve_editable_path(filename)
        try:
            content = file_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = ""
        return _render("editor.html", filename=filename, content=content)

    # -- Editor (POST) ------------------------------------------------------

    @app.post("/editor/{filename}")
    async def editor_save(filename: str, content: str = Form(...)) -> RedirectResponse:
        """Save edited content back to the file."""
        file_path = _resolve_editable_path(filename)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        logger.info("Saved %s (%d bytes) via admin editor", file_path, len(content))
        return RedirectResponse(url=f"/editor/{filename}", status_code=303)

    # -- Trigger: heartbeat -------------------------------------------------

    @app.post("/trigger/heartbeat")
    async def trigger_heartbeat() -> RedirectResponse:
        """Manually fire the heartbeat cycle."""
        logger.info("Manual heartbeat trigger via admin")
        await heartbeat_trigger()
        return RedirectResponse(url="/", status_code=303)

    # -- Trigger: cron ------------------------------------------------------

    @app.post("/trigger/cron")
    async def trigger_cron(prompt: str = Form(...)) -> RedirectResponse:
        """Fire a cron-style prompt through the agent."""
        logger.info("Manual cron trigger via admin: %s", prompt[:120])
        await cron_trigger(prompt)
        return RedirectResponse(url="/", status_code=303)

    # -- Chat page ----------------------------------------------------------

    _ADMIN_CHAT_SESSION = "admin-chat"

    @app.get("/chat", response_class=HTMLResponse)
    async def chat_page(request: Request) -> HTMLResponse:
        """Show the chat interface with conversation history."""
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT role, content, created_at
                FROM   messages
                WHERE  session_id = ?
                ORDER BY created_at ASC
                """,
                (_ADMIN_CHAT_SESSION,),
            )
            history = [dict(r) for r in await cursor.fetchall()]
        return _render("chat.html", history=history)

    @app.post("/api/chat")
    async def chat_api(request: Request) -> JSONResponse:
        """Process a chat message and return the agent response."""
        from arc.agent import run_agent

        body = await request.json()
        user_message = body.get("message", "").strip()
        if not user_message:
            return JSONResponse(
                {"error": "Empty message"}, status_code=400
            )

        response = await run_agent(
            user_message,
            source="admin",
            session_id=_ADMIN_CHAT_SESSION,
        )
        return JSONResponse({"response": response})

    # -- Trigger: compaction ------------------------------------------------

    @app.post("/compact")
    async def trigger_compact() -> RedirectResponse:
        """Manually run context compaction."""
        logger.info("Manual compaction trigger via admin")
        compacted = await maybe_compact()
        if compacted:
            logger.info("Compaction completed successfully")
        else:
            logger.info("Compaction skipped (threshold not met)")
        return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_admin_app() -> FastAPI:
    """Create and return the ARC admin :class:`FastAPI` application."""
    app = FastAPI(title="ARC Admin", version="0.1.0")
    _install_sse_handler()
    _register_routes(app)
    logger.info("Admin dashboard app created")
    return app
