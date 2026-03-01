# Docker Execution MCP Server — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `tools/docker_server.py` MCP server that gives ARC sandboxed code execution via ephemeral Docker containers.

**Architecture:** A new MCP tool server registered in `data/mcp_servers.json` exposes four tools (`run_python`, `run_shell`, `run_node`, `run_in_image`). Each tool spins up an ephemeral Docker container, runs code or a command, captures stdout/stderr/exit code, destroys the container, and returns a formatted result string. The server follows the exact same MCP stdio pattern as existing `tools/dice_server.py`.

**Tech Stack:** `docker>=7.0.0` Python SDK, `pytest>=8.0`, `pytest-asyncio>=0.23`, existing MCP SDK (`mcp[cli]>=1.0.0`)

**Design doc:** `docs/plans/2026-02-28-docker-execution-design.md`

---

### Task 1: Add Dependencies

**Files:**
- Modify: `requirements.txt`
- Modify: `pyproject.toml`

**Step 1: Add docker SDK to requirements.txt**

After line 15 (`mcp[cli]>=1.0.0`), add:

```
docker>=7.0.0
```

**Step 2: Add docker SDK and dev deps to pyproject.toml**

In `pyproject.toml`, the `dependencies` list needs `docker>=7.0.0`. Also add dev extras and pytest config.

Replace the `[project]` section with:

```toml
[project]
name = "arc"
version = "0.1.0"
description = "ARC — a single-purpose autonomous AI agent framework"
requires-python = ">=3.11"
dependencies = [
    "python-telegram-bot>=21.0",
    "ollama>=0.4.0",
    "chromadb>=0.5.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "jinja2>=3.1.0",
    "apscheduler>=3.10.0",
    "python-dotenv>=1.0.0",
    "aiosqlite>=0.20.0",
    "python-multipart>=0.0.9",
    "mcp[cli]>=1.0.0",
    "docker>=7.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

Then append at the end of `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

**Step 3: Install dependencies**

```bash
pip install docker>=7.0.0 pytest pytest-asyncio
```

**Step 4: Verify**

```bash
python -c "import docker; print(docker.__version__)"
python -c "import pytest; print(pytest.__version__)"
```

Expected: version numbers printed, no errors.

**Step 5: Commit**

```bash
git add requirements.txt pyproject.toml
git commit -m "chore: add docker SDK and pytest dev dependencies"
```

---

### Task 2: Create Test Infrastructure

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create tests directory and files**

```bash
mkdir tests
touch tests/__init__.py
```

Create `tests/conftest.py`:

```python
"""Pytest configuration: add tools/ directory to sys.path so docker_server
can be imported directly (it lives in tools/, not in a Python package)."""

import sys
from pathlib import Path

# Allow `import docker_server` in tests
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
```

**Step 2: Verify pytest finds the tests directory**

```bash
pytest --collect-only
```

Expected: `no tests ran` (no test files yet) — but no errors.

**Step 3: Commit**

```bash
git add tests/
git commit -m "chore: set up pytest test infrastructure"
```

---

### Task 3: TDD — Tool Schema List

**Files:**
- Create: `tests/test_docker_server.py`
- Create: `tools/docker_server.py` (skeleton only)

**Step 1: Write the failing test**

Create `tests/test_docker_server.py`:

```python
"""Tests for the Docker execution MCP server."""

import pytest
from unittest.mock import MagicMock, patch
import docker.errors


# ---------------------------------------------------------------------------
# Tool schema tests
# ---------------------------------------------------------------------------

def test_list_tools_returns_four_tools():
    """list_tools returns exactly 4 Tool objects."""
    import asyncio
    import docker_server
    tools = asyncio.run(docker_server.list_tools())
    assert len(tools) == 4


def test_list_tools_has_correct_names():
    """list_tools includes run_python, run_shell, run_node, run_in_image."""
    import asyncio
    import docker_server
    tools = asyncio.run(docker_server.list_tools())
    names = {t.name for t in tools}
    assert names == {"run_python", "run_shell", "run_node", "run_in_image"}


def test_run_python_schema_requires_code():
    """run_python tool schema lists 'code' as required."""
    import asyncio
    import docker_server
    tools = asyncio.run(docker_server.list_tools())
    run_python = next(t for t in tools if t.name == "run_python")
    assert "code" in run_python.inputSchema["required"]


def test_run_in_image_schema_requires_image_and_command():
    """run_in_image tool schema lists 'image' and 'command' as required."""
    import asyncio
    import docker_server
    tools = asyncio.run(docker_server.list_tools())
    run_in_image = next(t for t in tools if t.name == "run_in_image")
    required = run_in_image.inputSchema["required"]
    assert "image" in required
    assert "command" in required
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_docker_server.py::test_list_tools_returns_four_tools -v
```

