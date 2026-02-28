# MCP Skill Server Integration — Design Document

## Problem

ARC's built-in tools (search_memory, save_to_memory, write_heartbeat) are hard-coded. To give ARC new skills — web search, file manipulation, code execution, API access — we need a plugin system. The Model Context Protocol (MCP) provides exactly this: a standardised way for LLM agents to discover and invoke external tool servers.

## Approach

Add an MCP client layer that connects to configured MCP servers at startup, discovers their tools, and merges those tools into ARC's existing tool pipeline. Built-in tools take priority; MCP tools extend the catalogue.

## Architecture

```
Startup (main.py)
    │
    ▼
MCPManager.connect_all()          ← reads data/mcp_servers.json
    ├── stdio_client(server_1)    ← subprocess, stdin/stdout
    ├── stdio_client(server_2)
    └── ...
    │
    ▼
Tool schemas merged into get_tool_schemas()
    │
    ▼
Agent Loop (agent.py)
    │  tool call "web_search"
    ▼
execute_tool()
    ├── TOOL_REGISTRY (built-in)  → local handler
    └── MCPManager.call_tool()    → MCP session.call_tool()
```

## New Components

### `src/arc/mcp_client.py` — MCPManager

A singleton class responsible for:

1. **Loading config** — reads `data/mcp_servers.json`
2. **Connecting** — launches each server as a subprocess using `mcp.client.stdio.stdio_client()`
3. **Tool discovery** — calls `session.list_tools()` on each connected server
4. **Schema conversion** — translates MCP tool schemas to Ollama function-calling format
5. **Tool dispatch** — `call_tool(name, arguments)` routes to the correct server session
6. **Lifecycle** — `connect_all()` at startup, `shutdown()` on teardown

### `data/mcp_servers.json` — Server Configuration

```json
{
  "servers": {
    "web-search": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-server-web-search"],
      "env": { "API_KEY": "..." }
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/docs"]
    }
  }
}
```

Fields per server:
- `command` (required): executable to run
- `args` (optional): command-line arguments
- `env` (optional): additional environment variables passed to the subprocess

## Integration Points

### tools.py

- `get_tool_schemas()` returns built-in schemas + MCP schemas (built-in first)
- `execute_tool()` checks `TOOL_REGISTRY` first; if tool name not found, delegates to `MCPManager.call_tool()`

### main.py

- After `init_db()`, call `await mcp_manager.connect_all()`
- On shutdown, call `await mcp_manager.shutdown()`

### admin.py

- New section on dashboard showing connected MCP servers and their discovered tools

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Transport | Stdio only | Simpler, no network config, covers 90% of MCP servers |
| Connection timing | On startup | Predictable, tools available immediately, no first-call latency |
| Name conflicts | Built-in wins | Prevents MCP servers from overriding core behaviour |
| Failed connections | Log warning, skip | One broken server shouldn't block the entire agent |
| Config format | JSON file | Standard, matches Claude Desktop convention, easy to edit |

## Dependencies

- `mcp[cli]` — official MCP Python SDK (adds `mcp`, `httpx`, `anyio`)

## Error Handling

- Server fails to start → log warning, mark server as disconnected, continue
- Tool call to disconnected server → return error string to LLM context
- MCP tool raises exception → catch, return error string to LLM context
- Config file missing → log info, start with no MCP servers (graceful degradation)
