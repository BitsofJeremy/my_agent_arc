# ARC — Autonomous AI Agent Framework

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://python.org)
[![Ollama](https://img.shields.io/badge/LLM-Ollama-black.svg)](https://ollama.com)

A modular, self-contained autonomous AI agent built on four architectural zones:
**Triggers**, **Context Injection**, **Agentic Loop**, and **Outputs/Memory**.
ARC runs entirely on your own hardware — no API keys, no cloud dependencies, no
data leaving your machine.

> **Repository:** <https://github.com/BitsofJeremy/my_agent_arc>

---

## Table of Contents

- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Configuration Reference](#configuration-reference)
- [Connecting Telegram](#connecting-telegram)
- [Customising ARC's Personality](#customising-arcs-personality)
- [MCP Skill Servers](#mcp-skill-servers)
- [Admin Dashboard](#admin-dashboard)
- [Deploying with systemd (Debian/Ubuntu)](#deploying-with-systemd)
- [Design Decisions](#design-decisions)
- [Roadmap](#roadmap)
- [License](#license)

---

## Architecture

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

---

## Tech Stack

| Component       | Technology                                        |
| --------------- | ------------------------------------------------- |
| Runtime         | Python 3.11+                                      |
| LLM Inference   | [Ollama](https://ollama.com/) (local models)      |
| Recommended LLM | [minimax-m2.5](https://ollama.com/library/minimax-m2.5) |
| Chat Interface  | [python-telegram-bot](https://python-telegram-bot.org/) |
| Relational DB   | SQLite (aiosqlite, WAL mode)                      |
| Vector Memory   | ChromaDB (persistent, local)                      |
| Admin Dashboard | FastAPI + Jinja2 + SSE                            |
| Scheduling      | APScheduler                                       |
| Skill Plugins   | [MCP](https://modelcontextprotocol.io/) (stdio)   |
| Config          | python-dotenv                                     |

---

## Project Structure

```
my_agent_arc/
├── src/arc/
│   ├── __init__.py
│   ├── config.py            # Settings from env vars (.env)
│   ├── database.py          # SQLite schema + ChromaDB init
│   ├── memory.py            # ChromaDB RAG wrapper (Ollama embeddings)
│   ├── context_manager.py   # History, compaction, prompt assembly
│   ├── tools.py             # Built-in tool schemas + MCP dispatcher
│   ├── mcp_client.py        # MCP server connections & tool discovery
│   ├── agent.py             # Core agentic loop (Ollama ↔ tools)
│   ├── gateway.py           # Triggers: Telegram, heartbeat, cron
│   ├── admin.py             # FastAPI admin dashboard + chat
│   └── main.py              # Entry point — wires everything together
├── templates/               # Jinja2 HTML for admin UI
│   ├── base.html
│   ├── dashboard.html
│   ├── editor.html
│   ├── chat.html
│   └── logs.html
├── data/
│   ├── soul.md              # System prompt (agent personality)
│   ├── identity.md          # Agent identity card
│   ├── user.md              # User profile (your info for ARC)
│   ├── heartbeat.md         # Self-directed heartbeat instructions
│   ├── tools.md             # Tool usage guidelines
│   ├── bootstrap.md         # First-run bootstrap instructions
│   ├── boot.md              # Session boot sequence
│   ├── agents.md            # Multi-agent coordination (future)
│   └── mcp_servers.json     # MCP server configuration
├── tools/
│   └── test_server.py       # Example MCP server (ping + echo)
├── scripts/
│   ├── install.sh           # Debian/Ubuntu install script
│   └── arc.service          # systemd unit file
├── docs/
│   └── PLAN.md
├── pyproject.toml
├── requirements.txt
├── .env.example
├── LICENSE                   # AGPL-3.0
└── README.md
```

---

## Quick Start

### Prerequisites

- **Python 3.11+**
- **[Ollama](https://ollama.com/download)** installed and running
- (Optional) A Telegram bot token from [@BotFather](https://t.me/BotFather)

### 1. Clone the repository

```bash
git clone https://github.com/BitsofJeremy/my_agent_arc.git
cd my_agent_arc
```

### 2. Pull the LLM models

```bash
ollama pull minimax-m2.5          # recommended chat model
ollama pull nomic-embed-text      # embedding model for memory
```

> **Model choice:** We recommend [minimax-m2.5](https://ollama.com/library/minimax-m2.5)
> for its strong tool-calling support and reasoning quality. Any Ollama model
> with function-calling support will work — set `ARC_OLLAMA_MODEL` in `.env`.

### 3. Create a virtual environment & install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
ARC_OLLAMA_MODEL=minimax-m2.5       # or your preferred model
ARC_TELEGRAM_BOT_TOKEN=your-token   # optional — admin chat works without it
```

### 5. Run ARC

```bash
python -m arc.main
```

ARC starts three subsystems concurrently:

| Subsystem          | What it does                           |
| ------------------ | -------------------------------------- |
| **Admin Dashboard** | Web UI at `http://localhost:8080`      |
| **Telegram Bot**    | Listens for messages (if token is set) |
| **Heartbeat**       | Periodic autonomous trigger            |

> **Telegram is optional.** ARC runs fine without it — use the admin chat at
> `http://localhost:8080/chat` instead.

---

## Configuration Reference

All settings use the `ARC_` prefix and are loaded from `.env` or environment
variables.

| Variable                          | Default                  | Description                                         |
| --------------------------------- | ------------------------ | --------------------------------------------------- |
| `ARC_TELEGRAM_BOT_TOKEN`          | *(empty — bot disabled)* | Telegram Bot API token from @BotFather              |
| `ARC_OLLAMA_HOST`                 | `http://localhost:11434` | Ollama server URL                                   |
| `ARC_OLLAMA_MODEL`                | `minimax-m2.5`           | Chat model for the agentic loop                     |
| `ARC_OLLAMA_EMBED_MODEL`          | `nomic-embed-text`       | Embedding model for ChromaDB memory                 |
| `ARC_SQLITE_DB_PATH`             | `data/arc.db`            | SQLite database file path                           |
| `ARC_CHROMADB_PATH`              | `data/chromadb`          | ChromaDB persistent storage path                    |
| `ARC_CONTEXT_WINDOW_TOKENS`      | `8192`                   | Max tokens for assembled context window             |
| `ARC_COMPACTION_THRESHOLD`       | `0.5`                    | Context window fraction that triggers compaction    |
| `ARC_HEARTBEAT_INTERVAL_MINUTES` | `15`                     | Minutes between autonomous heartbeat triggers       |
| `ARC_ADMIN_HOST`                 | `0.0.0.0`               | Admin dashboard bind address                        |
| `ARC_ADMIN_PORT`                 | `8080`                   | Admin dashboard port                                |
| `ARC_SOUL_PATH`                  | `data/soul.md`           | Path to the system prompt (personality) file        |
| `ARC_HEARTBEAT_PATH`            | `data/heartbeat.md`      | Path to heartbeat instruction file                  |
| `ARC_MAX_AGENT_ITERATIONS`      | `10`                     | Max tool-call loops before forced response          |

---

## Connecting Telegram

### Step 1: Create a bot with BotFather

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Choose a name (e.g. "ARC Agent") and username (e.g. `arc_agent_bot`)
4. BotFather gives you a token like `123456789:ABCdefGHIjklMNO...`

### Step 2: Configure ARC

Add the token to your `.env`:

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

ARC will start polling for Telegram messages. Send any message to your bot and
ARC will respond in character.

> **Privacy:** ARC uses long-polling (not webhooks), so no public URL or port
> forwarding is required. All messages are processed locally.

---

## Customising ARC's Personality

ARC's personality is defined in three markdown files in the `data/` directory.
Edit them to make ARC your own.

### `data/soul.md` — The System Prompt

This is ARC's core personality document, injected at the start of every LLM
call. It defines:

- **Voice & manner** — how ARC speaks (formal British, dry wit, etc.)
- **Core principles** — behavioural guidelines
- **Boundaries** — what ARC won't do
- **Tool usage patterns** — how ARC should use its tools

**To change ARC's personality:** Edit `soul.md` directly or use the admin
dashboard editor at `http://localhost:8080/editor/soul`. Changes take effect
on the next message — no restart required.

**Example:** To make ARC more casual, you might change:
```markdown
## Voice & Manner
- Speak casually and warmly, like a knowledgeable friend
- Use contractions freely
- Drop the formality — be direct and approachable
```

### `data/identity.md` — The Identity Card

A structured profile with ARC's name, creature type, emoji, and speech patterns.
This is injected alongside `soul.md` on every call.

### `data/user.md` — Your Profile

Tell ARC about yourself — your name, preferences, timezone, projects. ARC reads
this on every trigger so it knows who it's working with.

**Example:**
```markdown
# User Profile

- **Name:** Jeremy
- **Timezone:** US/Pacific
- **Projects:** my_agent_arc, a web scraping tool, a home automation system
- **Preferences:** Prefers concise answers. Likes Python. Tea over coffee.
```

### Other Template Files

| File               | Purpose                                          |
| ------------------ | ------------------------------------------------ |
| `data/heartbeat.md` | Instructions ARC reads on each heartbeat cycle. ARC can rewrite this itself via the `write_heartbeat` tool. |
| `data/tools.md`     | Guidelines for how ARC should use its tools      |
| `data/bootstrap.md` | First-run instructions                           |
| `data/boot.md`      | Session boot sequence                            |
| `data/agents.md`    | Multi-agent coordination (future use)            |

---

## MCP Skill Servers

ARC supports [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
servers to extend its capabilities with external tools. MCP servers run as
subprocesses and communicate over stdio.

### How it works

1. ARC reads `data/mcp_servers.json` at startup
2. Launches each configured server as a subprocess
3. Discovers available tools via the MCP protocol
4. Merges those tools into ARC's tool catalogue
5. When the LLM calls an MCP tool, ARC routes it to the correct server

### Configuring MCP Servers

Edit `data/mcp_servers.json`:

```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/documents"]
    },
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

Each server entry has:

| Field     | Required | Description                                    |
| --------- | -------- | ---------------------------------------------- |
| `command` | Yes      | Executable to run (e.g. `npx`, `python`, `node`) |
| `args`    | No       | Command-line arguments                         |
| `env`     | No       | Additional environment variables               |

After editing, restart ARC. Connected servers and their tools appear on the
admin dashboard.

### Built-in Test Server

ARC ships with a test MCP server at `tools/test_server.py` providing `ping`
and `echo` tools. It's pre-configured in `mcp_servers.json`:

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

### Writing Your Own MCP Server

Create a Python file in `tools/` using the MCP SDK:

```python
#!/usr/bin/env python3
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
                    "input": {"type": "string", "description": "The input"},
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

Add it to `mcp_servers.json` and restart ARC.

### Finding MCP Servers

Browse the [MCP Server Directory](https://github.com/modelcontextprotocol/servers)
for community-built servers. Most can be added with a single `npx` command
(requires Node.js).

---

## Admin Dashboard

The built-in web UI runs at **http://localhost:8080** and provides:

| Page        | URL              | Description                                          |
| ----------- | ---------------- | ---------------------------------------------------- |
| Dashboard   | `/`              | Database stats, MCP server status, recent messages   |
| Chat        | `/chat`          | Conversational chat interface with ARC               |
| Logs        | `/logs`          | Live-streaming log viewer (Server-Sent Events)       |
| Soul Editor | `/editor/soul`   | Edit ARC's personality (soul.md) in-browser          |
| Heartbeat   | `/editor/heartbeat` | Edit heartbeat instructions in-browser            |

**Manual triggers:** The dashboard has buttons to manually fire the heartbeat,
send custom cron prompts, and trigger context compaction.

---

## Deploying with systemd

For Debian/Ubuntu servers, use the provided install script:

```bash
# Download and run the installer
sudo bash scripts/install.sh
```

The script:

1. Installs Python 3.11+ and system dependencies
2. Installs Ollama and pulls the recommended models
3. Creates a dedicated `arc` system user
4. Clones the repository to `/opt/arc`
5. Creates a Python virtual environment and installs dependencies
6. Copies `.env.example` to `.env` (edit afterwards)
7. Installs and enables `arc.service` for systemd

### Managing the service

```bash
# Start / stop / restart
sudo systemctl start arc
sudo systemctl stop arc
sudo systemctl restart arc

# View logs
sudo journalctl -u arc -f

# Check status
sudo systemctl status arc
```

### Manual systemd setup

If you prefer to set things up manually, copy the service file:

```bash
sudo cp scripts/arc.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable arc
sudo systemctl start arc
```

Edit `/etc/systemd/system/arc.service` to match your installation path and
user. See `scripts/arc.service` for the template.

---

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| **Local-first** | All inference via Ollama | No data leaves your machine |
| **Polling over webhooks** | Telegram long-polling | Simpler for local dev; no public URL needed |
| **Token estimation** | `len(text) // 4` | No external tokenizer dependency |
| **Compaction at 50%** | Summarise older messages | Keeps context fresh within token budget |
| **Self-reprogramming** | `write_heartbeat` tool | Agent can alter its own future behaviour |
| **SQLite WAL mode** | Concurrent reads/writes | Bot and admin dashboard share the DB safely |
| **MCP for plugins** | Stdio transport | Standard protocol, huge ecosystem of servers |
| **Built-in tools win** | Name conflict resolution | Prevents MCP servers overriding core behaviour |

---

## Roadmap

- [x] Core agentic loop with Ollama
- [x] Telegram integration
- [x] SQLite + ChromaDB hybrid storage
- [x] Context compaction engine
- [x] FastAPI admin dashboard with chat
- [x] MCP skill server support
- [x] Formal British personality (ARC character)
- [x] systemd deployment scripts
- [ ] **Voice interface** — TTS (text-to-speech) and STT (speech-to-text) for
  hands-free interaction via Telegram voice messages or a local microphone
- [ ] Webhook mode for Telegram (production deployment)
- [ ] Multi-session support with session management UI
- [ ] Agent-to-agent communication (`agents.md`)

---

## License

This project is licensed under the **GNU Affero General Public License v3.0
(AGPL-3.0)**. See [LICENSE](LICENSE) for details.