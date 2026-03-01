# PEP 723 + uv run Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enforce PEP 723 inline script metadata across all Python MCP tool servers, switch launch command to `uv run`, make ARC always generate PEP 723-compliant scripts, and update all docs.

**Architecture:** Five independent change areas — the skill template/tool (core logic), the JSON config, the four existing tool files, ARC's soul, and the user guide. No new abstractions needed; changes are additive (new template section, new optional parameter, header insertions, doc rewrites).

**Tech Stack:** Python 3.11+, uv, mcp SDK, standard library only for the tool changes.

**Design doc:** `docs/plans/2026-03-01-pep723-uv-run-design.md`

---

## Task 1: Update `_SKILL_TEMPLATE` in `src/arc/tools.py`

**Files:**
- Modify: `src/arc/tools.py:263-283`

The template must gain a PEP 723 block. The block sits between the shebang and the ARC marker comment. It uses a `$deps` placeholder that `tool_write_skill` will fill.

**Step 1: Write a failing test for the new template output**

Create `tests/test_tools_write_skill.py`:

```python
"""Tests for write_skill template and PEP 723 compliance."""
import pytest
from string import Template
from arc.tools import _SKILL_TEMPLATE, _ARC_GENERATED_MARKER


def test_template_contains_pep723_block():
    rendered = _SKILL_TEMPLATE.substitute(
        marker=_ARC_GENERATED_MARKER,
        name="test_skill",
        description="A test skill",
        deps='#   "mcp",\n',
        code="# skill code here",
    )
    assert "# /// script" in rendered
    assert '# requires-python = ">=3.11"' in rendered
    assert "# dependencies = [" in rendered
    assert '#   "mcp"' in rendered
    assert "# ///" in rendered


def test_template_pep723_block_before_marker():
    rendered = _SKILL_TEMPLATE.substitute(
        marker=_ARC_GENERATED_MARKER,
        name="test_skill",
        description="A test skill",
        deps='#   "mcp",\n',
        code="# skill code here",
    )
    script_pos = rendered.index("# /// script")
    marker_pos = rendered.index(_ARC_GENERATED_MARKER)
    assert script_pos < marker_pos


def test_template_extra_dependencies_included():
    rendered = _SKILL_TEMPLATE.substitute(
        marker=_ARC_GENERATED_MARKER,
        name="test_skill",
        description="A test skill",
        deps='#   "mcp",\n#   "requests",\n',
        code="# skill code here",
    )
    assert '#   "requests"' in rendered
```

**Step 2: Run tests to confirm they fail**

```bash
cd /Users/jeremy/Documents/current_projects/my_agent_arc
python -m pytest tests/test_tools_write_skill.py -v
```

Expected: FAIL — `KeyError: 'deps'` (placeholder not in template yet).

**Step 3: Update `_SKILL_TEMPLATE`**

In `src/arc/tools.py`, replace the `_SKILL_TEMPLATE` definition (lines 263–283):

```python
_SKILL_TEMPLATE = Template('''\
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
$deps# ]
# ///
$marker: $name
# $description

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
import asyncio

server = Server("$name")

$code

async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
''')
```

**Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_tools_write_skill.py::test_template_contains_pep723_block tests/test_tools_write_skill.py::test_template_pep723_block_before_marker tests/test_tools_write_skill.py::test_template_extra_dependencies_included -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_tools_write_skill.py src/arc/tools.py
git commit -m "feat: add PEP 723 block to skill template"
```

---

## Task 2: Update `tool_write_skill` to accept `dependencies` and use `uv run`

**Files:**
- Modify: `src/arc/tools.py` — `write_skill` schema (~line 94–131) and `tool_write_skill` function (~line 313–376)
- Test: `tests/test_tools_write_skill.py`

**Step 1: Write failing tests**

Append to `tests/test_tools_write_skill.py`:

```python
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.mark.asyncio
async def test_write_skill_uses_uv_run_in_config(tmp_path):
    """Generated mcp_servers.json entry must use uv run, not python."""
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text('{"servers": {}}')
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    with (
        patch("arc.tools._MCP_CONFIG_PATH", config_path),
        patch("arc.tools._TOOLS_DIR", tools_dir),
        patch("arc.tools.reload_mcp_manager", new_callable=AsyncMock, return_value=None),
    ):
        from arc.tools import tool_write_skill
        await tool_write_skill(
            name="myskill",
            description="does stuff",
            code="# empty",
        )

    config = json.loads(config_path.read_text())
    entry = config["servers"]["myskill"]
    assert entry["command"] == "uv"
    assert entry["args"] == ["run", "tools/myskill_server.py"]


