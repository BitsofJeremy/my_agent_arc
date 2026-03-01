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
