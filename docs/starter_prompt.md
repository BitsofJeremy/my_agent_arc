Make me an agent: Context and Objective
Act as a Senior AI Architect and Lead Python Engineer. Your task is to build a custom, single-purpose autonomous AI agent framework inspired by "OpenClaw".
The architecture consists of four zones: Triggers, Context Injection, The Agentic Loop (LLM + Tools), and Outputs/Memory.

Technology Stack
* Language: Python 3.11+
* LLM Engine: Ollama (local models via ollama Python library).
* Primary Interface: Telegram (via python-telegram-bot).
* Relational Storage / History: SQLite (replaces JSONL stores for durability and querying).
* Vector Storage / Memory: ChromaDB (for RAG memory retrieval).
* Admin Interface: FastAPI with Jinja2 templates (Alternative: Streamlit if rapid prototyping is preferred. Implement FastAPI by default).
* Task Scheduling: APScheduler (for Cron and Heartbeat triggers).

System Architecture & Requirements

1. Gateway & Triggers (gateway.py)
The system must be always-on and react to multiple event types:
* Telegram Webhook/Polling: Listen for user messages.
* Heartbeat: A cron job that fires every X minutes, instructing the agent to read a heartbeat.md instruction file and decide if it needs to act.
* Cron Tasks: Scheduled custom prompts that wake the agent up for specific routines (e.g., "morning briefing").

2. Context Management & Compaction (context_manager.py)
* SQLite History: All turns (User, Agent, Tool inputs/outputs) must be logged in an SQLite database.
* Compaction Engine: Do not pass the entire SQLite history to the LLM. Track approximate token counts. When the context window reaches 50% capacity:
    1. Fetch older chunks of messages.
    2. Ask the LLM to summarize them.
    3. Store the summary back in SQLite as a "compacted_node".
    4. Write the detailed summary to ChromaDB for long-term retrieval.
    5. Keep only the summary and the most recent raw messages in the active context window.
* Injection: On every trigger, inject the System Prompt (from a local soul.md file), the compacted context, recent raw history, and available Tool Schemas.

3. Memory & RAG (memory.py)
* Implement ChromaDB.
* Expose a search_memory(query: str) tool to the LLM.
* When the LLM needs to recall old facts, it must proactively call this tool. The tool queries ChromaDB and returns the context.

4. Agentic Loop & Tools (agent.py & tools/)
* Connect to Ollama using its native function-calling/tool schemas.
* The Loop:
    1. Gateway receives a trigger and passes context to the LLM.
    2. LLM decides to either respond with text or call a tool.
    3. If a tool is called, execute it in a controlled local environment.
    4. Append tool execution results to the context and call the LLM again.
    5. Repeat until the LLM outputs a final user-facing response.
* Required Base Tools:
    * search_memory(query)
    * save_to_memory(fact)
    * write_heartbeat(instructions): Allows the agent to program its own future behavior by modifying the heartbeat.md file.

5. Admin Interface (admin.py)
Build a basic HTTP dashboard that allows the user to:
* View live logs of the Agentic Loop.
* View and edit the soul.md (System Prompt) and heartbeat.md.
* Manually trigger a heartbeat or cron job.
* View the SQLite database size and trigger manual compaction.

Output Requirements
Do not write the entire application in a single script. Generate the code using a modular structure.
Provide the following:
1. requirements.txt
2. database.py (SQLite and ChromaDB initialization schema).
3. tools.py (Implementation of the base tools).
4. context_manager.py (Logic for fetching history and the compaction algorithm).
5. agent.py (The main loop connecting Ollama, context, and tools).
6. main.py (The entry point initializing the Telegram bot, APScheduler, and FastAPI admin UI).
Write robust, production-ready Python code. Include explicit error handling for when Ollama fails or hallucinates a tool call.