Expected: `ModuleNotFoundError: No module named 'docker_server'`

**Step 3: Create the docker_server.py skeleton with tool schemas**

Create `tools/docker_server.py`:

```python
#!/usr/bin/env python3
"""ARC Docker Execution MCP Server.

Provides sandboxed code execution via ephemeral Docker containers.
Four tools: run_python, run_shell, run_node, run_in_image.
"""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
import asyncio
import os
import tempfile
import time
from typing import Any

import docker
import docker.errors

server = Server("docker-server")

# ---------------------------------------------------------------------------
# Docker client (lazy init — allows import without Docker running)
# ---------------------------------------------------------------------------

_docker_client: docker.DockerClient | None = None


def _get_client() -> docker.DockerClient:
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_TOOLS = [
    Tool(
        name="run_python",
        description=(
            "Run Python code in an ephemeral Docker container. "
            "Returns stdout, stderr, and exit code."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source code to execute",
                },
                "packages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "pip packages to install before running (e.g. ['requests', 'pandas'])",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Kill container after N seconds (default 60)",
                    "default": 60,
                },
            },
            "required": ["code"],
        },
    ),
    Tool(
        name="run_shell",
        description=(
            "Run a Bash script in an ephemeral Ubuntu 24.04 Docker container. "
            "Returns stdout, stderr, and exit code."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "Bash script to execute",
                },
                "packages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "apt packages to install before running",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Kill container after N seconds (default 60)",
                    "default": 60,
                },
            },
            "required": ["script"],
        },
    ),
    Tool(
        name="run_node",
        description=(
            "Run JavaScript code in an ephemeral Node.js 22 Docker container. "
            "Returns stdout, stderr, and exit code."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "JavaScript source code to execute",
                },
                "packages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "npm packages to install before running",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Kill container after N seconds (default 60)",
                    "default": 60,
                },
            },
            "required": ["code"],
        },
    ),
    Tool(
        name="run_in_image",
        description=(
            "Run any command in any Docker image. "
            "Full flexibility to use any runtime (e.g. rust:1.82, golang:1.23, alpine:latest). "
            "Optionally pass code/script via the 'code' parameter — it is written to /tmp/script."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "image": {
                    "type": "string",
                    "description": "Docker image name (e.g. 'rust:1.82', 'golang:1.23')",
                },
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command and args (e.g. ['python3', '-c', 'print(42)'])",
                },
                "code": {
                    "type": "string",
                    "description": "Optional code written to /tmp/script inside the container",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Kill container after N seconds (default 60)",
                    "default": 60,
                },
            },
            "required": ["image", "command"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return _TOOLS


# Stubs — implemented in later tasks
def _run_container(image: str, command: list[str], code: str | None = None, timeout: int = 60) -> str:
    raise NotImplementedError

def _run_python(code: str, packages: list[str] | None = None, timeout_seconds: int = 60) -> str:
    raise NotImplementedError

def _run_shell(script: str, packages: list[str] | None = None, timeout_seconds: int = 60) -> str:
    raise NotImplementedError

def _run_node(code: str, packages: list[str] | None = None, timeout_seconds: int = 60) -> str:
    raise NotImplementedError

def _run_in_image(image: str, command: list[str], code: str | None = None, timeout_seconds: int = 60) -> str:
    raise NotImplementedError


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    raise NotImplementedError(f"call_tool not yet implemented: {name}")


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_docker_server.py::test_list_tools_returns_four_tools \
       tests/test_docker_server.py::test_list_tools_has_correct_names \
       tests/test_docker_server.py::test_run_python_schema_requires_code \
       tests/test_docker_server.py::test_run_in_image_schema_requires_image_and_command -v
```

