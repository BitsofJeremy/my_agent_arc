"""Context management and compaction for the OpenClaw agent framework.

Handles conversation history logging, token-aware context compaction via Ollama
summarisation, and assembly of the final prompt context (soul + compacted
summaries + recent messages) ready for ``ollama.chat()``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import ollama

from openclaw.config import get_settings
from openclaw.database import get_db
from openclaw.memory import save_to_memory

logger = logging.getLogger("openclaw.context_manager")


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Return a rough token count for *text* (≈ 4 characters per token).

    This is a fast heuristic — good enough for budget tracking without
    pulling in a real tokeniser.
    """
    return len(text) // 4


# ---------------------------------------------------------------------------
# Message logging
# ---------------------------------------------------------------------------


async def log_message(
    role: str,
    content: str,
    tool_name: str | None = None,
    tool_call_id: str | None = None,
    session_id: str | None = None,
) -> int:
    """Persist a single conversation turn to the ``messages`` table.

    Parameters
    ----------
    role:
        One of ``"user"``, ``"assistant"``, ``"tool"``, ``"system"``.
    content:
        The message body.
    tool_name:
        Optional tool identifier (for tool-result messages).
    tool_call_id:
        Optional upstream call ID linking a tool result to its invocation.
    session_id:
        Optional session scope; ``None`` means the default (global) session.

    Returns
    -------
    int
        The ``id`` of the newly inserted row.
    """
    tokens = estimate_tokens(content)

    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO messages (role, content, tool_name, tool_call_id,
                                  token_estimate, session_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (role, content, tool_name, tool_call_id, tokens, session_id),
        )
        await db.commit()
        message_id: int = cursor.lastrowid  # type: ignore[assignment]

    logger.debug(
        "Logged %s message (id=%d, ~%d tokens, session=%s)",
        role,
        message_id,
        tokens,
        session_id,
    )
    return message_id


# ---------------------------------------------------------------------------
# History retrieval
# ---------------------------------------------------------------------------


async def get_recent_history(
    session_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, str | int | None]]:
    """Fetch the most recent non-compacted messages.

    Parameters
    ----------
    session_id:
        Scope to a specific session; ``None`` returns the default session.
    limit:
        Maximum number of messages to return (most-recent first in the DB
        query, but returned in chronological order).

    Returns
    -------
    list[dict]
        Each dict contains the columns of the ``messages`` table.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, role, content, tool_name, tool_call_id,
                   token_estimate, session_id, created_at
            FROM   messages
            WHERE  is_compacted = 0
              AND  (session_id IS ? OR (? IS NULL AND session_id IS NULL))
            ORDER BY created_at DESC
            LIMIT  ?
            """,
            (session_id, session_id, limit),
        )
        rows = await cursor.fetchall()

    # Return in chronological order (oldest first).
    return [dict(row) for row in reversed(rows)]


# ---------------------------------------------------------------------------
# Compacted context
# ---------------------------------------------------------------------------


async def get_compacted_context() -> str:
    """Return all compacted summaries joined into a single string.

    Summaries are ordered chronologically so the resulting text reads as a
    coherent narrative of earlier conversation.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT summary
            FROM   compacted_nodes
            ORDER BY created_at ASC
            """
        )
        rows = await cursor.fetchall()

    return "\n\n".join(row["summary"] for row in rows)


# ---------------------------------------------------------------------------
# Compaction engine
# ---------------------------------------------------------------------------


