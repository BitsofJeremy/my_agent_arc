"""Tests for the Docker execution MCP server."""

import pytest
from unittest.mock import MagicMock, patch
import docker.errors
import os


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