Expected: 4 PASSED

**Step 5: Commit**

```bash
git add tools/docker_server.py tests/test_docker_server.py
git commit -m "feat: add docker_server.py skeleton with tool schemas and failing tests"
```

---

### Task 4: TDD — `_run_container` Success Path

**Files:**
- Modify: `tests/test_docker_server.py` (add tests)
- Modify: `tools/docker_server.py` (implement `_run_container`)

**Step 1: Add failing tests to `tests/test_docker_server.py`**

Append these tests:

```python
# ---------------------------------------------------------------------------
# _run_container tests
# ---------------------------------------------------------------------------

def _make_mock_container(exit_code: int = 0, stdout: bytes = b"hello\n", stderr: bytes = b""):
    """Build a mock docker container object."""
    container = MagicMock()
    container.wait.return_value = {"StatusCode": exit_code}
    container.logs.side_effect = lambda stdout=True, stderr=False: (
        stdout_bytes if stdout and not stderr else stderr_bytes
        if stderr and not stdout else b""
    )
    # Fix closure: capture values properly
    container.logs.side_effect = None

    def logs_side_effect(stdout=True, stderr=False):
        if stdout and not stderr:
            return stdout
        if stderr and not stdout:
            return stderr
        return b""

    container.logs.side_effect = logs_side_effect
    container.remove.return_value = None
    return container


def test_run_container_success_returns_formatted_result():
    """_run_container returns formatted result block with exit code and stdout."""
    import docker_server

    mock_container = _make_mock_container(exit_code=0, stdout=b"hello world\n", stderr=b"")
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    with patch.object(docker_server, "_get_client", return_value=mock_client):
        result = docker_server._run_container(
            image="python:3.12-slim",
            command=["python", "/tmp/script"],
            code="print('hello world')",
            timeout=30,
        )

    assert "=== Container Execution Result ===" in result
    assert "Exit code: 0" in result
    assert "hello world" in result


def test_run_container_includes_runtime():
    """_run_container result includes a Runtime line."""
    import docker_server

    mock_container = _make_mock_container()
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    with patch.object(docker_server, "_get_client", return_value=mock_client):
        result = docker_server._run_container(
            image="python:3.12-slim",
            command=["python", "/tmp/script"],
        )

    assert "Runtime:" in result
    assert "ms" in result


def test_run_container_mounts_code_as_readonly_tmpfile():
    """_run_container mounts code via a read-only temp file at /tmp/script."""
    import docker_server

    mock_container = _make_mock_container()
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    with patch.object(docker_server, "_get_client", return_value=mock_client):
        docker_server._run_container(
            image="python:3.12-slim",
            command=["python", "/tmp/script"],
            code="print('hi')",
        )

    call_kwargs = mock_client.containers.run.call_args
    volumes = call_kwargs.kwargs.get("volumes", call_kwargs[1].get("volumes", {}))
    assert len(volumes) == 1
    mount = list(volumes.values())[0]
    assert mount["bind"] == "/tmp/script"
    assert mount["mode"] == "ro"


def test_run_container_no_code_no_volumes():
    """_run_container passes empty volumes dict when code is None."""
    import docker_server

    mock_container = _make_mock_container()
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    with patch.object(docker_server, "_get_client", return_value=mock_client):
        docker_server._run_container(
            image="ubuntu:24.04",
            command=["echo", "hi"],
        )

    call_kwargs = mock_client.containers.run.call_args
    volumes = call_kwargs.kwargs.get("volumes", call_kwargs[1].get("volumes", {}))
    assert volumes == {}


def test_run_container_removes_container_on_success():
    """_run_container calls container.remove() after successful execution."""
    import docker_server

    mock_container = _make_mock_container()
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    with patch.object(docker_server, "_get_client", return_value=mock_client):
        docker_server._run_container(
            image="python:3.12-slim",
            command=["python", "-c", "pass"],
        )

    mock_container.remove.assert_called_once()


def test_run_container_nonzero_exit_code():
    """_run_container returns exit code 1 in result when code crashes."""
    import docker_server

    mock_container = _make_mock_container(exit_code=1, stderr=b"NameError: name 'x' is not defined\n")
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    with patch.object(docker_server, "_get_client", return_value=mock_client):
        result = docker_server._run_container(
            image="python:3.12-slim",
            command=["python", "/tmp/script"],
            code="print(x)",
        )

    assert "Exit code: 1" in result
    assert "NameError" in result
```

