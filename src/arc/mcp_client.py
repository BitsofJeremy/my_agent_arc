"""MCP (Model Context Protocol) client manager for the ARC agent framework.

Connects to external MCP tool servers at startup, discovers their tools, and
provides a unified interface for schema retrieval and tool execution.  Servers
are configured in ``data/mcp_servers.json``.
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from arc.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config path
# ---------------------------------------------------------------------------

_CONFIG_PATH: Path = PROJECT_ROOT / "data" / "mcp_servers.json"

# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


@dataclass
class ServerConnection:
    """State for a single connected MCP server."""

    name: str
    session: ClientSession
    tools: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# MCPManager
# ---------------------------------------------------------------------------


class MCPManager:
    """Manages connections to one or more MCP tool servers.

    Usage::

        manager = MCPManager()
        await manager.connect_all()   # reads data/mcp_servers.json
        schemas = manager.get_tool_schemas()
        result  = await manager.call_tool("web_search", {"query": "hello"})
        await manager.shutdown()
    """

    def __init__(self) -> None:
        self._exit_stack = contextlib.AsyncExitStack()
        self._servers: dict[str, ServerConnection] = {}
        self._tool_map: dict[str, str] = {}  # tool name → server name

    # -- Properties ---------------------------------------------------------

    @property
    def servers(self) -> dict[str, ServerConnection]:
        return self._servers

    @property
    def server_count(self) -> int:
        return len(self._servers)

    # -- Startup ------------------------------------------------------------

    async def connect_all(self) -> None:
        """Read the config file and connect to every listed MCP server."""
        config = self._load_config()
        servers_cfg: dict[str, Any] = config.get("servers", {})

        if not servers_cfg:
            logger.info("MCP: no servers configured in %s", _CONFIG_PATH)
            return

        for name, entry in servers_cfg.items():
            try:
                await self._connect_server(name, entry)
            except Exception:
                logger.exception("MCP: failed to connect server %r — skipping", name)

    async def _connect_server(self, name: str, entry: dict[str, Any]) -> None:
        """Launch and initialise a single MCP server."""
        command: str = entry["command"]
        args: list[str] = entry.get("args", [])
        env: dict[str, str] | None = entry.get("env")

        logger.info("MCP: connecting to %r (%s %s)", name, command, " ".join(args))

        params = StdioServerParameters(command=command, args=args, env=env)

        # Enter the stdio_client context — stays open until shutdown.
        read_stream, write_stream = await self._exit_stack.enter_async_context(
            stdio_client(params)
        )

        # Enter the ClientSession context.
        session: ClientSession = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        # Discover tools.
        tools_result = await session.list_tools()
        ollama_schemas = [self._convert_schema(tool) for tool in tools_result.tools]

        conn = ServerConnection(name=name, session=session, tools=ollama_schemas)
        self._servers[name] = conn

        for schema in ollama_schemas:
            tool_name = schema["function"]["name"]
            self._tool_map[tool_name] = name

        tool_names = [s["function"]["name"] for s in ollama_schemas]
        logger.info(
            "MCP: server %r connected — %d tools: %s",
            name,
            len(ollama_schemas),
            ", ".join(tool_names) or "(none)",
        )

    # -- Schema conversion --------------------------------------------------

    @staticmethod
    def _convert_schema(tool: Any) -> dict[str, Any]:
        """Convert an MCP ``Tool`` object to Ollama function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema or {
                    "type": "object",
                    "properties": {},
                },
            },
        }

    # -- Tool schemas -------------------------------------------------------

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Return all MCP tool schemas in Ollama format."""
        schemas: list[dict[str, Any]] = []
        for conn in self._servers.values():
            schemas.extend(conn.tools)
        return schemas

    def has_tool(self, name: str) -> bool:
        """Check whether an MCP server provides a tool with *name*."""
        return name in self._tool_map

    # -- Tool execution -----------------------------------------------------

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute an MCP tool and return the result as a string."""
        server_name = self._tool_map.get(name)
        if server_name is None:
            return f"Error: MCP tool '{name}' not found"

        conn = self._servers.get(server_name)
        if conn is None:
            return f"Error: MCP server '{server_name}' is not connected"

        logger.info("MCP: calling tool %s on server %s", name, server_name)
        result = await conn.session.call_tool(name, arguments)

        # Extract text content from the result.
        parts: list[str] = []
        for content_block in result.content:
            if hasattr(content_block, "text"):
                parts.append(content_block.text)
            else:
                parts.append(str(content_block))

        return "\n".join(parts) if parts else "(no output)"

    # -- Shutdown -----------------------------------------------------------

    async def shutdown(self) -> None:
        """Close all MCP server connections."""
        logger.info("MCP: shutting down %d server(s)", len(self._servers))
        try:
            await self._exit_stack.aclose()
        except RuntimeError:
            # anyio cancel scope issues during shutdown — log and continue.
            logger.warning("MCP: non-fatal error during shutdown (cancel scope)")
        self._servers.clear()
        self._tool_map.clear()

    # -- Server info --------------------------------------------------------

    def get_server_info(self) -> list[dict[str, Any]]:
        """Return a summary of connected servers and their tools."""
        info: list[dict[str, Any]] = []
        for name, conn in self._servers.items():
            info.append({
                "name": name,
                "tool_count": len(conn.tools),
                "tools": [t["function"]["name"] for t in conn.tools],
            })
        return info

    # -- Config loading -----------------------------------------------------

    @staticmethod
    def _load_config() -> dict[str, Any]:
        """Read and parse ``data/mcp_servers.json``."""
        if not _CONFIG_PATH.exists():
            logger.info("MCP: config file not found at %s", _CONFIG_PATH)
            return {"servers": {}}

        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("MCP: failed to read config %s: %s", _CONFIG_PATH, exc)
            return {"servers": {}}

        return data


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager: MCPManager | None = None


async def init_mcp_manager() -> MCPManager | None:
    """Create the global :class:`MCPManager` and connect to all servers.

    Returns ``None`` if no servers were configured or all failed.
    """
    global _manager  # noqa: PLW0603
    _manager = MCPManager()
    await _manager.connect_all()
    if _manager.server_count == 0:
        logger.info("MCP: no servers connected — MCP tools disabled")
    return _manager


async def reload_mcp_manager() -> MCPManager | None:
    """Replace the global :class:`MCPManager` with a fresh instance.

    Creates a new manager, connects to all configured servers, and replaces
    the module-level singleton.  The old manager's subprocesses are left to
    be cleaned up by the OS (avoids anyio cancel-scope issues with
    in-process shutdown during a reload).
    """
    global _manager  # noqa: PLW0603
    logger.info("MCP: reloading — creating fresh manager")
    old = _manager
    new = MCPManager()
    await new.connect_all()
    _manager = new
    # Best-effort shutdown of old manager.
    if old is not None:
        try:
            await old.shutdown()
        except Exception:
            logger.debug("MCP: old manager cleanup failed (non-fatal)")
    return _manager


def get_mcp_manager() -> MCPManager | None:
    """Return the global :class:`MCPManager`, or ``None`` if not initialised."""
    return _manager
