# MCP Skill Server Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add MCP (Model Context Protocol) client support so ARC can discover and invoke external tool servers at startup, extending its skill set beyond built-in tools.

**Architecture:** A new `mcp_client.py` module manages stdio-based MCP server connections. At startup it reads `data/mcp_servers.json`, launches each server as a subprocess, discovers tools via `session.list_tools()`, and converts schemas to Ollama format. The existing `tools.py` dispatcher is extended to fall back to MCP when a tool name isn't in the built-in registry.

**Tech Stack:** `mcp[cli]` (official MCP Python SDK), stdio transport, JSON config file.

---

### Task 1: Add MCP dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Add the dependency**

Add `mcp[cli]>=1.0.0` to `requirements.txt` after the `aiosqlite` line:

```
mcp[cli]>=1.0.0
```

**Step 2: Install it**

Run: `cd /Users/jeremy/Documents/current_projects/my_agent_arc && pip install 'mcp[cli]>=1.0.0'`
Expected: Successfully installed mcp and dependencies

**Step 3: Commit**

```bash
git add requirements.txt
git commit -m "feat: add mcp[cli] dependency for MCP server support"
```

---

### Task 2: Create default MCP servers config file

**Files:**
- Create: `data/mcp_servers.json`

**Step 1: Create the config file**

```json
{
  "servers": {}
}
```

This is the empty default — users add servers here.

**Step 2: Commit**

```bash
git add data/mcp_servers.json
git commit -m "feat: add empty mcp_servers.json config"
```

---

### Task 3: Build `mcp_client.py` — MCPManager core

**Files:**
- Create: `src/arc/mcp_client.py`

**Step 1: Write the MCPManager class**

The module must:

1. Define `MCPManager` class with these attributes:
   - `_servers: dict[str, _ServerConnection]` — maps server name to connection state
   - `_tool_map: dict[str, str]` — maps tool name → server name for dispatch

2. Define `_ServerConnection` dataclass holding:
   - `name: str`
   - `session: ClientSession`
   - `read: MemoryObjectReceiveStream`
   - `write: MemoryObjectSendStream`
   - `tools: list[dict]` — Ollama-format schemas

3. Implement `async connect_all()`:
   - Read `data/mcp_servers.json` from `PROJECT_ROOT / "data" / "mcp_servers.json"`
   - For each server entry, call `stdio_client(StdioServerParameters(command=..., args=..., env=...))` 
   - Create a `ClientSession`, call `session.initialize()`, then `session.list_tools()`
   - Convert each MCP tool schema to Ollama format (see conversion logic below)
   - Register tool name → server name in `_tool_map`
   - Wrap each server connection in try/except — log warning on failure, skip that server

4. Implement `get_tool_schemas() -> list[dict]`:
   - Return all MCP tool schemas in Ollama format

5. Implement `async call_tool(name: str, arguments: dict) -> str`:
   - Look up server name from `_tool_map[name]`
   - Call `session.call_tool(name, arguments)`
   - Return the text content from the result
   - On error, return error string

6. Implement `async shutdown()`:
   - Close all sessions and cleanup

**MCP → Ollama schema conversion:**

MCP format:
```python
{
    "name": "web_search",
    "description": "Search the web",
    "inputSchema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"]
    }
}
```

Ollama format:
```python
{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]
        }
    }
}
```

The conversion is: wrap in `{"type": "function", "function": {...}}` and rename `inputSchema` → `parameters`.

**Key imports:**
```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
```

**Important implementation detail:** The `stdio_client` is an async context manager that must stay open for the lifetime of the server connection. Use `contextlib.AsyncExitStack` to manage multiple server lifetimes.

```python
import contextlib

class MCPManager:
    def __init__(self):
        self._exit_stack = contextlib.AsyncExitStack()
        self._servers: dict[str, _ServerConnection] = {}
        self._tool_map: dict[str, str] = {}
```

For each server:
```python
read, write = await self._exit_stack.enter_async_context(
    stdio_client(StdioServerParameters(command=cmd, args=args, env=env))
)
session = await self._exit_stack.enter_async_context(ClientSession(read, write))
await session.initialize()
tools_result = await session.list_tools()
```

Shutdown is just:
```python
await self._exit_stack.aclose()
```

**Step 2: Commit**

```bash
git add src/arc/mcp_client.py
git commit -m "feat: add MCPManager for MCP server connections"
```

---

### Task 4: Integrate MCPManager into tools.py