**Step 2: Run to verify tests fail**

```bash
pytest tests/test_docker_server.py -k "run_container" -v
```

Expected: `NotImplementedError` on all `_run_container` tests.

**Step 3: Implement `_run_container` in `tools/docker_server.py`**

Replace the `_run_container` stub with:

```python
def _run_container(
    image: str,
    command: list[str],
    code: str | None = None,
    timeout: int = 60,
) -> str:
    """Spin up an ephemeral container, run command, return formatted result."""
    start = time.monotonic()
    tmp_path: str | None = None
    container = None

    try:
        client = _get_client()

        volumes: dict[str, Any] = {}
        if code is not None:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".tmp", delete=False) as f:
                f.write(code)
                tmp_path = f.name
            volumes[tmp_path] = {"bind": "/tmp/script", "mode": "ro"}

        container = client.containers.run(
            image=image,
            command=command,
            volumes=volumes,
            network_mode="host",
            mem_limit="512m",
            cpu_quota=100_000,
            cpu_period=100_000,
            auto_remove=False,
            detach=True,
        )

        try:
            result = container.wait(timeout=timeout)
            exit_code = result["StatusCode"]
        except Exception:
            try:
                container.kill()
            except Exception:
                pass
            runtime_ms = int((time.monotonic() - start) * 1000)
            partial = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace").strip()
            return (
                f"=== Container Execution Result ===\n"
                f"Exit code: killed (timeout)\n"
                f"Runtime: {runtime_ms}ms\n\n"
                f"--- stdout ---\n{partial or '(empty)'}\n\n"
                f"--- stderr ---\n"
                f"⚠ Container killed after {timeout}s timeout"
            )

        runtime_ms = int((time.monotonic() - start) * 1000)
        stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace").strip()
        stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace").strip()

        return (
            f"=== Container Execution Result ===\n"
            f"Exit code: {exit_code}\n"
            f"Runtime: {runtime_ms}ms\n\n"
            f"--- stdout ---\n{stdout or '(empty)'}\n\n"
            f"--- stderr ---\n{stderr or '(empty)'}"
        )

    except docker.errors.ImageNotFound:
        return f"=== Container Execution Result ===\nError: Image '{image}' not found."
    except docker.errors.DockerException as e:
        err = str(e)
        if any(k in err for k in ("ConnectionRefused", "FileNotFoundError", "Error while fetching server")):
            return (
                "=== Container Execution Result ===\n"
                "Error: Docker daemon is not accessible. Is Docker running?"
            )
        return f"=== Container Execution Result ===\nError: {err}"
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_docker_server.py -k "run_container" -v
```

Expected: all `run_container` tests PASSED.

**Step 5: Commit**

```bash
git add tools/docker_server.py tests/test_docker_server.py
git commit -m "feat: implement _run_container core helper with TDD"
```

---

### Task 5: TDD — Error Paths for `_run_container`

**Files:**
- Modify: `tests/test_docker_server.py` (add error path tests)

**Step 1: Add failing tests**

Append to `tests/test_docker_server.py`:

