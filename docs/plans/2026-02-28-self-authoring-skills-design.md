# Self-Authoring Skills — Design Document

## Problem

ARC's skill set is currently fixed at startup: three built-in tools plus whatever MCP servers are pre-configured. To learn new capabilities, a human must manually write an MCP server file and restart ARC. The agent should be able to create its own tools at runtime.

## Approach

Add three new built-in tools (`write_skill`, `list_skills`, `remove_skill`) that let ARC generate MCP server Python files from a template, register them in `mcp_servers.json`, and hot-reload the MCP manager — all without restarting.

## Architecture

```
ARC decides it needs a new skill
    │
    ▼
Calls write_skill(name, description, tools_spec)
    │
    ▼
tools.py generates tools/<name>_server.py from template
    │
    ▼
Updates data/mcp_servers.json with new server entry
    │
    ▼
Calls MCPManager.reload()  (shutdown → reconnect all)
    │
    ▼
New tools immediately available in ARC's next LLM call
```

## New Built-in Tools

### `write_skill(name, description, code)`

- `name`: Skill server name (e.g. "weather")
- `description`: What the skill does
- `code`: Complete Python source for tool implementations — inserted into an MCP server template

The tool:
1. Validates the name (alphanumeric + underscores only)
2. Generates `tools/<name>_server.py` using a template that wraps the code in proper MCP server boilerplate
3. Adds an entry to `data/mcp_servers.json`
4. Calls `MCPManager.reload()` to hot-reload all connections
5. Returns a summary of newly available tools

### `list_skills()`

Returns all connected MCP servers and their discovered tools. Helps ARC understand its current capabilities before creating new ones.

### `remove_skill(name)`

Removes a server from `mcp_servers.json`, deletes the generated file, and triggers a reload. Only removes ARC-generated skills (files with the `# ARC-generated` marker).

## MCPManager Changes

Add `async reload()` method:
```python
async def reload(self) -> None:
    await self.shutdown()
    self.__init__()       # reset state
    await self.connect_all()
```

## Template

Generated MCP servers follow this structure:

```python
#!/usr/bin/env python3
# ARC-generated skill server: {name}
# {description}

{user_code}

# --- MCP server boilerplate ---
from mcp.server import Server
from mcp.server.stdio import stdio_server
import asyncio

server = Server("{name}")

# Tool registration and call_tool handler generated from user code

async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

## Safety Considerations

- Generated files are restricted to the `tools/` directory
- Each skill runs as a separate subprocess (MCP process isolation)
- Skill names are validated (alphanumeric + underscores only)
- ARC-generated files are clearly marked with a comment header
- `remove_skill` only deletes files with the ARC-generated marker
- No built-in tools can be overridden (name conflict check)

## Files Changed

- **Create:** Nothing new — all changes are in existing modules
- **Modify:** `src/arc/tools.py` — add three new tools + schemas
- **Modify:** `src/arc/mcp_client.py` — add `reload()` method and `get_server_info()`
- **Modify:** `data/soul.md` — document new self-authoring capabilities
