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
import shlex
import tempfile
import time
from typing import Any

import docker
import docker.errors
import requests.exceptions

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


def _reset_client() -> None:
    """Discard the cached Docker client so the next call reconnects fresh."""
    global _docker_client
    _docker_client = None


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
            network_mode="host",  # Intentional: moderate isolation allows pip/npm/apt installs
            mem_limit="512m",
            cpu_quota=100_000,
            cpu_period=100_000,
            pids_limit=128,
            auto_remove=False,
            detach=True,
        )

        try:
            result = container.wait(timeout=timeout)
            exit_code = result["StatusCode"]
        except requests.exceptions.ReadTimeout:
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
                f"Container killed after {timeout}s timeout"
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
        if any(k in err for k in ("Connection aborted", "Connection refused", "FileNotFoundError", "Error while fetching server")):
            _reset_client()  # Force reconnect on next call
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


def _run_shell(
    script: str,
    packages: list[str] | None = None,
    timeout_seconds: int = 60,
) -> str:
    if packages:
        pkg_str = " ".join(shlex.quote(p) for p in packages)
        full_script = f"apt-get update -q && apt-get install -y -q {pkg_str}\n{script}"
    else:
        full_script = script

    return _run_container(
        image="ubuntu:24.04",
        command=["bash", "/tmp/script"],
        code=full_script,
        timeout=timeout_seconds,
    )


def _run_node(
    code: str,
    packages: list[str] | None = None,
    timeout_seconds: int = 60,
) -> str:
    if packages:
        pkg_str = " ".join(shlex.quote(p) for p in packages)
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


def _run_in_image(
    image: str,
    command: list[str],
    code: str | None = None,
    timeout_seconds: int = 60,
) -> str:
    return _run_container(image=image, command=command, code=code, timeout=timeout_seconds)


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

    # Overall wall-clock timeout: user timeout + 30s buffer for Docker overhead.
    # Guards against client.containers.run() hanging (e.g. slow image pull or
    # Docker daemon unresponsive).
    #
    # Uses asyncio.wait() NOT asyncio.wait_for(): in Python 3.12+ wait_for
    # blocks until the cancelled coroutine fully completes before raising
    # TimeoutError, which defeats the purpose when the inner thread is stuck.
    # asyncio.wait() returns immediately after the timeout, leaving the thread
    # to finish in the background (acceptable — it will eventually clean itself
    # up or expire when the process exits).
    user_timeout = int(arguments.get("timeout_seconds", 60))
    total_timeout = user_timeout + 30

    task = asyncio.create_task(asyncio.to_thread(handler, **arguments))
    done, _ = await asyncio.wait({task}, timeout=total_timeout)

    if not done:
        _reset_client()
        result = (
            f"=== Container Execution Result ===\n"
            f"Error: Operation timed out after {total_timeout}s. "
            f"Docker may be unresponsive or the image pull is taking too long."
        )
    else:
        result = task.result()
    return [TextContent(type="text", text=result)]


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
