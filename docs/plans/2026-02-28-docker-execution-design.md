# Docker Execution MCP Server — Design Document

**Date:** 2026-02-28
**Status:** Approved
**Approach:** Dedicated MCP Docker Server (Approach B)

---

## Overview

Give ARC the ability to spin up ephemeral Docker containers for sandboxed code execution. ARC can run Python, shell scripts, Node.js, or any command in any Docker image — containers live only for the duration of the task and are automatically torn down.

This is implemented as a new MCP tool server (`tools/docker_server.py`) registered in `data/mcp_servers.json`, consistent with ARC's existing tool ecosystem. No changes to `tools.py` or the core agentic loop are required.

---

## Architecture

```
ARC agentic loop
    ↓  tool call: run_python(code=..., packages=[...])
MCPManager routes to docker_server.py (MCP subprocess)
    ↓
docker_server.py uses docker Python SDK
    ↓
Ephemeral container: pull image → install packages → run code → capture output → rm container
    ↓
Returns: stdout + stderr + exit_code + runtime_ms
    ↓
MCPManager returns result string to ARC
```

---

## Tool Surface

Four tools exposed by the MCP server:

### `run_python`
Run Python code in an ephemeral `python:3.12-slim` container.

**Parameters:**
- `code: str` — Python source code to execute
- `packages: list[str]` (optional) — pip packages to install before running
- `timeout_seconds: int` (optional, default 60) — kill container after N seconds

**Returns:** Formatted block with stdout, stderr, exit code, runtime

---

### `run_shell`
Run a shell script in an ephemeral `ubuntu:24.04` container.

**Parameters:**
- `script: str` — Bash script to execute
- `packages: list[str]` (optional) — apt packages to install via `apt-get install`
- `timeout_seconds: int` (optional, default 60)

**Returns:** Formatted block with stdout, stderr, exit code, runtime

---

### `run_node`
Run JavaScript code in an ephemeral `node:22-slim` container.

**Parameters:**
- `code: str` — JavaScript source to execute
- `packages: list[str]` (optional) — npm packages to install before running
- `timeout_seconds: int` (optional, default 60)

**Returns:** Formatted block with stdout, stderr, exit code, runtime

---

### `run_in_image`
Run any command in any Docker image. Full flexibility for ARC to use any runtime.

**Parameters:**
- `image: str` — Docker image name (e.g. `"rust:1.82"`, `"golang:1.23"`)
- `command: list[str]` — Command and args to run (e.g. `["python3", "-c", "print('hi')"]`)
- `code: str` (optional) — If provided, written to `/tmp/script` and available in container
- `timeout_seconds: int` (optional, default 60)

**Returns:** Formatted block with stdout, stderr, exit code, runtime

---

## Container Execution Model

### Lifecycle

```
1. Write code/script to a named tempfile on host
2. docker run:
   - image: appropriate for the language
   - volumes: {tempfile → /tmp/script.* (read-only)}
   - network_mode: "host"         ← internet access allowed (moderate isolation)
   - mem_limit: "512m"
   - cpu_quota: 100_000           ← 1 CPU core equivalent
   - auto_remove: True            ← --rm (cleanup on exit)
   - detach: False                ← wait for completion
3. Capture stdout + stderr + exit code
4. Delete tempfile
5. Return structured result
```

### Package Installation

For `run_python` with `packages=["pandas"]`, a wrapper script is generated:
```python
import subprocess
subprocess.run(["pip", "install", "-q", "pandas"], check=True)

# ... original code below ...
```

For `run_shell`, packages are installed via `apt-get install -y` at script start.
For `run_node`, packages are installed via `npm install` before execution.

### Result Format

```
=== Container Execution Result ===
Exit code: 0
Runtime: 1243ms

--- stdout ---
Hello from Python!

--- stderr ---
(empty)
```

---

## Implementation Details

### Files Changed

| File | Change |
|------|--------|
| `tools/docker_server.py` | **New** — MCP server with 4 tools |
| `data/mcp_servers.json` | Add `"docker"` server entry |
| `requirements.txt` | Add `docker>=7.0.0` |

### docker_server.py Structure

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
import docker
import tempfile, os, time, asyncio

server = Server("docker-server")
client = docker.from_env()

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [run_python_tool, run_shell_tool, run_node_tool, run_in_image_tool]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    match name:
        case "run_python":  return [TextContent(type="text", text=_run_python(**arguments))]
        case "run_shell":   return [TextContent(type="text", text=_run_shell(**arguments))]
        case "run_node":    return [TextContent(type="text", text=_run_node(**arguments))]
        case "run_in_image": return [TextContent(type="text", text=_run_in_image(**arguments))]
        case _: raise ValueError(f"Unknown tool: {name}")

def _run_container(image, command, code=None, timeout=60):
    """Core execution logic used by all tool handlers."""
    ...
```

### mcp_servers.json Addition

```json
"docker": {
  "command": "python",
  "args": ["tools/docker_server.py"]
}
```

### Error Handling

| Error | Response |
|-------|----------|
| Docker daemon not running | Clear error message: "Docker daemon is not accessible. Is Docker running?" |
| Image not found | Attempt `docker pull`, surface pull error if fails |
| Timeout exceeded | Return partial stdout with: "⚠ Container killed after {N}s timeout" |
| OOM killed | Return stderr with: "⚠ Container killed: out of memory (limit: 512m)" |
| Code crashes (non-zero exit) | Return full stdout+stderr with exit code — not treated as a tool error |

---

## Security Posture

**Moderate isolation:**
- ✅ Internet access allowed (`network_mode="host"`)
- ✅ Resource limits: 512MB RAM, 1 CPU core
- ✅ Timeout enforced (default 60s, configurable per call)
- ✅ Container auto-removed on exit (`--rm`)
- ✅ No host filesystem access (only the temp script file, read-only)
- ✅ Runs as container's default user (not host root)
- ❌ No additional seccomp/AppArmor profiles (future hardening option)

---

## Dependencies

- `docker>=7.0.0` (Python Docker SDK)
- Docker daemon running on host (Docker Desktop or Docker Engine)

---

## Future Extensions (Out of Scope)

- **Approach C extension**: Update `write_skill` template to support Docker-backed skill authoring
- **Persistent volumes**: Named volumes for stateful tasks (e.g. installing large ML models once)
- **Strict isolation mode**: `--network=none` flag as a per-call option
- **Custom Dockerfiles**: ARC builds and caches a custom image for a task