async def maybe_compact(session_id: str | None = None) -> bool:
    """Run compaction if non-compacted messages exceed the token budget.

    The threshold is ``settings.context_window_tokens * settings.compaction_threshold``.
    When exceeded the *older half* of non-compacted messages is summarised by
    Ollama and stored as a compacted node.

    Returns
    -------
    bool
        ``True`` if compaction was performed, ``False`` otherwise.
    """
    settings = get_settings()
    token_budget = int(settings.context_window_tokens * settings.compaction_threshold)

    # --- 1. Calculate total tokens in non-compacted messages ----------------
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT COALESCE(SUM(token_estimate), 0) AS total_tokens
            FROM   messages
            WHERE  is_compacted = 0
              AND  (session_id IS ? OR (? IS NULL AND session_id IS NULL))
            """,
            (session_id, session_id),
        )
        row = await cursor.fetchone()
        total_tokens: int = row["total_tokens"]  # type: ignore[index]

    if total_tokens <= token_budget:
        logger.debug(
            "Compaction not needed (%d tokens <= %d budget)",
            total_tokens,
            token_budget,
        )
        return False

    logger.info(
        "Compaction triggered: %d tokens > %d budget — summarising older messages",
        total_tokens,
        token_budget,
    )

    # --- 2. Fetch the older half of non-compacted messages ------------------
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, role, content
            FROM   messages
            WHERE  is_compacted = 0
              AND  (session_id IS ? OR (? IS NULL AND session_id IS NULL))
            ORDER BY created_at ASC
            """,
            (session_id, session_id),
        )
        all_rows = await cursor.fetchall()

    midpoint = len(all_rows) // 2
    if midpoint == 0:
        logger.warning("Not enough messages to compact (total=%d)", len(all_rows))
        return False

    older_messages = all_rows[:midpoint]
    message_ids: list[int] = [row["id"] for row in older_messages]

    # --- 3. Format as conversation text and ask Ollama to summarise ---------
    conversation_text = "\n".join(
        f"{row['role']}: {row['content']}" for row in older_messages
    )

    try:
        response = ollama.chat(
            model=settings.ollama_model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Summarize this conversation concisely, preserving key "
                        "facts and decisions:\n\n"
                        f"{conversation_text}"
                    ),
                }
            ],
        )
        summary: str = response["message"]["content"]
    except Exception:
        logger.exception("Ollama summarisation failed — skipping compaction")
        return False

    summary_tokens = estimate_tokens(summary)
    ids_csv = ",".join(str(mid) for mid in message_ids)

    # --- 4. Store the compacted node ----------------------------------------
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO compacted_nodes (summary, original_message_ids, token_estimate)
            VALUES (?, ?, ?)
            """,
            (summary, ids_csv, summary_tokens),
        )

        # --- 5. Mark originals as compacted ---------------------------------
        placeholders = ",".join("?" for _ in message_ids)
        await db.execute(
            f"UPDATE messages SET is_compacted = 1 WHERE id IN ({placeholders})",  # noqa: S608
            message_ids,
        )
        await db.commit()

    logger.info(
        "Compacted %d messages (%s) into summary (~%d tokens)",
        len(message_ids),
        ids_csv,
        summary_tokens,
    )

    # --- 6. Persist summary into ChromaDB long-term memory ------------------
    try:
        await save_to_memory(summary, metadata={"type": "compaction"})
    except Exception:
        logger.exception("Failed to save compaction summary to ChromaDB")

    return True


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


async def build_context(
    session_id: str | None = None,
) -> list[dict[str, str]]:
    """Assemble the full prompt context for an ``ollama.chat()`` call.

    The returned list contains:

    1. A **system** message composed of the soul prompt (``soul.md``) and any
       compacted conversation summaries.
    2. The recent (non-compacted) conversation messages in chronological order.

    Parameters
    ----------
    session_id:
        Scope to a specific conversation session.

    Returns
    -------
    list[dict[str, str]]
        Messages in the ``{"role": "…", "content": "…"}`` format expected by
        ``ollama.chat()``.
    """
    settings = get_settings()

    # --- Read the soul prompt -----------------------------------------------
    soul_path = Path(settings.soul_path)
    try:
        soul_text = soul_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Soul file not found at %s — using empty system prompt", soul_path)
        soul_text = ""

    # --- Gather compacted summaries -----------------------------------------
    compacted = await get_compacted_context()

    # --- Build the system message -------------------------------------------
    system_parts: list[str] = []
    if soul_text:
        system_parts.append(soul_text.strip())
    if compacted:
        system_parts.append(
            "## Previous Conversation Context\n\n" + compacted.strip()
        )

    system_message = "\n\n".join(system_parts)

    messages: list[dict[str, str]] = []
    if system_message:
        messages.append({"role": "system", "content": system_message})

    # --- Append recent history ----------------------------------------------
    history = await get_recent_history(session_id=session_id)
    for msg in history:
        messages.append({
            "role": str(msg["role"]),
            "content": str(msg["content"]),
        })

    logger.debug(
        "Built context: %d messages (%d system, %d history)",
        len(messages),
        1 if system_message else 0,
        len(history),
    )
    return messages
