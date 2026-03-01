# ARC User Guide

*The complete reference for installing, configuring, operating, and extending the Analytical Resonance Core agent framework.*

> **Repository:** <https://github.com/BitsofJeremy/my_agent_arc>

---

## Table of Contents

1. [What is ARC?](#1-what-is-arc)
2. [Quick Start](#2-quick-start)
3. [Configuration Reference](#3-configuration-reference)
4. [Connecting Telegram](#4-connecting-telegram)
5. [The Admin Dashboard](#5-the-admin-dashboard)
6. [How the Agentic Loop Works](#6-how-the-agentic-loop-works)
7. [Context Management & Compaction](#7-context-management--compaction)
8. [Memory & RAG](#8-memory--rag)
9. [Built-in Tools](#9-built-in-tools)
10. [MCP Skill Servers](#10-mcp-skill-servers)
11. [Self-Authoring Skills](#11-self-authoring-skills)
12. [Docker Code Execution](#12-docker-code-execution)
13. [Customising ARC's Personality](#13-customising-arcs-personality)
14. [Triggers & Scheduling](#14-triggers--scheduling)
15. [Deployment on Linux](#15-deployment-on-linux)
16. [Troubleshooting](#16-troubleshooting)

---

## 1. What is ARC?

ARC (Analytical Resonance Core) is a modular, self-contained autonomous AI agent framework that runs entirely on your own hardware. No API keys, no cloud dependencies, no data leaving your machine.

The system is organised into four architectural zones:

```
┌─────────────────────────────────────────────────────────────────┐
│                         TRIGGERS                                │
│  ┌────────────┐  ┌─────────────┐  ┌──────────┐  ┌───────────┐  │
│  │  Telegram   │  │  Heartbeat  │  │   Cron   │  │   Admin   │  │
│  │  Message    │  │  (APSched)  │  │   Jobs   │  │  Manual   │  │
│  └─────┬──────┘  └──────┬──────┘  └────┬─────┘  └─────┬─────┘  │
│        └────────┬───────┴──────────────┴───────────────┘        │
│                 ▼                                                │
│        ┌────────────────┐                                       │
│        │ handle_trigger │  (gateway.py — unified entry)         │
│        └───────┬────────┘                                       │
├────────────────┼────────────────────────────────────────────────┤
│                ▼          CONTEXT INJECTION                      │
│  ┌──────────────────────────────────────────────┐               │
│  │           Context Manager                     │               │
│  │  soul.md + identity.md + user.md              │               │
│  │  + compacted summaries + recent turns         │               │
│  │  + tool schemas  →  assembled prompt          │               │
│  └──────────────────────┬───────────────────────┘               │
├─────────────────────────┼───────────────────────────────────────┤
│                         ▼       AGENTIC LOOP                    │
│           ┌─────────────────────────┐                           │
│           │      Ollama LLM         │                           │
│           │  (tool-calling model)   │◄──────────┐               │
│           └────────────┬────────────┘           │               │
│                        │  tool call?            │ tool result   │
│                        ▼                        │               │
│           ┌─────────────────────────┐           │               │
│           │      Tool Dispatcher    │───────────┘               │
│           │  Built-in + MCP tools   │                           │
│           └─────────────────────────┘                           │
├─────────────────────────┬───────────────────────────────────────┤
│                         ▼       OUTPUTS / MEMORY                │
│  ┌──────────┐  ┌────────────┐  ┌──────────────┐                │
│  │ Telegram  │  │   SQLite   │  │   ChromaDB   │                │
│  │  Reply    │  │  Messages  │  │  Vector Mem  │                │
│  └──────────┘  └────────────┘  └──────────────┘                │
└─────────────────────────────────────────────────────────────────┘
```

**Zone 1 — Triggers** receive inbound events: Telegram messages from users, periodic heartbeat ticks from APScheduler, scheduled cron prompts, or manual triggers from the admin dashboard. All triggers funnel through a single `handle_trigger` function in `gateway.py`.

**Zone 2 — Context Injection** assembles the prompt. The context manager reads `soul.md` (personality), `identity.md` (character metadata), and `user.md` (user profile), appends any compacted conversation summaries, then attaches recent conversation history. The result is a complete message list ready for the LLM.

**Zone 3 — Agentic Loop** sends the assembled context to Ollama. If the model requests tool calls, the tool dispatcher executes them (built-in tools or MCP server tools) and feeds results back to the model. This loop repeats until the model produces a final text answer or the iteration cap is reached.

**Zone 4 — Outputs / Memory** delivers the response. The reply goes back to the originating channel (Telegram or admin chat). Every message is logged to SQLite. Important facts and compaction summaries are persisted to ChromaDB for long-term vector memory.

---

## 2. Quick Start

### Prerequisites

- **Python 3.11+** — [python.org/downloads](https://www.python.org/downloads/)
- **Ollama** — [ollama.com/download](https://ollama.com/download)
- **Git** — to clone the repository
- **Docker Desktop** (macOS/Windows) or **Docker Engine** (Linux) — if you want code execution via the Docker tools (see [Section 12](#12-docker-code-execution))

### Step 1: Clone the repository

```bash
git clone https://github.com/BitsofJeremy/my_agent_arc.git
cd my_agent_arc
```

### Step 2: Pull the LLM models

```bash
ollama pull minimax-m2.5          # recommended chat model
ollama pull nomic-embed-text      # embedding model for memory
```

The recommended chat model is [minimax-m2.5](https://ollama.com/library/minimax-m2.5) for its strong tool-calling support and reasoning quality. Any Ollama model with function-calling support will work — set `ARC_OLLAMA_MODEL` in `.env` to use a different one.

### Step 3: Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Alternatively, install in editable mode (useful if you plan to modify ARC):

```bash
pip install -e .
```

### Step 4: Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
ARC_OLLAMA_MODEL=minimax-m2.5       # or your preferred model
ARC_TELEGRAM_BOT_TOKEN=your-token   # optional — admin chat works without it
```

### Step 5: Run ARC

```bash
python -m arc.main
```

ARC starts three subsystems concurrently:

| Subsystem           | What it does                            |
| ------------------- | --------------------------------------- |
| **Admin Dashboard** | Web UI at `http://localhost:8080`       |
| **Telegram Bot**    | Listens for messages (if token is set)  |
| **Heartbeat**       | Periodic autonomous trigger             |

Open `http://localhost:8080/chat` to talk to ARC immediately — no Telegram required.

---

## 3. Configuration Reference

All settings use the `ARC_` prefix and are loaded from `.env` or environment variables. The configuration is managed by `src/arc/config.py` using a frozen dataclass.

| Variable | Default | Description |
| --- | --- | --- |
| `ARC_TELEGRAM_BOT_TOKEN` | *(empty — bot disabled)* | Telegram Bot API token from [@BotFather](https://t.me/BotFather). Leave empty to run without Telegram. |
| `ARC_OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL. Change this if Ollama runs on a different host or port. |
| `ARC_OLLAMA_MODEL` | `minimax-m2.5` | Chat model for the agentic loop. Must support function/tool calling. Recommended: [minimax-m2.5](https://ollama.com/library/minimax-m2.5). |
| `ARC_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model for ChromaDB vector memory. Used by the `search_memory` and `save_to_memory` tools. |
| `ARC_SQLITE_DB_PATH` | `data/arc.db` | SQLite database file path (relative to project root or absolute). |
| `ARC_CHROMADB_PATH` | `data/chromadb` | ChromaDB persistent storage directory (relative to project root or absolute). |
| `ARC_CONTEXT_WINDOW_TOKENS` | `8192` | Maximum token budget for the assembled context window sent to Ollama. |
| `ARC_COMPACTION_THRESHOLD` | `0.5` | Fraction of the context window that triggers compaction. At `0.5`, compaction fires when non-compacted messages exceed 4096 tokens (half of 8192). |
| `ARC_HEARTBEAT_INTERVAL_MINUTES` | `15` | Minutes between autonomous heartbeat triggers. The heartbeat reads `heartbeat.md` and, if it contains actionable instructions, sends them to the agent. |
| `ARC_ADMIN_HOST` | `0.0.0.0` | Admin dashboard bind address. Use `127.0.0.1` to restrict to localhost. |
| `ARC_ADMIN_PORT` | `8080` | Admin dashboard port number. |
| `ARC_SOUL_PATH` | `data/soul.md` | Path to the system prompt file that defines ARC's personality. |
| `ARC_HEARTBEAT_PATH` | `data/heartbeat.md` | Path to the heartbeat instruction file. ARC can rewrite this itself via the `write_heartbeat` tool. |
| `ARC_MAX_AGENT_ITERATIONS` | `10` | Maximum number of LLM↔tool call loops before the agent stops and returns a fallback message. Prevents runaway tool-calling chains. |

### Path resolution

Relative paths (like the defaults `data/arc.db`, `data/chromadb`) are resolved against the project root directory. Absolute paths are used as-is.

### Example `.env` file

```bash
# Telegram (optional)
ARC_TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ

# Ollama
ARC_OLLAMA_HOST=http://localhost:11434
ARC_OLLAMA_MODEL=minimax-m2.5
ARC_OLLAMA_EMBED_MODEL=nomic-embed-text

# Context
ARC_CONTEXT_WINDOW_TOKENS=8192
ARC_COMPACTION_THRESHOLD=0.5

# Heartbeat
ARC_HEARTBEAT_INTERVAL_MINUTES=15

# Admin
ARC_ADMIN_HOST=0.0.0.0
ARC_ADMIN_PORT=8080

# Agent
ARC_MAX_AGENT_ITERATIONS=10
```

---

## 4. Connecting Telegram

Telegram is optional. ARC runs fine without it — use the admin chat at `http://localhost:8080/chat` instead. If you want Telegram integration, follow these steps.

### Step 1: Create a bot with BotFather

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a display name (e.g. "ARC Agent")
4. Choose a username ending in `bot` (e.g. `arc_agent_bot`)
5. BotFather replies with a token like `123456789:ABCdefGHIjklMNO...`

### Step 2: Set the token

Add it to your `.env` file:

```bash
ARC_TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNO...
```

### Step 3: Restart ARC

```bash
# If running directly:
python -m arc.main

# If running as a systemd service:
sudo systemctl restart arc
```

ARC will start polling for Telegram messages. Send any message to your bot and ARC will respond.

### Privacy notes

- ARC uses **long-polling** (not webhooks), so no public URL or port forwarding is required.
- All messages are processed locally on your machine.
- Each Telegram chat gets its own `session_id` (the chat ID), so conversations are isolated.

---

## 5. The Admin Dashboard

The built-in web UI runs at **http://localhost:8080** (configurable via `ARC_ADMIN_HOST` and `ARC_ADMIN_PORT`). It is built with FastAPI, Jinja2 templates, and Server-Sent Events for live streaming.

### Dashboard (`/`)

The landing page shows:

- **Database statistics** — SQLite file size, total message count, number of compacted nodes
- **MCP server status** — connected MCP skill servers and their available tools
- **Recent messages** — the last 20 messages from all sessions

The dashboard also provides manual trigger buttons:

| Button | Action |
| --- | --- |
| **Fire Heartbeat** | Manually triggers a heartbeat cycle (reads `heartbeat.md` and sends it to the agent) |
| **Fire Cron** | Sends a custom text prompt through the agent as a cron-style trigger |
| **Run Compaction** | Manually triggers a context compaction check (still respects the threshold — skips if not exceeded) |

### Chat (`/chat`)

A web-based chat interface for talking to ARC directly. Messages sent here use the session ID `admin-chat`, separate from Telegram sessions. Conversation history is displayed on the page and persisted to SQLite.

### Logs (`/logs`)

A live log viewer using Server-Sent Events (SSE). Streams all `arc.*` logger output in real time. The log stream connects to `/api/logs/stream` and displays formatted log lines as they arrive. Useful for debugging tool calls, compaction events, and MCP server issues.

### Soul Editor (`/editor/soul`)

An in-browser text editor for `data/soul.md`. Changes are saved directly to disk and take effect on the next message — no restart required. This is ARC's core personality document.

### Heartbeat Editor (`/editor/heartbeat`)

An in-browser text editor for `data/heartbeat.md`. Edit the heartbeat instructions that ARC reads on each heartbeat cycle. ARC can also edit this file itself via the `write_heartbeat` tool.

---

## 6. How the Agentic Loop Works

The agentic loop is the core of ARC. It lives in `src/arc/agent.py` and orchestrates multi-turn conversations with tool use. Here is the step-by-step flow:

### 1. Log the incoming message

The user's message is persisted to the `messages` table in SQLite with role `"user"`, a token estimate, and the session ID.

### 2. Compact if needed

The context manager checks whether non-compacted messages exceed the token budget threshold (default: 50% of 8192 = 4096 tokens). If so, compaction runs before building context. See [Section 7](#7-context-management--compaction) for details.

### 3. Build the prompt context

The context manager assembles a list of messages for Ollama:

1. **System message** — `soul.md` + `identity.md` + `user.md` + any compacted conversation summaries
2. **Recent history** — the most recent non-compacted messages in chronological order (up to 50)

### 4. Call Ollama

The assembled messages and tool schemas are sent to Ollama's `chat` API. The call runs on a background thread via `asyncio.to_thread` to avoid blocking the event loop.

### 5. Check the response

**If the model requested tool calls** — the assistant's message (containing `tool_calls`) is appended to the conversation. Each tool call is executed via the tool dispatcher, and the results are appended as `"tool"` role messages. All tool calls and results are logged to SQLite. The loop continues back to step 4.

**If the model produced a final text answer** — the response content is logged as an `"assistant"` message and returned to the caller.

### 6. Iteration guard

If the loop runs for `ARC_MAX_AGENT_ITERATIONS` iterations (default: 10) without producing a final answer, ARC returns a fallback message:

> *"I've been thinking about this for a while and need to stop here. Could you rephrase or simplify your request?"*

### Error handling

- **Ollama unreachable or model error** — returns `"I'm having trouble thinking right now. Please try again."`
- **Malformed tool arguments** — logs the error and feeds it back to the model as a tool result so the model can recover
- **Unknown tool name** — returns an error listing available tools so the model can self-correct
- **Tool execution exception** — caught and returned as an error string to the model

### Visual flow

```
User message
    │
    ▼
┌─ Log to SQLite ──────────────────────┐
│                                       │
├─ Maybe compact (if over threshold) ──┤
│                                       │
├─ Build context ──────────────────────┤
│  (soul + identity + user +            │
│   compacted summaries + history)      │
│                                       │
├─ Call Ollama ◄───────────────────────┤
│    │                                  │
│    ├─ Tool calls? ── Yes ──┐         │
│    │                       │         │
│    │    Execute tools       │         │
│    │    Log results         │         │
│    │    Append to context ──┘         │
│    │                                  │
│    └─ Final text? ── Yes ──┐         │
│                            │         │
│         Log response        │         │
│         Return to caller ───┘         │
└───────────────────────────────────────┘
```

---

## 7. Context Management & Compaction

ARC manages conversation history within a fixed token budget to ensure the context window sent to Ollama never exceeds the model's capacity. This is handled by `src/arc/context_manager.py`.

### Token estimation

ARC uses a fast heuristic: **1 token ≈ 4 characters**. The estimate is calculated as `len(text) // 4`. This avoids pulling in a tokeniser library while being accurate enough for budget tracking.

Every message logged to SQLite includes a `token_estimate` column computed at insert time.

### When compaction fires

Compaction is checked before every agentic loop run. It triggers when:

```
total_tokens_of_non_compacted_messages  >  context_window_tokens × compaction_threshold
```

With the defaults (`context_window_tokens=8192`, `compaction_threshold=0.5`), compaction fires when non-compacted messages exceed **4096 estimated tokens**.

### What happens during compaction

1. **Fetch all non-compacted messages** for the session, ordered chronologically.
2. **Split at the midpoint** — the older half is selected for compaction.
3. **Format as conversation text** — each message becomes `"role: content"` on its own line.
4. **Summarise via Ollama** — the conversation text is sent to the configured chat model with the prompt: *"Summarize this conversation concisely, preserving key facts and decisions."*
5. **Store the compacted node** — the summary, original message IDs, and a token estimate are inserted into the `compacted_nodes` table.
6. **Mark originals** — the compacted messages are flagged (`is_compacted = 1`) so they no longer appear in the active context window.
7. **Persist to ChromaDB** — the summary is also saved to long-term vector memory with `{"type": "compaction"}` metadata, so it can be found via RAG search.

### How context is built

When `build_context` assembles the prompt, it:

1. Reads `soul.md` (the personality/system prompt)
2. Reads `identity.md` and `user.md` from the same directory as `soul.md`
3. Fetches all compacted summaries from `compacted_nodes` (chronological order) and appends them under a `## Previous Conversation Context` heading
4. Fetches the most recent non-compacted messages (up to 50, chronological order)

The result is a complete `messages` list that Ollama receives:

```
[system]  soul.md + identity.md + user.md + compacted summaries
[user]    older surviving message
[assistant] ...
[user]    most recent message
```

---

## 8. Memory & RAG

ARC has a long-term vector memory system built on ChromaDB with Ollama embeddings. This is separate from the SQLite conversation history — it stores discrete facts and knowledge that persist indefinitely.

### How it works

- **Collection name:** `agent_memory`
- **Embedding model:** configured by `ARC_OLLAMA_EMBED_MODEL` (default: `nomic-embed-text`)
- **Storage:** persistent on disk at `ARC_CHROMADB_PATH` (default: `data/chromadb`)

When a fact is saved, it is:
1. Embedded into a vector using the Ollama `embeddings` endpoint
2. Stored in ChromaDB with a UUID, the text, a timestamp, and optional metadata

When a query is searched, it is:
1. Embedded into a vector
2. Compared against all stored vectors using ChromaDB's similarity search
3. The top N results (default: 5) are returned with their content, metadata, and distance scores

### Agent integration

ARC has two built-in tools that expose this memory to the LLM:

- **`search_memory(query)`** — searches ChromaDB and returns formatted results
- **`save_to_memory(fact)`** — persists a fact with a timestamp

ARC's personality prompt (`soul.md`) instructs the agent to use these tools proactively:
- Before claiming ignorance, search memory first
- When learning something important, save it
- Compaction summaries are automatically saved to memory

### What goes into memory

- Facts the agent explicitly saves via `save_to_memory`
- Compaction summaries (saved automatically with `{"type": "compaction"}` metadata)
- Anything the user asks ARC to remember

---

## 9. Built-in Tools

ARC ships with six built-in tools. Their schemas are defined in `src/arc/tools.py` in Ollama's function-calling format, and the implementations are async Python functions.

### `search_memory(query)`

Search the agent's long-term memory (ChromaDB) for relevant context.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `query` | string | Yes | Natural-language search query |

**Returns:** A formatted list of matching memories, or `"No relevant memories found."` if nothing matches.

**Example usage:** The agent calls this before answering questions where prior context might help, or when the user asks "do you remember...?"

---

### `save_to_memory(fact)`

Persist an important fact or decision to long-term memory.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `fact` | string | Yes | The fact or decision to remember |

**Returns:** `"Saved to memory: <fact>"`

**Example usage:** The agent calls this when it learns something worth keeping across sessions — user preferences, project decisions, important dates.

---

### `write_heartbeat(instructions)`

Write instructions for the agent's next heartbeat cycle. This is how ARC programs its own future behaviour.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `instructions` | string | Yes | Instructions for the next heartbeat cycle |

**Returns:** `"Heartbeat instructions updated successfully."`

**How it works:** The tool reads `data/heartbeat.md`, finds the `## Current Instructions` section, and replaces everything in that section with the new instructions. If the section doesn't exist, it's appended.

**Example usage:** The agent might write: *"Check in with Jeremy about the deployment status. Review the project backlog for any overdue items."* On the next heartbeat (every 15 minutes by default), ARC reads these instructions and acts on them.

---

### `write_skill(name, description, code)`

Create a new MCP tool server. This is how ARC extends its own capabilities at runtime.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | Yes | Skill name (alphanumeric and underscores only, e.g. `weather`) |
| `description` | string | Yes | Brief description of what the skill does |
| `code` | string | Yes | Python code defining MCP tools. Must include `@server.list_tools()` and `@server.call_tool()` decorated functions. |

**Returns:** On success: `"Skill '<name>' created and loaded successfully. Available tools: <list>"`. On failure or if restart is needed: `"Skill '<name>' created. Restart ARC to activate it."`

**How it works:**
1. Validates the skill name (must start with a letter, alphanumeric + underscores only)
2. Checks for conflicts with built-in tool names
3. Generates a complete Python MCP server file at `tools/<name>_server.py` using a template that wraps the provided code with server boilerplate
4. Adds the server entry to `data/mcp_servers.json`
5. Hot-reloads the MCP manager so the new tools are available immediately

The generated file includes the marker `# ARC-generated skill server` — this is a safety marker that prevents `remove_skill` from deleting files that weren't generated by ARC.

---

### `list_skills()`

List all connected MCP skill servers and their available tools.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| *(none)* | — | — | — |

**Returns:** A formatted list of connected servers with their tool names and counts, or `"No MCP skill servers connected."`.

---

### `remove_skill(name)`

Remove an ARC-generated skill server and its tools.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | Yes | Name of the skill server to remove |

**Returns:** `"Skill '<name>' removed successfully."` on success.

**Safety:** Only files containing the `# ARC-generated skill server` marker can be deleted. Manually created MCP servers are protected.

**How it works:**
1. Validates the name
2. Reads the server file and checks for the ARC-generated marker
3. Deletes the file from `tools/`
4. Removes the entry from `data/mcp_servers.json`
5. Hot-reloads the MCP manager

### Tool dispatch priority

When the agent calls a tool, the dispatcher in `src/arc/tools.py` follows this order:

1. Check the built-in tool registry first
2. If not found, check connected MCP servers
3. If still not found, return an error listing available tools

**Built-in tools always win.** If an MCP server defines a tool with the same name as a built-in tool, the built-in version takes priority. This prevents MCP servers from overriding core behaviour.

The dispatcher also filters tool arguments to only those the handler function actually accepts, so hallucinated extra parameters from the LLM don't crash the call.

---

## 10. MCP Skill Servers

ARC supports the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) for extending its capabilities with external tool servers. MCP servers run as subprocesses and communicate over stdio.

### How it works

1. At startup, ARC reads `data/mcp_servers.json`
2. Each configured server is launched as a subprocess via `StdioServerParameters`
3. ARC initialises a `ClientSession` with each server and discovers available tools
4. Tool schemas are converted to Ollama's function-calling format and merged into the tool catalogue
5. When the LLM calls an MCP tool, ARC routes the call to the correct server's session
6. The server's response text is extracted and returned to the agent

All MCP connections are managed by the `MCPManager` class in `src/arc/mcp_client.py`.

### Configuration format

Edit `data/mcp_servers.json`:

```json
{
  "servers": {
    "server-name": {
      "command": "python",
      "args": ["tools/my_server.py"],
      "env": {
        "OPTIONAL_VAR": "value"
      }
    }
  }
}
```

Each server entry supports:

| Field | Required | Description |
| --- | --- | --- |
| `command` | Yes | Executable to run (`python`, `npx`, `node`, etc.) |
| `args` | No | Command-line arguments (list of strings) |
| `env` | No | Additional environment variables (key-value object) |

### Examples

**Python MCP server (local script):**

```json
{
  "servers": {
    "test": {
      "command": "python",
      "args": ["tools/test_server.py"]
    }
  }
}
```

**npx-based MCP server (Node.js):**

```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/documents"]
    }
  }
}
```

**Server with environment variables:**

```json
{
  "servers": {
    "web-search": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-server-web-search"],
      "env": {
        "API_KEY": "your-api-key"
      }
    }
  }
}
```

After editing `mcp_servers.json`, restart ARC. Connected servers and their tools appear on the admin dashboard.

### Built-in test server

ARC ships with a test MCP server at `tools/test_server.py` that provides two tools:

- **`ping`** — returns `"pong"` with a UTC timestamp (no parameters)
- **`echo`** — echoes back a provided message

It is pre-configured in `data/mcp_servers.json` and serves as both a connectivity test and a reference implementation.

### Writing your own MCP server

Create a Python file in `tools/` using the MCP SDK. Here is the pattern from `tools/test_server.py`:

```python
#!/usr/bin/env python3
"""My custom MCP tool server."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("my-server")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="my_tool",
            description="Does something useful",
            inputSchema={
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "The input to process",
                    },
                },
                "required": ["input"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "my_tool":
        result = f"Processed: {arguments.get('input', '')}"
        return [TextContent(type="text", text=result)]
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

Add it to `data/mcp_servers.json` and restart ARC:

```json
{
  "servers": {
    "my-server": {
      "command": "python",
      "args": ["tools/my_server.py"]
    }
  }
}
```

### Finding community MCP servers

Browse the [MCP Server Directory](https://github.com/modelcontextprotocol/servers) for community-built servers. Most can be added with a single `npx` command (requires Node.js).

### Error handling

If an MCP server fails to connect at startup, ARC logs the error and skips that server — other servers and built-in tools continue working. If a tool call to an MCP server fails at runtime, the error is caught and returned to the model as a tool result string.

---

## 11. Self-Authoring Skills

ARC can write its own tools at runtime using the `write_skill` tool. This is one of ARC's most powerful capabilities — it can extend its own mind without human intervention.

### How it works

When ARC calls `write_skill(name, description, code)`:

1. **Validation** — the name is checked (must be alphanumeric + underscores, no conflicts with built-in tools)
2. **File generation** — a complete MCP server Python file is generated at `tools/<name>_server.py` using a template that adds the server boilerplate, imports, and `asyncio.run(main())` entry point around the provided code
3. **Config update** — `data/mcp_servers.json` is updated to include the new server
4. **Hot-reload** — the MCP manager is reloaded, connecting to the new server and discovering its tools immediately
5. **Confirmation** — ARC receives confirmation with the list of available tools from the new server

### Safety markers

Every ARC-generated file includes the comment `# ARC-generated skill server: <name>` at the top. This marker serves two purposes:

- `remove_skill` will only delete files containing this marker, protecting manually-created servers
- It makes it easy to identify which servers were auto-generated

### Example conversation

Here is what it looks like when ARC creates a skill:

> **User:** I need you to be able to tell me the current time in different timezones.
>
> **ARC:** I shall create a timezone tool for myself. One moment.
>
> *[ARC calls `write_skill` with name="timezone", description="Get current time in any timezone", and the Python code defining a `get_time` tool]*
>
> **ARC:** Done. I now have a `get_time` tool available. Shall I demonstrate? What timezone would you like?

### Generated file structure

The generated file at `tools/<name>_server.py` looks like:

```python
#!/usr/bin/env python3
# ARC-generated skill server: timezone
# Get current time in any timezone

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
import asyncio

server = Server("timezone")

# ... the code ARC provided ...

async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

### Removing self-authored skills

ARC can remove its own skills via `remove_skill(name)`. This deletes the server file (only if it has the ARC-generated marker), removes the entry from `mcp_servers.json`, and hot-reloads the MCP manager.

---

## 12. Docker Code Execution

ARC ships with a dedicated MCP server — `tools/docker_server.py` — that runs code inside ephemeral Docker containers. Each invocation spins up a fresh container, executes the code, returns the output, and removes the container. Nothing persists between calls. No interpreter state, no leftover files, no side effects on the host.

This makes it practical to run untrusted or experimental code, install dependencies freely, and benchmark or test snippets in a clean environment without any risk to the host machine.

### Prerequisites

- **Docker Desktop** (macOS or Windows) — [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)
- **Docker Engine** (Linux) — [docs.docker.com/engine/install](https://docs.docker.com/engine/install/)
- The `docker` Python package — already present in `requirements.txt` (`docker>=7.0.0`), installed automatically with `pip install -r requirements.txt`

Docker must be running before ARC starts. The docker server will fail to connect to the Docker daemon at startup otherwise.

### Configuration

Add the `docker` server entry to `data/mcp_servers.json`:

**macOS (Docker Desktop):**

```json
{
  "servers": {
    "docker": {
      "command": "python",
      "args": ["tools/docker_server.py"],
      "env": {
        "DOCKER_HOST": "unix:///Users/jeremy/.docker/run/docker.sock"
      }
    }
  }
}
```

Docker Desktop on macOS places the Unix socket at a user-specific path rather than the system default `/var/run/docker.sock`. The `DOCKER_HOST` environment variable tells the `docker` Python library where to find it. Replace the path with your own username if it differs.

**Linux (Docker Engine):**

```json
{
  "servers": {
    "docker": {
      "command": "python",
      "args": ["tools/docker_server.py"]
    }
  }
}
```

Standard Docker Engine installations on Linux use `/var/run/docker.sock`, which the library finds automatically. No `env` block is needed. If your installation uses a non-standard socket path, add a `DOCKER_HOST` entry as above.

After updating `mcp_servers.json`, restart ARC. The docker server and its four tools will appear on the admin dashboard.

### The four tools

#### `run_python`

Runs Python code in an isolated `python:3.12-slim` container.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `code` | string | Yes | — | Python source code to execute |
| `packages` | list of strings | No | `[]` | Packages to install via `pip` before running |
| `timeout_seconds` | integer | No | `60` | Maximum execution time before the container is killed |

#### `run_shell`

Runs a Bash script in an `ubuntu:24.04` container.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `script` | string | Yes | — | Bash script to execute |
| `packages` | list of strings | No | `[]` | Packages to install via `apt` before running |
| `timeout_seconds` | integer | No | `60` | Maximum execution time before the container is killed |

#### `run_node`

Runs JavaScript in a `node:22-slim` container.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `code` | string | Yes | — | JavaScript source code to execute |
| `packages` | list of strings | No | `[]` | Packages to install via `npm` before running |
| `timeout_seconds` | integer | No | `60` | Maximum execution time before the container is killed |

#### `run_in_image`

Runs an arbitrary command in any Docker image. Use this when none of the specialised tools fit.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `image` | string | Yes | — | Docker image name (e.g. `alpine:3.19`, `rust:1.78-slim`) |
| `command` | list of strings | Yes | — | Command and arguments to execute (e.g. `["python3", "/tmp/script"]`) |
| `code` | string | No | — | Optional source code or script content — written to `/tmp/script` inside the container before the command runs |
| `timeout_seconds` | integer | No | `60` | Maximum execution time before the container is killed |

### Result format

All four tools return output in the same structured format:

```
=== Container Execution Result ===
Exit code: 0
Runtime: 214ms

--- stdout ---
Hello from Python!

--- stderr ---
(empty)
```

ARC receives this as a single text block and uses it to formulate its response. A non-zero exit code, stderr output, or a timeout are all surfaced in this format for the model to interpret.

### Container resource limits

Every container is started with the following constraints:

| Resource | Limit |
| --- | --- |
| RAM | 512 MB |
| CPU | 1 core |
| PIDs | 128 |
| Network | Internet access enabled |

These defaults prevent a single code execution from starving the host. Internet access is intentionally left open — if ARC needs to install packages or fetch data during execution, it can.

### Container lifecycle and cleanup

Containers are labelled `arc.managed=true` at creation. Three layers of cleanup ensure no orphaned containers accumulate:

1. **Per-execution cleanup** — every container is removed in a `finally` block immediately after execution completes, whether it succeeded, failed, or timed out.
2. **Startup cleanup** — when `docker_server.py` initialises, it queries Docker for all containers with the `arc.managed=true` label and removes any that are already stopped. This recovers from crashes that prevented the `finally` block from running.
3. **Background sweep** — a coroutine runs every five minutes, repeating the same stale-container sweep in case any containers leaked during normal operation.

### Image caching

Docker images are not bundled with ARC. On the first call to a given tool, Docker pulls the required image from Docker Hub (`python:3.12-slim`, `ubuntu:24.04`, `node:22-slim`). This pull can take 30–60 seconds depending on network speed and image size. Subsequent calls use the locally cached image and start immediately.

If you are on a slow connection or want to pre-cache images before first use:

```bash
docker pull python:3.12-slim
docker pull ubuntu:24.04
docker pull node:22-slim
```

### Example usage

When asked "calculate the sum of the first 1000 primes", ARC calls `run_python` rather than attempting to estimate the answer:

```
ARC calls: run_python(code="""
def sieve(n):
    is_prime = [True] * (n + 1)
    is_prime[0] = is_prime[1] = False
    for i in range(2, int(n**0.5) + 1):
        if is_prime[i]:
            for j in range(i*i, n+1, i):
                is_prime[j] = False
    return [i for i in range(2, n+1) if is_prime[i]]

primes = sieve(8000)[:1000]
print(f"Sum of first 1000 primes: {sum(primes)}")
""")
```

Container result:

```
=== Container Execution Result ===
Exit code: 0
Runtime: 183ms

--- stdout ---
Sum of first 1000 primes: 3682913

--- stderr ---
(empty)
```

ARC's `soul.md` instructs it to reach for `run_python` first rather than estimating — code that can be verified should be verified.

---

## 13. Customising ARC's Personality

ARC's personality and context are defined in markdown files in the `data/` directory. Edit them to make ARC your own. Changes to these files take effect on the next message — no restart required.

### `data/soul.md` — The System Prompt

This is ARC's core personality document. It is injected at the start of every LLM call as part of the system message. It defines:

- **Voice and manner** — how ARC speaks (formal British, dry wit, etc.)
- **Core principles** — behavioural guidelines (be genuinely helpful, have opinions, be resourceful)
- **Boundaries** — what ARC won't do
- **Tool usage patterns** — how and when to use each tool
- **Continuity instructions** — how ARC should handle memory across sessions

**To edit:** Modify the file directly, or use the admin dashboard editor at `http://localhost:8080/editor/soul`.

**Example customisation** — to make ARC more casual:

```markdown
## Voice & Manner
- Speak casually and warmly, like a knowledgeable friend
- Use contractions freely
- Drop the formality — be direct and approachable
```

### `data/identity.md` — The Identity Card

A structured profile with ARC's name, creature type, emoji, speech patterns, and philosophical nature. This is injected alongside `soul.md` as part of the system message.

### `data/user.md` — Your Profile

Tell ARC about yourself. ARC reads this on every trigger so it knows who it's working with.

```markdown
# User Profile

- **Name:** Jeremy
- **What to call me:** Jeremy
- **Timezone:** US/Pacific
- **Projects:** my_agent_arc, a web scraping tool, home automation
- **Preferences:** Concise answers. Python. Tea over coffee.
```

### Other data files

| File | Purpose | Editable via Admin? |
| --- | --- | --- |
| `data/heartbeat.md` | Instructions ARC reads on each heartbeat cycle. ARC can rewrite the "Current Instructions" section itself via the `write_heartbeat` tool. | Yes (`/editor/heartbeat`) |
| `data/tools.md` | Field notes on tool configuration — environment-specific details like API endpoints, service URLs, device names. | No (edit directly) |
| `data/bootstrap.md` | First-run instructions. ARC reads this on initial activation to introduce itself and learn about the user. Delete it after the first session. | No (edit directly) |
| `data/boot.md` | Session boot sequence — lean instructions executed on every startup. | No (edit directly) |
| `data/agents.md` | Operating manual with memory guidelines, safety rules, and heartbeat/cron behaviour. | No (edit directly) |
| `data/mcp_servers.json` | MCP server configuration. See [Section 10](#10-mcp-skill-servers). | No (edit directly) |

---

## 14. Triggers & Scheduling

ARC has four trigger sources. All triggers funnel through the same `handle_trigger` function in `src/arc/gateway.py`, which delegates to `run_agent` in the agentic loop.

### Telegram

When `ARC_TELEGRAM_BOT_TOKEN` is set, ARC creates a `python-telegram-bot` Application that listens for text messages via long-polling. Each incoming message is routed through `handle_trigger` with `source="telegram"` and the chat ID as `session_id`. The agent's response is sent back to the Telegram chat.

Each Telegram chat has its own session, so multiple users get isolated conversation histories.

### Heartbeat

The heartbeat is a periodic trigger driven by APScheduler. Every `ARC_HEARTBEAT_INTERVAL_MINUTES` minutes (default: 15), ARC:

1. Reads `data/heartbeat.md`
2. Checks if the content is empty, whitespace-only, or matches the placeholder `"No current instructions."`
3. If the content is actionable, sends it to the agent as `[HEARTBEAT] <content>`
4. If the content is empty/placeholder, does nothing (no-op)

The heartbeat is how ARC achieves autonomous behaviour. It can program its own future behaviour by calling `write_heartbeat` to update the "Current Instructions" section of `heartbeat.md`. On the next heartbeat cycle, ARC reads those instructions and acts on them.

### Cron

Cron triggers are scheduled prompts. They work like heartbeats but with arbitrary text:

```python
await cron_trigger(prompt="Check the project status", name="daily-status")
```

The prompt is sent to the agent as `[CRON:daily-status] Check the project status`. Cron triggers are intended to be added as APScheduler jobs (see the `cron_trigger` function in `gateway.py`).

Currently, cron jobs can be fired manually from the admin dashboard. Adding persistent cron schedules is on the roadmap.

### Admin (Manual)

The admin dashboard provides buttons to manually fire triggers:

- **Fire Heartbeat** (`POST /trigger/heartbeat`) — runs the heartbeat cycle immediately
- **Fire Cron** (`POST /trigger/cron`) — sends a custom prompt through the agent
- **Run Compaction** (`POST /compact`) — manually triggers context compaction

The admin chat at `/chat` is also a trigger source, using `source="admin"` and session ID `"admin-chat"`.

---

## 15. Deployment on Linux

ARC includes a production-ready install script and systemd service file for Debian/Ubuntu servers.

### Automated install

```bash
sudo bash scripts/install.sh
```

The script is idempotent (safe to re-run) and performs these steps:

1. Installs system dependencies (`python3`, `python3-venv`, `python3-pip`, `git`, `curl`)
2. Checks Python version — if below 3.11, installs from the deadsnakes PPA
3. Installs Ollama (via the official install script) and starts the service
4. Pulls the recommended models (`minimax-m2.5` and `nomic-embed-text`)
5. Creates a dedicated `arc` system user with no login shell
6. Clones the repository to `/opt/arc` (or pulls latest if it already exists)
7. Creates a Python virtual environment at `/opt/arc/.venv` and installs dependencies
8. Copies `.env.example` to `.env` (if `.env` doesn't already exist)
9. Installs and enables the systemd service

### Post-install configuration

After running the script, edit the environment file:

```bash
sudo -u arc nano /opt/arc/.env
```

Set at minimum your Telegram bot token (if desired) and verify the model name.

### Managing the service

```bash
# Start ARC
sudo systemctl start arc

# Stop ARC
sudo systemctl stop arc

# Restart ARC (e.g. after config changes)
sudo systemctl restart arc

# View live logs
sudo journalctl -u arc -f

# Check status
sudo systemctl status arc
```

### The systemd unit file

The service file at `scripts/arc.service` runs ARC as the `arc` user from `/opt/arc`:

```ini
[Unit]
Description=ARC — Autonomous AI Agent Framework
After=network-online.target ollama.service
Wants=network-online.target ollama.service

[Service]
Type=simple
User=arc
Group=arc
WorkingDirectory=/opt/arc
ExecStart=/opt/arc/.venv/bin/python -m arc.main
Restart=on-failure
RestartSec=10
EnvironmentFile=/opt/arc/.env
```

Key features:
- **Ordered startup** — ARC starts after the network is online and Ollama is running
- **Auto-restart** — restarts on failure after a 10-second delay
- **Environment** — loads `.env` via `EnvironmentFile`

### Security hardening

The service file includes security restrictions:

```ini
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/arc/data
PrivateTmp=true
```

These ensure:
- ARC cannot gain additional privileges
- The filesystem is read-only except for `/opt/arc/data` (where the databases and config files live)
- Home directories are hidden from the process
- ARC gets its own private `/tmp`

### Manual systemd setup

If you prefer not to use the install script:

```bash
sudo cp scripts/arc.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable arc
sudo systemctl start arc
```

Edit `/etc/systemd/system/arc.service` to match your installation path and user if they differ from the defaults.

---

## 16. Troubleshooting

### Ollama not running

**Symptom:** ARC starts but returns *"I'm having trouble thinking right now."* on every message.

**Fix:**
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama
ollama serve

# Or if using systemd:
sudo systemctl start ollama
```

### Model not pulled

**Symptom:** Ollama is running but ARC returns errors or empty responses.

**Fix:**
```bash
# List available models
ollama list

# Pull the required models
ollama pull minimax-m2.5
ollama pull nomic-embed-text
```

### Port already in use

**Symptom:** `Address already in use` error on startup.

**Fix:**
```bash
# Find what's using port 8080
lsof -i :8080

# Change the port in .env
ARC_ADMIN_PORT=8081
```

### Telegram token invalid

**Symptom:** ARC logs show `Unauthorized` or `Invalid token` errors.

**Fix:**
1. Verify your token with BotFather — send `/mybots` to @BotFather and check the token
2. Ensure the token is set correctly in `.env` with no extra spaces or quotes:
   ```bash
   ARC_TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNO...
   ```
3. Restart ARC after changing the token

### MCP server fails to connect

**Symptom:** Admin dashboard shows no MCP servers, or logs show `MCP: failed to connect server`.

**Fix:**
1. Check `data/mcp_servers.json` syntax — it must be valid JSON
2. Verify the server command works standalone:
   ```bash
   python tools/test_server.py
   # Should hang (waiting for stdio input) — Ctrl+C to exit
   ```
3. Check that required dependencies are installed (e.g. `mcp[cli]` for Python servers, Node.js for `npx` servers)
4. Check the logs at `/logs` or `journalctl -u arc -f` for specific error messages

### Context compaction not working

**Symptom:** Conversations get slow or truncated after many messages.

**Fix:**
1. Check the compaction threshold — with defaults, compaction triggers after ~4096 estimated tokens of non-compacted messages
2. Manually trigger compaction from the admin dashboard (`POST /compact`)
3. Check that Ollama can generate summaries — compaction uses the configured chat model to summarise

### ChromaDB memory not saving

**Symptom:** `search_memory` always returns empty results.

**Fix:**
1. Verify the embedding model is pulled: `ollama list` should show `nomic-embed-text`
2. Check that `data/chromadb` directory exists and is writable
3. Check logs for `"Ollama embedding unavailable"` messages

### Permission errors on Linux

**Symptom:** ARC fails to write to databases or config files.

**Fix:**
```bash
# Ensure the arc user owns the data directory
sudo chown -R arc:arc /opt/arc/data

# Check systemd ReadWritePaths includes the data dir
sudo systemctl cat arc | grep ReadWritePaths
```

### ARC is unresponsive

**Symptom:** No response from admin chat or Telegram, but no errors in logs.

**Fix:**
1. Check if Ollama is overloaded — large models can take a while to respond
2. Check `ARC_MAX_AGENT_ITERATIONS` — if the agent is stuck in a tool-calling loop, it will eventually time out
3. Restart ARC:
   ```bash
   sudo systemctl restart arc
   # or Ctrl+C and re-run: python -m arc.main
   ```

---

*For more information, visit the [ARC repository on GitHub](https://github.com/BitsofJeremy/my_agent_arc).*