@pytest.mark.asyncio
async def test_write_skill_default_deps_in_file(tmp_path):
    """Generated file must contain mcp in the PEP 723 block when no deps given."""
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text('{"servers": {}}')
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    with (
        patch("arc.tools._MCP_CONFIG_PATH", config_path),
        patch("arc.tools._TOOLS_DIR", tools_dir),
        patch("arc.tools.reload_mcp_manager", new_callable=AsyncMock, return_value=None),
    ):
        from arc.tools import tool_write_skill
        await tool_write_skill(
            name="myskill",
            description="does stuff",
            code="# empty",
        )

    content = (tools_dir / "myskill_server.py").read_text()
    assert '#   "mcp"' in content


@pytest.mark.asyncio
async def test_write_skill_extra_deps_in_file(tmp_path):
    """Extra dependencies must appear in the PEP 723 block."""
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text('{"servers": {}}')
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    with (
        patch("arc.tools._MCP_CONFIG_PATH", config_path),
        patch("arc.tools._TOOLS_DIR", tools_dir),
        patch("arc.tools.reload_mcp_manager", new_callable=AsyncMock, return_value=None),
    ):
        from arc.tools import tool_write_skill
        await tool_write_skill(
            name="myskill",
            description="does stuff",
            code="import requests",
            dependencies=["requests", "pytz"],
        )

    content = (tools_dir / "myskill_server.py").read_text()
    assert '#   "requests"' in content
    assert '#   "pytz"' in content
```

**Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_tools_write_skill.py -v -k "uv_run or default_deps or extra_deps"
```

Expected: FAIL — `tool_write_skill` still writes `python` command, no `dependencies` param.

**Step 3: Update `write_skill` schema**

In `src/arc/tools.py`, inside the `write_skill` schema's `"properties"` dict (after the `"code"` property), add:

```python
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "pip package names required by this skill "
                            "(e.g. ['requests', 'pytz']). "
                            "'mcp' is always included automatically — do not list it."
                        ),
                    },
```

**Step 4: Update `tool_write_skill` function signature and body**

Change the function signature from:
```python
async def tool_write_skill(name: str, description: str, code: str) -> str:
```
to:
```python
async def tool_write_skill(
    name: str, description: str, code: str, dependencies: list[str] | None = None
) -> str:
```

Inside the function, after the `code` cleanup block and before `_TOOLS_DIR.mkdir(...)`, add deps formatting:

```python
    # Build PEP 723 deps block — mcp always first, then caller extras (deduplicated).
    all_deps = ["mcp"] + [d for d in (dependencies or []) if d != "mcp"]
    deps_block = "".join(f'#   "{dep}",\n' for dep in all_deps)
```

Update the `_SKILL_TEMPLATE.substitute(...)` call to pass `deps=deps_block`:

```python
    source = _SKILL_TEMPLATE.substitute(
        marker=_ARC_GENERATED_MARKER,
        name=name,
        description=description,
        deps=deps_block,
        code=code,
    )
```

Update the config entry in `tool_write_skill` from:
```python
    config.setdefault("servers", {})[name] = {
        "command": "python",
        "args": [f"tools/{name}_server.py"],
    }
```
to:
```python
    config.setdefault("servers", {})[name] = {
        "command": "uv",
        "args": ["run", f"tools/{name}_server.py"],
    }
```

**Step 5: Run all new tests**

```bash
python -m pytest tests/test_tools_write_skill.py -v
```

Expected: All PASS.

**Step 6: Run existing test suite to check for regressions**

```bash
python -m pytest tests/ -v --ignore=tests/test_docker_server.py
```

Expected: All PASS (docker tests require Docker running — skip for now).

**Step 7: Commit**

```bash
git add src/arc/tools.py tests/test_tools_write_skill.py
git commit -m "feat: add dependencies param to write_skill, switch to uv run"
```

---

## Task 3: Migrate `data/mcp_servers.json`

**Files:**
- Modify: `data/mcp_servers.json`

No tests needed — this is a config file change; correctness is verified when ARC starts.

**Step 1: Update all four server entries**

Replace the file contents with:

```json
{
  "servers": {
    "test": {
      "command": "uv",
      "args": [
        "run",
        "tools/test_server.py"
      ]
    },
    "dice": {
      "command": "uv",
      "args": [
        "run",
        "tools/dice_server.py"
      ]
    },
    "docker": {
      "command": "uv",
      "args": [
        "run",
        "tools/docker_server.py"
      ],
      "env": {
        "DOCKER_HOST": "unix:///Users/jeremy/.docker/run/docker.sock"
      }
    },
    "get_time": {
      "command": "uv",
      "args": [
        "run",
        "tools/get_time_server.py"
      ]
    }
  }
}
```

**Step 2: Commit**

```bash
git add data/mcp_servers.json
git commit -m "chore: switch mcp server launcher from python to uv run"
```

---

## Task 4: Add PEP 723 headers to existing tool files

**Files:**
- Modify: `tools/test_server.py`
- Modify: `tools/dice_server.py`
- Modify: `tools/get_time_server.py`
- Modify: `tools/docker_server.py`