**Files:**
- Modify: `src/arc/tools.py` — `get_tool_schemas()` and `execute_tool()`

**Step 1: Update `get_tool_schemas()`**

After the built-in `_TOOL_SCHEMAS`, append MCP schemas:

```python
def get_tool_schemas() -> list[dict[str, Any]]:
    """Return Ollama-compatible tool schemas for injection into chat calls."""
    from arc.mcp_client import get_mcp_manager
    schemas = list(_TOOL_SCHEMAS)
    manager = get_mcp_manager()
    if manager is not None:
        mcp_schemas = manager.get_tool_schemas()
        # Only add MCP tools whose names don't conflict with built-in tools
        builtin_names = {s["function"]["name"] for s in _TOOL_SCHEMAS}
        for schema in mcp_schemas:
            if schema["function"]["name"] not in builtin_names:
                schemas.append(schema)
    return schemas
```

**Step 2: Update `execute_tool()` fallback**

In the `execute_tool` function, after checking `TOOL_REGISTRY`, fall back to MCP:

```python
handler = TOOL_REGISTRY.get(tool_name)

if handler is None:
    # Try MCP servers
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
```

**Step 3: Commit**

```bash
git add src/arc/tools.py
git commit -m "feat: integrate MCP tools into tool schemas and dispatcher"
```

---

### Task 5: Wire MCPManager into main.py lifecycle

**Files:**
- Modify: `src/arc/main.py`

**Step 1: Add startup call**

After `await init_db()`, add:

```python
from arc.mcp_client import get_mcp_manager, init_mcp_manager

# -- MCP servers -------------------------------------------------------
mcp_manager = await init_mcp_manager()
if mcp_manager:
    logger.info("MCP: %d servers connected", mcp_manager.server_count)
```

**Step 2: Add shutdown call**

In the `finally` block, before scheduler shutdown:

```python
if mcp_manager:
    await mcp_manager.shutdown()
    logger.info("MCP servers stopped")
```

**Step 3: Commit**

```bash
git add src/arc/main.py
git commit -m "feat: wire MCP manager startup and shutdown into main.py"
```

---

### Task 6: Add MCP status to admin dashboard

**Files:**
- Modify: `src/arc/admin.py` — dashboard route
- Modify: `templates/dashboard.html`

**Step 1: Update dashboard route to pass MCP info**

In the `dashboard()` route function, add after DB stats:

```python
from arc.mcp_client import get_mcp_manager

mcp_info = []
manager = get_mcp_manager()
if manager is not None:
    for name, server in manager.servers.items():
        mcp_info.append({
            "name": name,
            "tool_count": len(server.tools),
            "tools": [t["function"]["name"] for t in server.tools],
        })
```

Pass `mcp_servers=mcp_info` to the template render call.

**Step 2: Update dashboard.html**

Add an MCP Servers card after the Actions card:

```html
{# ----- MCP Servers ----- #}
<div class="card">
  <h2>🔌 MCP Servers</h2>
  {% if mcp_servers %}
  <table>
    <thead>
      <tr>
        <th>Server</th>
        <th>Tools</th>
      </tr>
    </thead>
    <tbody>
      {% for server in mcp_servers %}
      <tr>
        <td><strong>{{ server.name }}</strong></td>
        <td>{{ server.tools | join(", ") }} ({{ server.tool_count }})</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p style="color: var(--muted);">No MCP servers configured. Edit <code>data/mcp_servers.json</code> to add servers.</p>
  {% endif %}
</div>
```

**Step 3: Commit**

```bash
git add src/arc/admin.py templates/dashboard.html
git commit -m "feat: show MCP server status on admin dashboard"
```

---

### Task 7: Test end-to-end with a real MCP server

**Step 1: Verify ARC starts cleanly with empty config**

Run: `cd /Users/jeremy/Documents/current_projects/my_agent_arc && python -m arc.main`
Expected: Starts without errors, logs "MCP: 0 servers connected" or similar

**Step 2: Kill the server**

**Step 3: Final commit with all changes**

```bash
git add -A
git commit -m "feat: complete MCP skill server integration"
git push origin main
```

---

## Notes

- The `mcp[cli]` SDK uses `anyio` under the hood which is compatible with asyncio.
- `stdio_client` launches subprocesses — ensure the commands (e.g., `npx`, `python`) are available in the system PATH.
- MCP servers using `npx` require Node.js to be installed.
- The `AsyncExitStack` pattern keeps server connections alive for the app lifetime without manual context manager nesting.
