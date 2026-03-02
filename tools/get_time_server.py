#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mcp",
#   "pytz",
# ]
# ///
# ARC-generated skill server: get_time
# Get current time in Mountain timezone (America/Denver) with proper formatting and DST handling

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
import asyncio

server = Server("get_time")

import json
from datetime import datetime
import pytz

@server.list_tools()
async def list_tools():
    """List available tools in this skill server"""
    return [
        {
            "name": "get_local_time",
            "description": "Get current time in Mountain timezone (America/Denver) with formatted output"
        },
        {
            "name": "get_time_details", 
            "description": "Get detailed time information including UTC, Mountain time, and DST status"
        }
    ]

@server.call_tool()
async def get_local_time():
    """Get current time in Mountain timezone (America/Denver) with formatted output"""
    utc_now = datetime.now(pytz.UTC)
    mountain_tz = pytz.timezone('America/Denver')
    mountain_now = utc_now.astimezone(mountain_tz)
    
    # Check if DST is in effect
    is_dst = mountain_now.dst() is not None and mountain_now.dst().total_seconds() > 0
    
    return {
        "current_time": mountain_now.strftime("%A, %B %d, %Y at %I:%M %p %Z"),
        "utc_time": utc_now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "mountain_time": mountain_now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "timezone_name": mountain_now.tzname(),
        "timezone_info": "Mountain Time (UTC-7 MST / UTC-6 MDT)",
        "is_dst": is_dst,
        "formatted_response": f"The current time is {mountain_now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}."
    }

@server.call_tool()
async def get_time_details():
    """Get detailed time information including UTC, Mountain time, and DST status"""
    utc_now = datetime.now(pytz.UTC)
    mountain_tz = pytz.timezone('America/Denver')
    mountain_now = utc_now.astimezone(mountain_tz)
    
    # Check if DST is in effect
    is_dst = mountain_now.dst() is not None and mountain_now.dst().total_seconds() > 0
    
    return {
        "utc_time": utc_now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "mountain_time": mountain_now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "local_display": mountain_now.strftime("%A, %B %d, %Y at %I:%M %p %Z"),
        "timezone_name": mountain_now.tzname(),
        "timezone_offset": "UTC-7 (MST) / UTC-6 (MDT)",
        "is_dst": is_dst,
        "dst_status": "Currently in Daylight Saving Time" if is_dst else "Currently in Standard Time",
        "time_info": {
            "utc_offset": -7 if not is_dst else -6,
            "time_zone": "America/Denver",
            "location": "Mountain timezone (Boulder/Denver area)"
        }
    }

async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
