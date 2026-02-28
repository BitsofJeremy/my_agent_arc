"""Database initialization for OpenClaw — SQLite (async) and ChromaDB (persistent).

Provides:
    - ``init_db``          – create SQLite tables (WAL mode, idempotent).
    - ``get_db``           – async context-manager yielding an aiosqlite connection.
    - ``get_chroma_client`` – return a persistent ChromaDB client.
    - ``get_memory_collection`` – return (or create) the ``agent_memory`` collection.

Both database paths are read from ``openclaw.config.get_settings()``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite
import chromadb

from openclaw.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL schema
# ---------------------------------------------------------------------------

_MESSAGES_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool', 'system')),
    content         TEXT NOT NULL,
    tool_name       TEXT,
    tool_call_id    TEXT,
    token_estimate  INTEGER NOT NULL,
    is_compacted    BOOLEAN DEFAULT 0,
    session_id      TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_COMPACTED_NODES_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS compacted_nodes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    summary              TEXT NOT NULL,
    original_message_ids TEXT NOT NULL,
    token_estimate       INTEGER NOT NULL,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# Indexes for common access patterns
_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id);",
    "CREATE INDEX IF NOT EXISTS idx_messages_created ON messages (created_at);",
    "CREATE INDEX IF NOT EXISTS idx_messages_compacted ON messages (is_compacted);",
]

# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------


def _resolve_sqlite_path() -> Path:
    """Return the fully-resolved SQLite database path, creating parent dirs."""
    settings = get_settings()
    db_path = Path(settings.sqlite_db_path)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


async def init_db() -> None:
    """Create SQLite tables and enable WAL mode (idempotent).

    Safe to call multiple times — uses ``CREATE TABLE IF NOT EXISTS``.
    """
    db_path = _resolve_sqlite_path()
    logger.info("Initializing SQLite database at %s", db_path)

    async with aiosqlite.connect(db_path) as db:
        # WAL mode allows concurrent readers while writing.
        await db.execute("PRAGMA journal_mode=WAL;")

        await db.execute(_MESSAGES_TABLE_SQL)
        await db.execute(_COMPACTED_NODES_TABLE_SQL)

        for idx_sql in _INDEXES_SQL:
            await db.execute(idx_sql)

        await db.commit()

    logger.info("SQLite schema initialized successfully.")


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """Async context-manager that yields an ``aiosqlite.Connection``.

    Usage::

        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM messages")
            rows = await cursor.fetchall()

    The connection is closed automatically on exit.  Row-factory is set to
    ``aiosqlite.Row`` so results behave like dicts.
    """
    db_path = _resolve_sqlite_path()

    db: aiosqlite.Connection | None = None
    try:
        db = await aiosqlite.connect(db_path)
        db.row_factory = aiosqlite.Row  # type: ignore[assignment]
        await db.execute("PRAGMA journal_mode=WAL;")
        yield db
    finally:
        if db is not None:
            await db.close()


# ---------------------------------------------------------------------------
# ChromaDB helpers
# ---------------------------------------------------------------------------

_chroma_client: chromadb.ClientAPI | None = None


def _resolve_chroma_path() -> Path:
    """Return the fully-resolved ChromaDB persistence path, creating dirs."""
    settings = get_settings()
    chroma_path = Path(settings.chromadb_path)
    if not chroma_path.is_absolute():
        chroma_path = Path.cwd() / chroma_path
    chroma_path.mkdir(parents=True, exist_ok=True)
    return chroma_path


def get_chroma_client() -> chromadb.ClientAPI:
    """Return a persistent ChromaDB client (singleton).

    The persistence directory is read from settings and created if it does
    not already exist.
    """
    global _chroma_client  # noqa: PLW0603

    if _chroma_client is None:
        chroma_path = _resolve_chroma_path()
        logger.info("Initializing ChromaDB client at %s", chroma_path)
        _chroma_client = chromadb.PersistentClient(path=str(chroma_path))

    return _chroma_client


def get_memory_collection() -> chromadb.Collection:
    """Return (or create) the ``agent_memory`` ChromaDB collection.

    Uses the singleton client from :func:`get_chroma_client`.
    """
    client = get_chroma_client()
    collection = client.get_or_create_collection(name="agent_memory")
    logger.info("ChromaDB collection 'agent_memory' ready.")
    return collection