No new tests needed — headers are inert to Python; correctness is `uv run` launching successfully.

**Step 1: Add PEP 723 header to `tools/test_server.py`**

Insert after `#!/usr/bin/env python3` (line 1), before the docstring:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mcp",
# ]
# ///
```

Also update the inline run comment in the docstring from:
```
Run standalone:  python tools/test_server.py
```
to:
```
Run standalone:  uv run tools/test_server.py
```

**Step 2: Add PEP 723 header to `tools/dice_server.py`**

Insert after `#!/usr/bin/env python3` (line 1):

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mcp",
# ]
# ///
```

**Step 3: Add PEP 723 header to `tools/get_time_server.py`**

Insert after `#!/usr/bin/env python3` (line 1):

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mcp",
#   "pytz",
# ]
# ///
```

**Step 4: Add PEP 723 header to `tools/docker_server.py`**

Insert after `#!/usr/bin/env python3` (line 1):

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mcp",
#   "docker",
#   "requests",
# ]
# ///
```

**Step 5: Commit**

```bash
git add tools/test_server.py tools/dice_server.py tools/get_time_server.py tools/docker_server.py
git commit -m "chore: add PEP 723 inline metadata headers to tool scripts"
```

---

## Task 5: Update `data/soul.md`

**Files:**
- Modify: `data/soul.md`

**Step 1: Add Python Writing Standard section**

After the `## Code Execution` section and before `## Continuity`, insert a new section:

```markdown
## Python Writing Standard

When you write any standalone Python script — including all skill servers — you must follow PEP 723 inline script metadata format. Every script begins with:

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mcp",
#   "other-package",
# ]
# ///
```

Scripts are executed with `uv run <script.py>` — never with bare `python`. When calling `write_skill`, always populate the `dependencies` parameter with any packages your tool code imports beyond the standard library. `mcp` is always included automatically — do not list it.

This is not optional. PEP 723 compliance is the standard for all Python in this system.
```

**Step 2: Commit**

```bash
git add data/soul.md
git commit -m "feat: add PEP 723 Python writing standard to soul.md"
```

---

## Task 6: Update `docs/guide.md`

**Files:**
- Modify: `docs/guide.md`

This is the largest doc change. Three sections need updating.

**Step 1: Update Quick Start — Step 3**

Find the Step 3 block (currently `python3 -m venv .venv` / `pip install -r requirements.txt`). Replace it with:

```markdown
### Step 3: Install uv (if not already installed)

[uv](https://docs.astral.sh/uv/) manages dependencies for the MCP tool scripts via PEP 723 inline metadata.

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# or via Homebrew
brew install uv

# or via pip
pip install uv
```

Then install ARC's own dependencies into a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Alternatively, install in editable mode (useful if you plan to modify ARC):

```bash
pip install -e .
```

MCP tool scripts in `tools/` do not need manual installation — `uv run` resolves their dependencies automatically from the inline metadata at first run.
```

**Step 2: Update Section 10 — MCP Skill Servers config example**

Find the Python MCP server example (around line 611–619 of the saved output):

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

Replace with:

```json
{
  "servers": {
    "test": {
      "command": "uv",
      "args": ["run", "tools/test_server.py"]
    }
  }
}
```

Also update the `"Writing your own MCP server"` section's `mcp_servers.json` snippet from `"command": "python"` to `"command": "uv"` with `"args": ["run", "tools/my_server.py"]`.

Update the code example in `"Writing your own MCP server"` to include the PEP 723 block at the top:

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mcp",
# ]
# ///
"""My custom MCP tool server."""
# ... rest unchanged ...
```

Also update both Docker server JSON config examples in Section 12 (macOS and Linux) from `"command": "python"` to `"command": "uv"` with `"run"` prepended to args.

**Step 3: Update Section 11 — Self-Authoring Skills**

Update the `write_skill` call description: change `write_skill(name, description, code)` to `write_skill(name, description, code, dependencies)`.

Add a `dependencies` row to any parameter table or prose description.

Replace the "Generated file structure" example with the PEP 723-compliant version:

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mcp",
#   "pytz",
# ]
# ///
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

**Step 4: Commit**

```bash
git add docs/guide.md
git commit -m "docs: update guide for PEP 723 and uv run"
```

---

## Verification

After all tasks are complete:

```bash
# 1. Run the full test suite
python -m pytest tests/ -v --ignore=tests/test_docker_server.py

# 2. Smoke-test uv run on a tool directly
uv run tools/test_server.py --help 2>&1 || echo "uv run resolved deps OK (stdio server exits cleanly)"

# 3. Check that the template no longer generates bare 'python' anywhere
grep -r '"command": "python"' data/mcp_servers.json && echo "FAIL: python still present" || echo "OK"
```
