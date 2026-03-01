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
- **write_skill** — create a new MCP tool server and hot-reload.
- **list_skills** — list all connected MCP servers and their tools.
- **remove_skill** — remove an ARC-generated skill server.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from collections.abc import Callable, Coroutine
from pathlib import Path
from string import Template
from typing import Any

from arc import memory
from arc.config import PROJECT_ROOT, get_settings

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
    {
        "type": "function",
        "function": {
            "name": "write_skill",
            "description": (
                "Create a new skill by generating an MCP tool server. "
                "The code parameter must be a complete Python script that defines "
                "MCP tools using the @server.list_tools() and @server.call_tool() "
                "decorators. The server boilerplate is added automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Skill name (alphanumeric and underscores only, e.g. 'weather')",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of what this skill does",
                    },
                    "code": {
                        "type": "string",
                        "description": (
                            "Python code defining MCP tools. Must include "
                            "@server.list_tools() and @server.call_tool() decorated functions. "
                            "BOTH decorated functions MUST be 'async def' — not plain 'def'. "
                            "Already available (do NOT import or redefine): "
                            "server, Server, Tool, TextContent, stdio_server, asyncio. "
                            "Only include imports for additional libraries your tool needs "
                            "(e.g. 'import datetime', 'import random'). "
                            "Do NOT include 'import server' — server is already defined."
                        ),
                    },
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "pip package names required by this skill "
                            "(e.g. ['requests', 'pytz']). "
                            "'mcp' is always included automatically — do not list it."
                        ),
                    },
                },
                "required": ["name", "description", "code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "List all connected MCP skill servers and their available tools.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_skill",
            "description": "Remove an ARC-generated skill server and its tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the skill server to remove",
                    },
                },
                "required": ["name"],
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
# Skill self-authoring tools
# ---------------------------------------------------------------------------

_ARC_GENERATED_MARKER = "# ARC-generated skill server"
_TOOLS_DIR = PROJECT_ROOT / "tools"
_MCP_CONFIG_PATH = PROJECT_ROOT / "data" / "mcp_servers.json"

_SKILL_TEMPLATE = Template('''\
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
$deps# ]
# ///
$marker: $name
# $description

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
import asyncio

server = Server("$name")

$code

async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
''')


def _validate_skill_name(name: str) -> str | None:
    """Return an error message if *name* is invalid, else ``None``."""
    if not name:
        return "Skill name cannot be empty."
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", name):
        return (
            f"Invalid skill name '{name}'. "
            "Must start with a letter and contain only letters, digits, and underscores."
        )
    return None


def _read_mcp_config() -> dict[str, Any]:
    """Read ``data/mcp_servers.json``."""
    if not _MCP_CONFIG_PATH.exists():
        return {"servers": {}}
    with open(_MCP_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _write_mcp_config(config: dict[str, Any]) -> None:
    """Write ``data/mcp_servers.json``."""
    with open(_MCP_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


async def tool_write_skill(
    name: str, description: str, code: str, dependencies: list[str] | None = None
) -> str:
    """Generate an MCP skill server file and hot-reload the MCP manager."""
    from arc.mcp_client import get_mcp_manager, reload_mcp_manager

    # Validate name.
    err = _validate_skill_name(name)
    if err:
        return f"Error: {err}"

    # Check for conflicts with built-in tools.
    builtin_names = {s["function"]["name"] for s in _TOOL_SCHEMAS}
    if name in builtin_names:
        return f"Error: '{name}' conflicts with a built-in tool name."

    # Strip imports that are already provided by the template boilerplate so
    # the model can't accidentally shadow or re-import them.
    _TEMPLATE_PROVIDED = {
        "from mcp.server import Server",
        "from mcp.server.stdio import stdio_server",
        "from mcp.types import TextContent, Tool",
        "import asyncio",
        "import server",
    }
    cleaned_lines = [
        line for line in code.splitlines()
        if line.strip() not in _TEMPLATE_PROVIDED
    ]
    code = "\n".join(cleaned_lines)

    # Build PEP 723 deps block — mcp always first, then caller extras (deduplicated).
    all_deps = ["mcp"] + [d for d in (dependencies or []) if d != "mcp"]
    deps_block = "".join(f'#   "{dep}",\n' for dep in all_deps)

    # Generate the server file.
    _TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    server_file = _TOOLS_DIR / f"{name}_server.py"

    source = _SKILL_TEMPLATE.substitute(
        marker=_ARC_GENERATED_MARKER,
        name=name,
        description=description,
        deps=deps_block,
        code=code,
    )
    server_file.write_text(source, encoding="utf-8")
    logger.info("Wrote skill server to %s", server_file)

    # Update mcp_servers.json.
    config = _read_mcp_config()
    config.setdefault("servers", {})[name] = {
        "command": "uv",
        "args": ["run", f"tools/{name}_server.py"],
    }
    _write_mcp_config(config)
    logger.info("Updated mcp_servers.json with skill '%s'", name)

    # Hot-reload MCP connections.
    manager = await reload_mcp_manager()
    if manager is not None:
        info = manager.get_server_info()
        for server_info in info:
            if server_info["name"] == name:
                tools_list = ", ".join(server_info["tools"])
                return (
                    f"Skill '{name}' created and loaded successfully. "
                    f"Available tools: {tools_list}"
                )

    return f"Skill '{name}' created. Restart ARC to activate it."


async def tool_list_skills() -> str:
    """List all connected MCP skill servers and their tools."""
    from arc.mcp_client import get_mcp_manager

    manager = get_mcp_manager()
    if manager is None or manager.server_count == 0:
        return "No MCP skill servers connected."

    info = manager.get_server_info()
    lines: list[str] = []
    for server in info:
        tools_str = ", ".join(server["tools"]) or "(no tools)"
        lines.append(f"- **{server['name']}**: {tools_str} ({server['tool_count']} tools)")

    return "Connected skill servers:\n" + "\n".join(lines)


async def tool_remove_skill(name: str) -> str:
    """Remove an ARC-generated skill server."""
    from arc.mcp_client import reload_mcp_manager

    err = _validate_skill_name(name)
    if err:
        return f"Error: {err}"

    server_file = _TOOLS_DIR / f"{name}_server.py"

    # Safety check: only remove ARC-generated files.
    if server_file.exists():
        content = server_file.read_text(encoding="utf-8")
        if _ARC_GENERATED_MARKER not in content:
            return f"Error: '{name}' was not generated by ARC — refusing to delete."
        server_file.unlink()
        logger.info("Deleted skill server %s", server_file)
    else:
        logger.warning("Skill file %s not found — removing from config only", server_file)

    # Remove from mcp_servers.json.
    config = _read_mcp_config()
    if name in config.get("servers", {}):
        del config["servers"][name]
        _write_mcp_config(config)
        logger.info("Removed '%s' from mcp_servers.json", name)

    # Hot-reload.
    await reload_mcp_manager()

    return f"Skill '{name}' removed successfully."


# ---------------------------------------------------------------------------
# Tool registry & dispatcher
# ---------------------------------------------------------------------------

# Maps tool names (matching the schema ``function.name``) to their async
# implementation callables.
TOOL_REGISTRY: dict[str, Callable[..., Coroutine[Any, Any, str]]] = {
    "search_memory": tool_search_memory,
    "save_to_memory": tool_save_to_memory,
    "write_heartbeat": tool_write_heartbeat,
    "write_skill": tool_write_skill,
    "list_skills": tool_list_skills,
    "remove_skill": tool_remove_skill,
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
