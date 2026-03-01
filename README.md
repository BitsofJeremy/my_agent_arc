# ARC — Analytical Resonance Core

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://python.org)
[![Ollama](https://img.shields.io/badge/LLM-Ollama-black.svg)](https://ollama.com)

A modular, self-contained autonomous AI agent that runs entirely on your own hardware. No API keys, no cloud dependencies, no data leaving your machine. ARC can search its own memory, program its own future behaviour, and write its own tools at runtime.

> 📖 **[Complete User Guide →](docs/guide.md)** — installation, configuration, architecture, and operations.

---

## Architecture

ARC is organised into four zones:

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

## Key Features

- **Fully local** — all LLM inference via [Ollama](https://ollama.com/). Your data never leaves your machine.
- **Agentic loop with tool use** — iterative LLM↔tool calling until a final answer is produced
- **Long-term vector memory** — ChromaDB stores facts across sessions, searchable via RAG
- **Context compaction** — automatic summarisation keeps conversations within the token budget
- **Self-programming** — ARC can rewrite its own heartbeat instructions to change future behaviour
- **Self-authoring skills** — ARC can create new MCP tool servers at runtime and hot-reload them
- **Sandboxed code execution** — ARC can spin up ephemeral Docker containers to run Python, shell scripts, JavaScript, or any language
- **MCP plugin ecosystem** — extend capabilities with any [Model Context Protocol](https://modelcontextprotocol.io/) server
- **Telegram + Web chat** — talk to ARC via Telegram or the built-in admin dashboard
- **Customisable personality** — edit markdown files to change voice, character, and behaviour instantly
- **Production-ready deployment** — systemd service with security hardening for Linux servers

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/BitsofJeremy/my_agent_arc.git
cd my_agent_arc

# 2. Pull models
ollama pull minimax-m2.5
ollama pull nomic-embed-text

# 2.5. Install Docker (required for sandboxed code execution)
# macOS/Windows: install Docker Desktop — https://www.docker.com/products/docker-desktop/
# Linux:         install Docker Engine — https://docs.docker.com/engine/install/

# 3. Install
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 4. Configure
cp .env.example .env          # edit .env to set your preferences

# 5. Run
python -m arc.main            # admin dashboard at http://localhost:8080
```

Open **http://localhost:8080/chat** to start talking to ARC. Telegram is optional — set `ARC_TELEGRAM_BOT_TOKEN` in `.env` if you want it.

> See the **[Complete User Guide](docs/guide.md)** for detailed setup, all configuration options, and deployment instructions.

---

## Project Structure

```
my_agent_arc/
├── src/arc/
│   ├── config.py            # Settings from env vars (.env)
│   ├── database.py          # SQLite schema + ChromaDB init
│   ├── memory.py            # ChromaDB RAG wrapper (Ollama embeddings)
│   ├── context_manager.py   # History, compaction, prompt assembly
│   ├── tools.py             # Built-in tool schemas + dispatcher
│   ├── mcp_client.py        # MCP server connections & tool discovery
│   ├── agent.py             # Core agentic loop (Ollama ↔ tools)
│   ├── gateway.py           # Triggers: Telegram, heartbeat, cron
│   ├── admin.py             # FastAPI admin dashboard + chat
│   └── main.py              # Entry point
├── data/                    # Personality, config, databases
│   ├── soul.md              # System prompt (agent personality)
│   ├── identity.md          # Agent identity card
│   ├── user.md              # User profile
│   ├── heartbeat.md         # Self-directed heartbeat instructions
│   └── mcp_servers.json     # MCP server configuration
├── tools/                   # MCP tool servers
│   ├── docker_server.py     # Docker execution MCP server (run_python, run_shell, run_node, run_in_image)
│   └── test_server.py       # Example MCP server (ping + echo)
├── templates/               # Jinja2 HTML for admin UI
├── scripts/
│   ├── install.sh           # Debian/Ubuntu automated installer
│   └── arc.service          # systemd unit file
├── docs/
│   └── guide.md             # Complete user guide
├── pyproject.toml
├── requirements.txt
├── .env.example
└── LICENSE
```

---

## Built With

| Component | Technology |
| --- | --- |
| LLM Inference | [Ollama](https://ollama.com/) — recommended model: [minimax-m2.5](https://ollama.com/library/minimax-m2.5) |
| Chat Interface | [python-telegram-bot](https://python-telegram-bot.org/) |
| Relational Storage | SQLite via [aiosqlite](https://github.com/omnilib/aiosqlite) (WAL mode) |
| Vector Memory | [ChromaDB](https://www.trychroma.com/) (persistent, local) |
| Admin Dashboard | [FastAPI](https://fastapi.tiangolo.com/) + Jinja2 + SSE |
| Scheduling | [APScheduler](https://apscheduler.readthedocs.io/) |
| Skill Plugins | [Model Context Protocol](https://modelcontextprotocol.io/) (stdio transport) |
| Sandboxed Execution | Docker (ephemeral containers via Python Docker SDK) |

---

## Roadmap

- [ ] **TTS/STT voice interface** — hands-free interaction via Telegram voice messages or local microphone
- [ ] **Web search tools** — give ARC the ability to search the internet
- [ ] **Multi-agent coordination** — agent-to-agent communication via `agents.md`
- [ ] Webhook mode for Telegram (production deployment)
- [ ] Multi-session support with session management UI

---

## License

[AGPL-3.0](LICENSE)