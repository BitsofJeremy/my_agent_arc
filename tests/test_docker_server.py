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


# ---------------------------------------------------------------------------
# Helper for tests
# ---------------------------------------------------------------------------

def _make_mock_container(exit_code: int = 0, stdout: bytes = b"hello\n", stderr: bytes = b""):
    """Build a mock docker container that behaves like the real SDK response."""
    container = MagicMock()
    container.wait.return_value = {"StatusCode": exit_code}

    def logs_side_effect(stdout=True, stderr=False):
        if stdout and not stderr:
            return b"hello\n"
        if stderr and not stdout:
            return b""
        return b""

    container.logs.side_effect = logs_side_effect
    container.remove.return_value = None
    return container


# ---------------------------------------------------------------------------
# _run_container success path tests
# ---------------------------------------------------------------------------

def test_run_container_success_returns_formatted_result():
    """_run_container returns a formatted result block with exit code and stdout."""
    import docker_server

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.side_effect = lambda stdout=True, stderr=False: (
        b"hello world\n" if stdout and not stderr else b""
    )
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
    """_run_container result includes a Runtime line with ms."""
    import docker_server

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = b""
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

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = b""
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    with patch.object(docker_server, "_get_client", return_value=mock_client):
        docker_server._run_container(
            image="python:3.12-slim",
            command=["python", "/tmp/script"],
            code="print('hi')",
        )

    call_kwargs = mock_client.containers.run.call_args
    volumes = call_kwargs.kwargs.get("volumes") or call_kwargs[1].get("volumes", {})
    assert len(volumes) == 1
    mount = list(volumes.values())[0]
    assert mount["bind"] == "/tmp/script"
    assert mount["mode"] == "ro"


def test_run_container_no_code_no_volumes():
    """_run_container passes empty volumes dict when code is None."""
    import docker_server

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = b""
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    with patch.object(docker_server, "_get_client", return_value=mock_client):
        docker_server._run_container(
            image="ubuntu:24.04",
            command=["echo", "hi"],
        )

    call_kwargs = mock_client.containers.run.call_args
    volumes = call_kwargs.kwargs.get("volumes") or call_kwargs[1].get("volumes", {})
    assert volumes == {}


def test_run_container_removes_container_on_success():
    """_run_container calls container.remove() after successful execution."""
    import docker_server

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = b""
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    with patch.object(docker_server, "_get_client", return_value=mock_client):
        docker_server._run_container(
            image="python:3.12-slim",
            command=["python", "-c", "pass"],
        )

    mock_container.remove.assert_called_once()


def test_run_container_nonzero_exit_code():
    """_run_container includes exit code 1 in result when code crashes."""
    import docker_server

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 1}
    mock_container.logs.side_effect = lambda stdout=True, stderr=False: (
        b"" if stdout and not stderr else b"NameError: name 'x' is not defined\n"
    )
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


# ---------------------------------------------------------------------------
# _run_container error path tests
# ---------------------------------------------------------------------------

def test_run_container_timeout_kills_and_reports():
    """_run_container kills container and returns timeout message on timeout."""
    import docker_server

    mock_container = MagicMock()
    mock_container.wait.side_effect = Exception("Read timed out")
    mock_container.logs.side_effect = lambda stdout=True, stderr=False: b"partial" if stdout and not stderr else b""
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
