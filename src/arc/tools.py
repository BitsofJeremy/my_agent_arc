"""Tool registry, schemas, and implementations for the ARC agent framework.

Provides Ollama-compatible tool schemas and async implementations for each
tool the agent can call.  A central dispatcher (:func:`execute_tool`) routes
tool-call requests from the agentic loop to the correct handler.

Tools
-----
- **search_memory** — query ChromaDB long-term memory via RAG.
- **save_to_memory** — persist an important fact to long-term memory.
- **write_heartbeat** — rewrite the *Current Instructions* section of
  ``heartbeat.md`` so the agent can program its own future behavior.
"""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from arc import memory
from arc.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ollama-compatible tool schemas
# ---------------------------------------------------------------------------

_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Search the agent's long-term memory for relevant context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for long-term memory",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_to_memory",
            "description": "Save an important fact or decision to long-term memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": "Important fact or decision to remember",
                    },
                },
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_heartbeat",
            "description": (
                "Write instructions for the agent's next heartbeat cycle. "
                "This allows the agent to program its own future behavior."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instructions": {
                        "type": "string",
                        "description": "Instructions for the agent's next heartbeat cycle",
                    },
                },
                "required": ["instructions"],
            },
        },
    },
]


def get_tool_schemas() -> list[dict[str, Any]]:
    """Return Ollama-compatible tool schemas for injection into chat calls.

    Merges built-in schemas with any MCP server tools.  Built-in tools take
    priority when names conflict.
    """
    from arc.mcp_client import get_mcp_manager

    schemas = list(_TOOL_SCHEMAS)
    manager = get_mcp_manager()
    if manager is not None:
        builtin_names = {s["function"]["name"] for s in _TOOL_SCHEMAS}
        for schema in manager.get_tool_schemas():
            if schema["function"]["name"] not in builtin_names:
                schemas.append(schema)
    return schemas


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def tool_search_memory(query: str) -> str:
    """Search long-term memory and return formatted results.

    Delegates to :func:`arc.memory.search_memory`.  Returns a
    human-readable summary of matching memories or a *"No relevant memories
    found."* sentinel when the result set is empty.
    """
    logger.debug("search_memory called with query=%r", query)
    results: list[str] = await memory.search_memory(query)

    if not results:
        return "No relevant memories found."

    formatted_lines = [f"- {item}" for item in results]
    return "Relevant memories:\n" + "\n".join(formatted_lines)


async def tool_save_to_memory(fact: str) -> str:
    """Persist an important fact to long-term memory.

    Delegates to :func:`arc.memory.save_to_memory` and returns a
    confirmation string.
    """
    logger.debug("save_to_memory called with fact=%r", fact)
    await memory.save_to_memory(fact)
    return f"Saved to memory: {fact}"


async def tool_write_heartbeat(instructions: str) -> str:
    """Rewrite the *Current Instructions* section of ``heartbeat.md``.

    Reads the current heartbeat file, locates the ``## Current Instructions``
    heading, replaces everything from that heading to the next heading (or EOF)
    with the new *instructions*, and writes the file back.

    This is the mechanism through which the agent programs its own future
    behavior across heartbeat cycles.
    """
    settings = get_settings()
    heartbeat_path = Path(settings.heartbeat_path)

    logger.debug(
        "write_heartbeat called — path=%s, instructions=%r",
        heartbeat_path,
        instructions,
    )

    content = heartbeat_path.read_text(encoding="utf-8")

    # Replace everything after "## Current Instructions" up to the next
    # heading (## …) or end-of-file with the new instructions.
    new_section = f"## Current Instructions\n{instructions}\n"
    updated, count = re.subn(
        r"## Current Instructions\n.*?(?=\n## |\Z)",
        new_section.rstrip("\n"),
        content,
        count=1,
        flags=re.DOTALL,
    )

    if count == 0:
        # Section header not found — append it.
        updated = content.rstrip("\n") + "\n\n" + new_section

    heartbeat_path.write_text(updated, encoding="utf-8")
    logger.info("Heartbeat instructions updated at %s", heartbeat_path)
    return "Heartbeat instructions updated successfully."


# ---------------------------------------------------------------------------
# Tool registry & dispatcher
# ---------------------------------------------------------------------------

# Maps tool names (matching the schema ``function.name``) to their async
# implementation callables.
TOOL_REGISTRY: dict[str, Callable[..., Coroutine[Any, Any, str]]] = {
    "search_memory": tool_search_memory,
    "save_to_memory": tool_save_to_memory,
    "write_heartbeat": tool_write_heartbeat,
}


async def execute_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    """Dispatch a tool call by name and return the result string.

    Parameters
    ----------
    tool_name:
        The tool to invoke (must match a key in :data:`TOOL_REGISTRY`).
    arguments:
        A mapping of parameter names to values, forwarded as keyword
        arguments to the tool function.

    Returns
    -------
    str
        The tool's result on success, or a human-readable error message on
        failure (unknown tool, execution error, etc.).
    """
    handler = TOOL_REGISTRY.get(tool_name)

    if handler is None:
        # Fall back to MCP servers for non-built-in tools.
        from arc.mcp_client import get_mcp_manager

        manager = get_mcp_manager()
        if manager is not None and manager.has_tool(tool_name):
            try:
                result = await manager.call_tool(tool_name, arguments)
                logger.debug("MCP tool %s returned: %s", tool_name, result[:200])
                return result
            except Exception as exc:
                msg = f"Error executing MCP tool {tool_name}: {exc}"
                logger.exception(msg)
                return msg

        available = ", ".join(sorted(TOOL_REGISTRY))
        msg = f"Error: Unknown tool '{tool_name}'. Available tools: {available}"
        logger.warning(msg)
        return msg

    try:
        # Filter arguments to only those the handler actually accepts,
        # so hallucinated extra params from the LLM don't crash the call.
        sig = inspect.signature(handler)
        accepted = set(sig.parameters.keys())
        filtered_args = {k: v for k, v in arguments.items() if k in accepted}

        result = await handler(**filtered_args)
    except Exception as exc:
        msg = f"Error executing {tool_name}: {exc}"
        logger.exception(msg)
        return msg

    logger.debug("Tool %s returned: %s", tool_name, result[:200])
    return result