```python
def test_run_container_timeout_kills_and_reports():
    """_run_container kills container and returns timeout message on timeout."""
    import docker_server

    mock_container = MagicMock()
    mock_container.wait.side_effect = Exception("Read timed out")
    mock_container.logs.side_effect = lambda stdout=True, stderr=False: b"partial" if stdout else b""

    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    with patch.object(docker_server, "_get_client", return_value=mock_client):
        result = docker_server._run_container(
            image="python:3.12-slim",
            command=["python", "/tmp/script"],
            code="import time; time.sleep(999)",
            timeout=1,
        )

    assert "killed" in result.lower()
    assert "timeout" in result.lower()
    mock_container.kill.assert_called_once()


def test_run_container_docker_not_running():
    """_run_container returns helpful message when Docker daemon is unreachable."""
    import docker_server

    with patch.object(
        docker_server,
        "_get_client",
        side_effect=docker.errors.DockerException("Error while fetching server API version"),
    ):
        result = docker_server._run_container(
            image="python:3.12-slim",
            command=["python", "-c", "pass"],
        )

    assert "Docker daemon is not accessible" in result
    assert "Is Docker running?" in result


def test_run_container_image_not_found():
    """_run_container returns clear message when Docker image is not found."""
    import docker_server

    mock_client = MagicMock()
    mock_client.containers.run.side_effect = docker.errors.ImageNotFound("no such image")

    with patch.object(docker_server, "_get_client", return_value=mock_client):
        result = docker_server._run_container(
            image="thisimage:doesnotexist",
            command=["python", "-c", "pass"],
        )

    assert "not found" in result.lower()
    assert "thisimage:doesnotexist" in result


def test_run_container_cleans_up_tmpfile_on_success():
    """_run_container deletes the temp file after container exits."""
    import docker_server

    created_paths = []
    original_mktemp = tempfile.NamedTemporaryFile

    def capturing_mktemp(**kwargs):
        f = original_mktemp(**kwargs)
        created_paths.append(f.name)
        return f

    mock_container = _make_mock_container()
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    with patch.object(docker_server, "_get_client", return_value=mock_client):
        with patch("tempfile.NamedTemporaryFile", side_effect=capturing_mktemp):
            docker_server._run_container(
                image="python:3.12-slim",
                command=["python", "/tmp/script"],
                code="print('hi')",
            )

    # Temp file should have been deleted
    for path in created_paths:
        assert not os.path.exists(path), f"Temp file {path} was not cleaned up"
```

