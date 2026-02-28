#!/usr/bin/env python3
# ARC-generated skill server: dice
# Roll dice

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
import asyncio

server = Server("dice")

import random

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="roll_dice",
            description="Roll a dice with the specified number of sides",
            inputSchema={
                "type": "object",
                "properties": {
                    "sides": {
                        "type": "integer",
                        "description": "Number of sides on the dice (default 6)",
                        "default": 6,
                        "minimum": 1
                    }
                },
                "required": []
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "roll_dice":
        raise ValueError(f"Unknown tool: {name}")
    
    sides = arguments.get("sides", 6)
    if not isinstance(sides, int) or sides < 1:
        raise ValueError("Number of sides must be a positive integer")
    
    result = random.randint(1, sides)
    
    return [
        TextContent(
            type="text",
            text=f"Rolled a {sides}-sided die: {result}"
        )
    ]

async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
