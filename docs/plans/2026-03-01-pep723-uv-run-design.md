# PEP 723 + uv run — System-Wide Design

*Date: 2026-03-01*

## Overview

Enforce PEP 723 inline script metadata across all Python tool scripts and switch the MCP server launcher from bare `python` to `uv run`. Update ARC's self-authoring behaviour so every Python script it generates is PEP 723 compliant from the start. Refactor documentation to match.

---

## 1. `src/arc/tools.py`

### 1a. `_SKILL_TEMPLATE`

Prepend a PEP 723 `# /// script` block before the existing boilerplate. The block includes:
- `requires-python = ">=3.11"`
- `dependencies` list — `"mcp"` always present, plus any caller-supplied extras

```
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mcp",
#   "some-extra-dep",
# ]
# ///
```

### 1b. `tool_write_skill` function

- Accept a new optional parameter `dependencies: list[str]` (default `[]`)
- Format the PEP 723 block from `["mcp"] + dependencies`, deduplicated
- Register the server in `mcp_servers.json` as:
  ```json
  { "command": "uv", "args": ["run", "tools/<name>_server.py"] }
  ```
  instead of `{ "command": "python", "args": ["tools/<name>_server.py"] }`

### 1c. `write_skill` tool schema

Add an optional `dependencies` property to the schema parameters:
```json
"dependencies": {
  "type": "array",
  "items": { "type": "string" },
  "description": "pip package names required by this skill (e.g. ['requests', 'pytz']). 'mcp' is always included automatically."
}
```

---

## 2. `data/mcp_servers.json`

Migrate all four existing server entries from `"command": "python"` to `"command": "uv"` with `"run"` prepended to args:

| Server | Old | New |
|--------|-----|-----|
| test | `python tools/test_server.py` | `uv run tools/test_server.py` |
| dice | `python tools/dice_server.py` | `uv run tools/dice_server.py` |
| docker | `python tools/docker_server.py` | `uv run tools/docker_server.py` |
| get_time | `python tools/get_time_server.py` | `uv run tools/get_time_server.py` |

---

## 3. Existing tool files

Add PEP 723 headers to each script immediately after the shebang line, with their actual runtime dependencies:

| File | Dependencies |
|------|-------------|
| `tools/test_server.py` | `["mcp"]` |
| `tools/dice_server.py` | `["mcp"]` |
| `tools/get_time_server.py` | `["mcp", "pytz"]` |
| `tools/docker_server.py` | `["mcp", "docker", "requests"]` |

---

## 4. `data/soul.md`

Add a **Python Writing Standard** section:

- All standalone Python scripts must include a PEP 723 `# /// script` metadata block
- Scripts are executed with `uv run <script.py>` — never bare `python`
- The `write_skill` tool's `dependencies` parameter must always be populated with required packages
- `mcp` is always included automatically by the template; do not list it manually

---

## 5. `docs/guide.md`

### Quick Start (Section 2)

Replace Step 3 (venv + pip) with:
- Prerequisite: `uv` installed (`pip install uv` or `brew install uv`)
- Tool scripts run via `uv run` — dependencies are resolved automatically from inline metadata
- The main arc package still installs from `requirements.txt` / `pyproject.toml` into the project environment

### MCP Skill Servers (Section 10)

Update any server launch command examples to show `uv run tools/<name>_server.py`.

### Self-Authoring Skills (Section 11)

- Document the PEP 723 format that all generated scripts include
- Document the new `dependencies` parameter on `write_skill`
- Show an example of what a generated file looks like with the metadata block

---

## Non-Goals

- The main ARC package (`src/arc/`) is a proper Python package — PEP 723 does not apply to it. It keeps `requirements.txt` / `pyproject.toml`.
- No changes to how ARC is launched (`python -m arc.main` remains unchanged).