**Step 2: Run to verify they pass** (they should already pass from Task 4's implementation)

```bash
pytest tests/test_docker_server.py -k "timeout or docker_not or image_not or cleans_up" -v
```

Expected: all PASSED (the `_run_container` implementation from Task 4 already handles these).

Note: If `test_run_container_cleans_up_tmpfile_on_success` fails, the issue is the patch path. Use `patch("docker_server.tempfile.NamedTemporaryFile", ...)` instead.

**Step 3: Commit**

```bash
git add tests/test_docker_server.py
git commit -m "test: add error path tests for _run_container"
```

---

### Task 6: TDD — `_run_python` Handler

**Files:**
- Modify: `tests/test_docker_server.py` (add handler tests)
- Modify: `tools/docker_server.py` (implement `_run_python`)

**Step 1: Add failing tests**

Append to `tests/test_docker_server.py`:

```python
# ---------------------------------------------------------------------------
# Handler tests
# ---------------------------------------------------------------------------

def test_run_python_uses_python_image():
    """_run_python calls _run_container with python:3.12-slim image."""
    import docker_server

    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_python(code="print('hi')")

    call_kwargs = mock_run.call_args.kwargs or mock_run.call_args[1]
    assert call_kwargs.get("image") == "python:3.12-slim"


def test_run_python_passes_code_through():
    """_run_python passes the code to _run_container (possibly wrapped)."""
    import docker_server

    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_python(code="print('hello')")

    call_kwargs = mock_run.call_args.kwargs or mock_run.call_args[1]
    assert "print('hello')" in call_kwargs.get("code", "")


def test_run_python_no_packages_no_wrapper():
    """_run_python without packages passes code unchanged (no pip wrapper)."""
    import docker_server

    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_python(code="x = 1")

    call_kwargs = mock_run.call_args.kwargs or mock_run.call_args[1]
    assert "pip" not in call_kwargs.get("code", "")


def test_run_python_with_packages_prepends_pip_install():
    """_run_python prepends a pip install block when packages are provided."""
    import docker_server

    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_python(code="import requests", packages=["requests", "pandas"])

    call_kwargs = mock_run.call_args.kwargs or mock_run.call_args[1]
    code = call_kwargs.get("code", "")
    assert "pip" in code
    assert "requests" in code
    assert "pandas" in code
    assert "import requests" in code  # original code still present


def test_run_python_respects_timeout():
    """_run_python passes timeout_seconds as timeout to _run_container."""
    import docker_server

    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_python(code="pass", timeout_seconds=120)

    call_kwargs = mock_run.call_args.kwargs or mock_run.call_args[1]
    assert call_kwargs.get("timeout") == 120
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_docker_server.py -k "run_python" -v
```

Expected: `NotImplementedError` on all `_run_python` tests.

**Step 3: Implement `_run_python` in `tools/docker_server.py`**

Replace the `_run_python` stub with:

```python
def _run_python(
    code: str,
    packages: list[str] | None = None,
    timeout_seconds: int = 60,
) -> str:
    if packages:
        pkg_args = ", ".join(repr(p) for p in packages)
        script = (
            f"import subprocess\n"
            f"subprocess.run(['pip', 'install', '-q', {pkg_args}], check=True)\n"
            f"\n{code}"
        )
    else:
        script = code

    return _run_container(
        image="python:3.12-slim",
        command=["python", "/tmp/script"],
        code=script,
        timeout=timeout_seconds,
    )
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_docker_server.py -k "run_python" -v
```

Expected: all PASSED.

**Step 5: Commit**

```bash
git add tools/docker_server.py tests/test_docker_server.py
git commit -m "feat: implement run_python handler with TDD"
```

---

### Task 7: TDD — `_run_shell` Handler

**Files:**
- Modify: `tests/test_docker_server.py`
- Modify: `tools/docker_server.py`

**Step 1: Add failing tests**

Append to `tests/test_docker_server.py`:

```python
def test_run_shell_uses_ubuntu_image():
    """_run_shell calls _run_container with ubuntu:24.04 image."""
    import docker_server

    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_shell(script="echo hi")

    call_kwargs = mock_run.call_args.kwargs or mock_run.call_args[1]
    assert call_kwargs.get("image") == "ubuntu:24.04"


def test_run_shell_uses_bash_command():
    """_run_shell runs the script with bash."""
    import docker_server

    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_shell(script="echo hi")

    call_kwargs = mock_run.call_args.kwargs or mock_run.call_args[1]
    command = call_kwargs.get("command", [])
    assert command[0] == "bash"


def test_run_shell_with_packages_prepends_apt_install():
    """_run_shell prepends apt-get install when packages provided."""
    import docker_server

    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_shell(script="curl example.com", packages=["curl"])

    call_kwargs = mock_run.call_args.kwargs or mock_run.call_args[1]
    code = call_kwargs.get("code", "")
    assert "apt-get" in code
    assert "curl" in code
    assert "curl example.com" in code


def test_run_shell_no_packages_no_apt():
    """_run_shell without packages does not include apt-get."""
    import docker_server

    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_shell(script="ls -la")

    call_kwargs = mock_run.call_args.kwargs or mock_run.call_args[1]
    assert "apt-get" not in call_kwargs.get("code", "")
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_docker_server.py -k "run_shell" -v
```

Expected: `NotImplementedError`

**Step 3: Implement `_run_shell` in `tools/docker_server.py`**

Replace the `_run_shell` stub with:

```python
def _run_shell(
    script: str,
    packages: list[str] | None = None,
    timeout_seconds: int = 60,
) -> str:
    if packages:
        pkg_str = " ".join(packages)
        full_script = f"apt-get update -q && apt-get install -y -q {pkg_str}\n{script}"
    else:
        full_script = script

    return _run_container(
        image="ubuntu:24.04",
        command=["bash", "/tmp/script"],
        code=full_script,
        timeout=timeout_seconds,
    )
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_docker_server.py -k "run_shell" -v
```

Expected: all PASSED.

**Step 5: Commit**

```bash
git add tools/docker_server.py tests/test_docker_server.py
git commit -m "feat: implement run_shell handler with TDD"
```

---

### Task 8: TDD — `_run_node` Handler

**Files:**
- Modify: `tests/test_docker_server.py`
- Modify: `tools/docker_server.py`

**Step 1: Add failing tests**

Append to `tests/test_docker_server.py`:

```python
def test_run_node_uses_node_image():
    """_run_node calls _run_container with node:22-slim image."""
    import docker_server

    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_node(code="console.log('hi')")

    call_kwargs = mock_run.call_args.kwargs or mock_run.call_args[1]
    assert call_kwargs.get("image") == "node:22-slim"


def test_run_node_with_packages_prepends_npm_install():
    """_run_node prepends npm install when packages provided."""
    import docker_server

    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_node(code="const _ = require('lodash')", packages=["lodash"])

    call_kwargs = mock_run.call_args.kwargs or mock_run.call_args[1]
    code = call_kwargs.get("code", "")
    assert "npm" in code
    assert "lodash" in code
    assert "require('lodash')" in code


def test_run_node_no_packages_no_npm():
    """_run_node without packages does not include npm."""
    import docker_server

    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_node(code="console.log(42)")

    call_kwargs = mock_run.call_args.kwargs or mock_run.call_args[1]
    assert "npm" not in call_kwargs.get("code", "")
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_docker_server.py -k "run_node" -v
```

Expected: `NotImplementedError`

**Step 3: Implement `_run_node` in `tools/docker_server.py`**

Replace the `_run_node` stub with:

```python
def _run_node(
    code: str,
    packages: list[str] | None = None,
    timeout_seconds: int = 60,
) -> str:
    if packages:
        pkg_str = " ".join(packages)
        script = (
            f"const {{ execSync }} = require('child_process');\n"
            f"execSync('npm install -g {pkg_str}', {{ stdio: 'pipe' }});\n"
            f"\n{code}"
        )
    else:
        script = code

    return _run_container(
        image="node:22-slim",
        command=["node", "/tmp/script"],
        code=script,
        timeout=timeout_seconds,
    )
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_docker_server.py -k "run_node" -v
```

Expected: all PASSED.

**Step 5: Commit**

```bash
git add tools/docker_server.py tests/test_docker_server.py
git commit -m "feat: implement run_node handler with TDD"
```

---

### Task 9: TDD — `_run_in_image` and `call_tool` Dispatch

**Files:**
- Modify: `tests/test_docker_server.py`
- Modify: `tools/docker_server.py`

**Step 1: Add failing tests**

Append to `tests/test_docker_server.py`:

```python
def test_run_in_image_passes_image_and_command():
    """_run_in_image passes image, command, code, and timeout to _run_container."""
    import docker_server

    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_in_image(
            image="rust:1.82",
            command=["rustc", "--version"],
            timeout_seconds=45,
        )

    call_kwargs = mock_run.call_args.kwargs or mock_run.call_args[1]
    assert call_kwargs.get("image") == "rust:1.82"
    assert call_kwargs.get("command") == ["rustc", "--version"]
    assert call_kwargs.get("timeout") == 45


def test_run_in_image_passes_code():
    """_run_in_image forwards code parameter to _run_container."""
    import docker_server

    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_in_image(
            image="golang:1.23",
            command=["go", "run", "/tmp/script"],
            code="package main\nfunc main() {}",
        )

    call_kwargs = mock_run.call_args.kwargs or mock_run.call_args[1]
    assert "package main" in (call_kwargs.get("code") or "")


async def test_call_tool_dispatches_run_python():
    """call_tool routes 'run_python' to _run_python and wraps result."""
    import docker_server

    with patch.object(docker_server, "_run_python", return_value="python result") as mock_handler:
        result = await docker_server.call_tool("run_python", {"code": "print('hi')"})

    mock_handler.assert_called_once_with(code="print('hi')")
    assert len(result) == 1
    assert result[0].text == "python result"


async def test_call_tool_dispatches_run_shell():
    """call_tool routes 'run_shell' to _run_shell."""
    import docker_server

    with patch.object(docker_server, "_run_shell", return_value="shell result"):
        result = await docker_server.call_tool("run_shell", {"script": "echo hi"})

    assert result[0].text == "shell result"


async def test_call_tool_dispatches_run_node():
    """call_tool routes 'run_node' to _run_node."""
    import docker_server

    with patch.object(docker_server, "_run_node", return_value="node result"):
        result = await docker_server.call_tool("run_node", {"code": "console.log('hi')"})

    assert result[0].text == "node result"


async def test_call_tool_dispatches_run_in_image():
    """call_tool routes 'run_in_image' to _run_in_image."""
    import docker_server

    with patch.object(docker_server, "_run_in_image", return_value="image result"):
        result = await docker_server.call_tool(
            "run_in_image", {"image": "rust:1.82", "command": ["rustc", "--version"]}
        )

    assert result[0].text == "image result"


async def test_call_tool_raises_for_unknown_tool():
    """call_tool raises ValueError for unknown tool names."""
    import docker_server

    with pytest.raises(ValueError, match="Unknown tool"):
        await docker_server.call_tool("nonexistent_tool", {})
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_docker_server.py -k "run_in_image or call_tool" -v
```

Expected: `NotImplementedError` or failures

**Step 3: Implement `_run_in_image` and `call_tool` in `tools/docker_server.py`**

Replace the `_run_in_image` stub:

```python
def _run_in_image(
    image: str,
    command: list[str],
    code: str | None = None,
    timeout_seconds: int = 60,
) -> str:
    return _run_container(image=image, command=command, code=code, timeout=timeout_seconds)
```

Replace the `call_tool` decorator function:

```python
@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    handlers = {
        "run_python": _run_python,
        "run_shell": _run_shell,
        "run_node": _run_node,
        "run_in_image": _run_in_image,
    }
    handler = handlers.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    result = handler(**arguments)
    return [TextContent(type="text", text=result)]
```

**Step 4: Run all tests**

```bash
pytest tests/test_docker_server.py -v
```

Expected: all tests PASSED.

**Step 5: Commit**

```bash
git add tools/docker_server.py tests/test_docker_server.py
git commit -m "feat: implement run_in_image and call_tool dispatch, all tests passing"
```

---

### Task 10: Register Docker Server in `mcp_servers.json`

**Files:**
- Modify: `data/mcp_servers.json`

**Step 1: Add docker server entry**

Edit `data/mcp_servers.json` to add the docker server:

```json
{
  "servers": {
    "test": {
      "command": "python",
      "args": [
        "tools/test_server.py"
      ]
    },
    "dice": {
      "command": "python",
      "args": [
        "tools/dice_server.py"
      ]
    },
    "docker": {
      "command": "python",
      "args": [
        "tools/docker_server.py"
      ]
    }
  }
}
```

**Step 2: Commit**

```bash
git add data/mcp_servers.json
git commit -m "feat: register docker MCP server in mcp_servers.json"
```

---

### Task 11: Smoke Test — Verify Server Starts

**Step 1: Verify docker_server.py is importable and the server object exists**

```bash
python -c "import sys; sys.path.insert(0, 'tools'); import docker_server; print('Server:', docker_server.server.name)"
```

Expected: `Server: docker-server`

**Step 2: Run the full test suite one final time**

```bash
pytest tests/ -v
```

Expected: all tests PASSED, none skipped.

**Step 3: Verify Docker is running and test a quick pull** (requires Docker Desktop or Docker Engine)

```bash
docker pull python:3.12-slim
```

Expected: image pulled or already cached.

**Step 4: Test the server can be started as a subprocess** (quick process test — press Ctrl+C after a second)

```bash
timeout 3 python tools/docker_server.py || true
```

Expected: process starts and exits cleanly (no import errors, no crash on startup).

**Step 5: Final commit**

```bash
git add .
git commit -m "feat: Docker execution MCP server complete — run_python, run_shell, run_node, run_in_image"
```

---

## Summary

After all tasks:

- `tools/docker_server.py` — MCP server with 4 tools backed by the docker Python SDK
- `tests/test_docker_server.py` — full TDD test suite (unit tests with mocked docker)
- `data/mcp_servers.json` — docker server registered, ARC discovers it at startup
- `requirements.txt` / `pyproject.toml` — `docker>=7.0.0` added

ARC can now ask it to `run_python`, `run_shell`, `run_node`, or `run_in_image` and get back stdout/stderr/exit code from an ephemeral Docker container.
