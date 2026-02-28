#!/usr/bin/env python3
"""A minimal MCP test server providing ping and echo tools.

Run standalone:  python tools/test_server.py
Used by ARC via data/mcp_servers.json as a stdio MCP server.
"""

from __future__ import annotations

import datetime

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("test-server")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="ping",
            description="Returns 'pong' with a timestamp. Use to verify MCP connectivity.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="echo",
            description="Echoes back the provided message.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to echo back",
                    },
                },
                "required": ["message"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "ping":
        now = datetime.datetime.now(datetime.UTC).isoformat()
        return [TextContent(type="text", text=f"pong — {now}")]

    if name == "echo":
        msg = arguments.get("message", "")
        return [TextContent(type="text", text=f"echo: {msg}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
