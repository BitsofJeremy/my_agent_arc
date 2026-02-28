# OpenClaw-Inspired Autonomous Agent Framework — Implementation Plan

## Problem Statement
Build a modular, single-purpose autonomous AI agent framework with four architectural zones: **Triggers**, **Context Injection**, **Agentic Loop (LLM + Tools)**, and **Outputs/Memory**. The agent uses Ollama for local LLM inference, Telegram as primary interface, SQLite for relational storage, ChromaDB for vector memory/RAG, FastAPI for admin, and APScheduler for scheduling.

## Proposed Approach
Implement bottom-up: foundational layers first (config, database), then core logic (context, memory, tools, agent loop), then interfaces (gateway, admin), and finally the entry point that wires everything together.

## Project Structure
```
my_agent_arc/
├── docs/
│   └── PLAN.md                # This plan
├── src/
│   └── openclaw/
│       ├── __init__.py
│       ├── config.py          # Settings, env vars, constants
│       ├── database.py        # SQLite schema + ChromaDB init
│       ├── memory.py          # ChromaDB RAG wrapper + tools
│       ├── context_manager.py # History fetch, compaction, injection
│       ├── tools.py           # Base tool implementations
│       ├── agent.py           # Agentic loop with Ollama
│       ├── gateway.py         # Triggers: Telegram, heartbeat, cron
│       ├── admin.py           # FastAPI + Jinja2 admin dashboard
│       └── main.py            # Entry point wiring everything
├── templates/                 # Jinja2 HTML templates for admin
│   ├── base.html
│   ├── dashboard.html
│   ├── editor.html
│   └── logs.html
├── data/
│   ├── soul.md                # System prompt file
│   └── heartbeat.md           # Heartbeat instruction file
├── requirements.txt
├── pyproject.toml
└── README.md
```

## Todos

### Phase 1 — Foundation
1. **project-scaffold**: Create directory structure, `pyproject.toml`, `requirements.txt`, `.env.example`, and placeholder `soul.md` / `heartbeat.md`.
2. **config-module**: Build `config.py` — load settings from env vars with sensible defaults (Ollama URL, model name, Telegram token, DB paths, context window size, compaction threshold).
3. **database-module**: Build `database.py` — SQLite schema for conversation turns (`messages` table with role, content, token_estimate, compacted flag, timestamps), `compacted_nodes` table, ChromaDB collection init.

### Phase 2 — Core Logic
4. **memory-module**: Build `memory.py` — ChromaDB wrapper exposing `search_memory(query)` and `save_to_memory(fact)` as tool-callable functions. Include embedding via Ollama embeddings endpoint.
5. **context-manager**: Build `context_manager.py` — fetch recent history from SQLite, detect 50% capacity threshold, run compaction (summarize via LLM → store in `compacted_nodes` + ChromaDB), assemble full context (system prompt + compacted summary + recent raw turns + tool schemas).
6. **tools-module**: Build `tools.py` — implement `search_memory`, `save_to_memory`, `write_heartbeat`. Define tool schemas in Ollama function-calling format. Include a tool registry/dispatcher.
7. **agent-loop**: Build `agent.py` — the core loop: receive context → call Ollama → parse response → if tool call, execute and re-loop → if final text, return. Include error handling for Ollama failures, hallucinated tool names, malformed arguments, and max-iteration guardrail.

### Phase 3 — Interfaces
8. **gateway-triggers**: Build `gateway.py` — Telegram bot (polling mode for simplicity, webhook-ready), heartbeat trigger (reads `heartbeat.md`, sends to agent), cron task trigger. All triggers funnel through a unified `handle_trigger(source, payload)` function.
9. **admin-dashboard**: Build `admin.py` — FastAPI app with Jinja2 templates: dashboard (DB stats, trigger controls), live log viewer (SSE endpoint), soul.md/heartbeat.md editor, manual compaction trigger.
10. **templates**: Create Jinja2 HTML templates for admin UI.

### Phase 4 — Integration & Entry Point
11. **main-entrypoint**: Build `main.py` — initialize all components, start Telegram bot, mount FastAPI admin, configure APScheduler heartbeat/cron jobs, run event loop.
12. **readme-update**: Update `README.md` with setup instructions, architecture overview, and usage guide.

### Dependencies
- `config-module` → depends on `project-scaffold`
- `database-module` → depends on `config-module`
- `memory-module` → depends on `database-module`
- `context-manager` → depends on `database-module`, `memory-module`
- `tools-module` → depends on `memory-module`
- `agent-loop` → depends on `context-manager`, `tools-module`
- `gateway-triggers` → depends on `agent-loop`
- `admin-dashboard` → depends on `database-module`, `context-manager`, `gateway-triggers`
- `main-entrypoint` → depends on `gateway-triggers`, `admin-dashboard`

## Key Design Decisions
- **Polling over Webhooks** for Telegram initially (simpler local dev; webhook can be added later).
- **Ollama native function calling** — use the `tools` parameter in `ollama.chat()`. Fallback: parse structured JSON from model output if model doesn't support native tool use.
- **Token estimation** — use a simple `len(text) // 4` heuristic (configurable). No external tokenizer dependency.
- **Compaction at 50%** of configured context window size, keeping most recent N messages raw.
- **SSE (Server-Sent Events)** for live log streaming in admin UI — lightweight, no WebSocket dependency.
- **SQLite WAL mode** for concurrent read/write from bot + admin.

## Notes
- Telegram bot token and Ollama model name must be configured via environment variables before running.
- ChromaDB runs in persistent local mode (no server needed).
- The agent can reprogram its own future behavior via `write_heartbeat` tool — this is a core autonomy feature.
