# ARC — Autonomous AI Agent Framework

A modular, self-contained autonomous AI agent built on four architectural zones:
**Triggers**, **Context Injection**, **Agentic Loop**, and **Outputs/Memory**.
ARC uses [Ollama](https://ollama.com/) for local LLM inference,
[Telegram](https://core.telegram.org/bots) as its primary conversational
interface, SQLite + ChromaDB for hybrid relational/vector storage, and a
FastAPI admin dashboard for monitoring and control.

> **Status:** early prototype (v0.1.0) — functional but evolving.

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
│  │  soul.md + compacted summaries + recent turns │               │
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
│           │  search_memory          │                           │
│           │  save_to_memory         │                           │
│           │  write_heartbeat        │                           │
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

| Component       | Technology                          |
| --------------- | ----------------------------------- |
| Runtime         | Python 3.11+                        |
| LLM Inference   | Ollama (local, tool-calling models) |
| Chat Interface  | python-telegram-bot                 |
| Relational DB   | SQLite (aiosqlite, WAL mode)        |
| Vector Memory   | ChromaDB (persistent, local)        |
| Admin Dashboard | FastAPI + Jinja2 + SSE              |
| Scheduling      | APScheduler                         |
| Config          | python-dotenv                       |

---

## Project Structure

```
my_agent_arc/
├── src/
│   └── arc/
│       ├── __init__.py
│       ├── config.py            # Settings from env vars (.env)
│       ├── database.py          # SQLite schema + ChromaDB init
│       ├── memory.py            # ChromaDB RAG wrapper (embed via Ollama)
│       ├── context_manager.py   # History, compaction, prompt assembly
│       ├── tools.py             # Tool schemas + dispatcher
│       ├── agent.py             # Core agentic loop (Ollama ↔ tools)
│       ├── gateway.py           # Triggers: Telegram, heartbeat, cron
│       ├── admin.py             # FastAPI admin dashboard
│       └── main.py              # Entry point — wires everything together
├── templates/                   # Jinja2 HTML for admin UI
│   ├── base.html
│   ├── dashboard.html
│   ├── editor.html
│   └── logs.html
├── data/
│   ├── soul.md                  # System prompt (agent personality)
│   └── heartbeat.md             # Heartbeat instruction file
├── docs/
│   └── PLAN.md                  # Architecture & implementation plan
├── pyproject.toml
├── requirements.txt
├── .env.example
├── LICENSE                      # AGPL-3.0
└── README.md
```

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/your-org/my_agent_arc.git
cd my_agent_arc
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set TELEGRAM_BOT_TOKEN
```

### 3. Install and start Ollama

```bash
# Install Ollama (https://ollama.com/download)
ollama pull llama3.1:8b           # default chat model
ollama pull nomic-embed-text      # embedding model for memory
```

### 4. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 5. Run the agent

```bash
python -m arc.main
```

The agent will start three concurrent subsystems:

- **Telegram bot** — listening for messages (long-polling)
- **Heartbeat scheduler** — periodic autonomous trigger (APScheduler)
- **Admin dashboard** — web UI at `http://localhost:8080`

---

## Configuration

All settings are loaded from environment variables (or `.env` file).

| Variable                     | Default                    | Description                                        |
| ---------------------------- | -------------------------- | -------------------------------------------------- |
| `TELEGRAM_BOT_TOKEN`         | *(required)*               | Telegram Bot API token from @BotFather             |
| `OLLAMA_HOST`                | `http://localhost:11434`   | Ollama server URL                                  |
| `OLLAMA_MODEL`               | `llama3.1:8b`              | Chat model for the agentic loop                    |
| `OLLAMA_EMBED_MODEL`         | `nomic-embed-text`         | Embedding model for ChromaDB memory                |
| `SQLITE_DB_PATH`             | `data/arc.db`              | Path to SQLite database file                       |
| `CHROMADB_PATH`              | `data/chromadb`            | Path to ChromaDB persistent storage                |
| `CONTEXT_WINDOW_TOKENS`      | `8192`                     | Max tokens for the assembled context window        |
| `COMPACTION_THRESHOLD`       | `0.5`                      | Fraction of context window that triggers compaction |
| `HEARTBEAT_INTERVAL_MINUTES` | `15`                       | Minutes between autonomous heartbeat triggers      |
| `ADMIN_HOST`                 | `0.0.0.0`                  | Admin dashboard bind address                       |
| `ADMIN_PORT`                 | `8080`                     | Admin dashboard port                               |

---

## Modules

### `config.py` — Settings

Loads all settings from environment variables and `.env` into an immutable
`Settings` dataclass. Handles path resolution, type coercion, and sensible
defaults.

### `database.py` — Storage Layer

Manages SQLite (async, WAL-enabled) and ChromaDB (persistent, local)
initialization. Provides async context managers for database access and defines
the schema: `messages` table (conversation turns with token estimates and
compaction flags) and `compacted_nodes` table (summaries).

### `memory.py` — Vector Memory / RAG

Retrieval-Augmented Generation interface wrapping ChromaDB. Exposes
`search_memory(query)` and `save_to_memory(fact)` functions that embed text
via Ollama and query/store results in the vector collection.

### `context_manager.py` — Context Assembly & Compaction

Handles conversation history logging, token-aware context compaction (summarizes
older messages via Ollama when the token budget is exceeded), and assembly of the
final chat context: system prompt (`soul.md`) → compacted summaries → recent raw
turns → tool schemas.

### `tools.py` — Tool Registry

Defines Ollama-compatible tool schemas and implementations for the agent's three
tools: `search_memory`, `save_to_memory`, and `write_heartbeat`. Includes a
central dispatcher that routes tool invocations by name.

### `agent.py` — Agentic Loop

The core reasoning loop. Iteratively calls Ollama with the assembled context and
tool definitions, executes any tool calls, feeds results back, and repeats until
the model produces a final text response or the iteration limit is reached.
Includes error handling for Ollama failures, hallucinated tool names, and
malformed arguments.

### `gateway.py` — Triggers

Inbound integration layer providing a Telegram bot handler, a heartbeat trigger
(reads `heartbeat.md` and sends it to the agent), and a generic cron trigger.
All triggers route through a unified `handle_trigger(source, payload)` entry
point.

### `admin.py` — Admin Dashboard

FastAPI application with Jinja2 templates. Provides a web UI for monitoring
database stats, browsing conversation messages, streaming live logs via
Server-Sent Events (SSE), editing `soul.md`/`heartbeat.md` in-browser, and
manually triggering heartbeat, cron, or compaction operations.

### `main.py` — Entry Point

Async entry point that initializes all components and concurrently runs three
subsystems: Telegram bot (long-polling), APScheduler (periodic heartbeat), and
Uvicorn (FastAPI admin dashboard). Handles graceful shutdown on `SIGINT`/`SIGTERM`.

---

## Admin Dashboard

The built-in admin UI runs at **http://localhost:8080** (configurable) and offers:

- **Dashboard** — database statistics, message counts, memory collection size,
  and quick-action buttons for triggers.
- **Logs** — live-streaming log viewer powered by Server-Sent Events.
- **Editor** — in-browser editor for `soul.md` (system prompt) and
  `heartbeat.md` (autonomous heartbeat instructions). Changes take effect on the
  next agent invocation.
- **Manual Controls** — trigger heartbeat, cron, or context compaction on demand.

---

## Key Design Decisions

- **Local-first** — all inference runs through Ollama; no data leaves your machine.
- **Polling over Webhooks** for Telegram (simpler for local dev; webhook-ready).
- **Token estimation** via `len(text) // 4` heuristic (no external tokenizer dependency).
- **Compaction at 50%** of the context window — older messages are summarized and
  stored as compacted nodes in both SQLite and ChromaDB.
- **Self-reprogramming** — the agent can rewrite `heartbeat.md` via the
  `write_heartbeat` tool, altering its own future autonomous behavior.
- **SQLite WAL mode** for concurrent reads/writes from the bot and admin dashboard.

---

## License

This project is licensed under the **GNU Affero General Public License v3.0
(AGPL-3.0)**. See [LICENSE](LICENSE) for details.