"""Tests for the Docker execution MCP server."""

import pytest
from unittest.mock import MagicMock, patch
import docker.errors
import requests.exceptions
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
    mock_container.wait.side_effect = requests.exceptions.ReadTimeout("Read timed out")
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


# ---------------------------------------------------------------------------
# _run_python handler tests
# ---------------------------------------------------------------------------

def test_run_python_uses_python_image():
    """_run_python calls _run_container with python:3.12-slim image."""
    import docker_server
    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_python(code="print('hi')")
    call_kwargs = mock_run.call_args.kwargs or dict(mock_run.call_args[0][0] if mock_run.call_args[0] else {})
    # Try both positional and keyword
    all_kwargs = {**mock_run.call_args.kwargs}
    if mock_run.call_args.args:
        import inspect
        sig = inspect.signature(docker_server._run_container)
        params = list(sig.parameters.keys())
        for i, arg in enumerate(mock_run.call_args.args):
            if i < len(params):
                all_kwargs[params[i]] = arg
    assert all_kwargs.get("image") == "python:3.12-slim"


def test_run_python_passes_code_through():
    """_run_python passes the original code in the code argument."""
    import docker_server
    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_python(code="print('hello')")
    code_arg = mock_run.call_args.kwargs.get("code") or (mock_run.call_args.args[2] if len(mock_run.call_args.args) > 2 else "")
    assert "print('hello')" in code_arg


def test_run_python_no_packages_no_pip_wrapper():
    """_run_python without packages passes code without pip install."""
    import docker_server
    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_python(code="x = 1")
    code_arg = mock_run.call_args.kwargs.get("code") or ""
    if not code_arg and mock_run.call_args.args:
        code_arg = mock_run.call_args.args[2] if len(mock_run.call_args.args) > 2 else ""
    assert "pip" not in code_arg


def test_run_python_with_packages_prepends_pip_install():
    """_run_python prepends pip install block when packages are provided."""
    import docker_server
    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_python(code="import requests", packages=["requests", "pandas"])
    code_arg = mock_run.call_args.kwargs.get("code") or ""
    if not code_arg and mock_run.call_args.args:
        code_arg = mock_run.call_args.args[2] if len(mock_run.call_args.args) > 2 else ""
    assert "pip" in code_arg
    assert "requests" in code_arg
    assert "pandas" in code_arg
    assert "import requests" in code_arg


def test_run_python_respects_timeout():
    """_run_python forwards timeout_seconds as timeout to _run_container."""
    import docker_server
    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_python(code="pass", timeout_seconds=120)
    timeout_arg = mock_run.call_args.kwargs.get("timeout")
    if timeout_arg is None and mock_run.call_args.args:
        timeout_arg = mock_run.call_args.args[3] if len(mock_run.call_args.args) > 3 else None
    assert timeout_arg == 120


# ---------------------------------------------------------------------------
# _run_shell handler tests
# ---------------------------------------------------------------------------

def test_run_shell_uses_ubuntu_image():
    """_run_shell calls _run_container with ubuntu:24.04 image."""
    import docker_server
    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_shell(script="echo hi")
    image_arg = mock_run.call_args.kwargs.get("image") or (mock_run.call_args.args[0] if mock_run.call_args.args else "")
    assert image_arg == "ubuntu:24.04"


def test_run_shell_uses_bash_command():
    """_run_shell runs the script with bash."""
    import docker_server
    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_shell(script="echo hi")
    cmd_arg = mock_run.call_args.kwargs.get("command") or (mock_run.call_args.args[1] if len(mock_run.call_args.args) > 1 else [])
    assert cmd_arg[0] == "bash"


def test_run_shell_with_packages_prepends_apt_install():
    """_run_shell prepends apt-get install when packages provided."""
    import docker_server
    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_shell(script="curl example.com", packages=["curl"])
    code_arg = mock_run.call_args.kwargs.get("code") or (mock_run.call_args.args[2] if len(mock_run.call_args.args) > 2 else "")
    assert "apt-get" in code_arg
    assert "curl" in code_arg
    assert "curl example.com" in code_arg


def test_run_shell_no_packages_no_apt():
    """_run_shell without packages does not include apt-get."""
    import docker_server
    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_shell(script="ls -la")
    code_arg = mock_run.call_args.kwargs.get("code") or (mock_run.call_args.args[2] if len(mock_run.call_args.args) > 2 else "")
    assert "apt-get" not in code_arg


# ---------------------------------------------------------------------------
# _run_node handler tests
# ---------------------------------------------------------------------------

def test_run_node_uses_node_image():
    """_run_node calls _run_container with node:22-slim image."""
    import docker_server
    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_node(code="console.log('hi')")
    image_arg = mock_run.call_args.kwargs.get("image") or (mock_run.call_args.args[0] if mock_run.call_args.args else "")
    assert image_arg == "node:22-slim"


def test_run_node_with_packages_prepends_npm_install():
    """_run_node prepends npm install when packages provided."""
    import docker_server
    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_node(code="const _ = require('lodash')", packages=["lodash"])
    code_arg = mock_run.call_args.kwargs.get("code") or (mock_run.call_args.args[2] if len(mock_run.call_args.args) > 2 else "")
    assert "npm" in code_arg
    assert "lodash" in code_arg
    assert "require('lodash')" in code_arg


def test_run_node_no_packages_no_npm():
    """_run_node without packages does not include npm."""
    import docker_server
    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_node(code="console.log(42)")
    code_arg = mock_run.call_args.kwargs.get("code") or (mock_run.call_args.args[2] if len(mock_run.call_args.args) > 2 else "")
    assert "npm" not in code_arg


# ---------------------------------------------------------------------------
# _run_in_image handler tests
# ---------------------------------------------------------------------------

def test_run_in_image_passes_image_and_command():
    """_run_in_image passes image and command through to _run_container."""
    import docker_server
    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_in_image(image="rust:1.82", command=["rustc", "--version"], timeout_seconds=45)
    kw = mock_run.call_args.kwargs
    image_arg = kw.get("image") or (mock_run.call_args.args[0] if mock_run.call_args.args else "")
    cmd_arg = kw.get("command") or (mock_run.call_args.args[1] if len(mock_run.call_args.args) > 1 else [])
    timeout_arg = kw.get("timeout")
    assert image_arg == "rust:1.82"
    assert cmd_arg == ["rustc", "--version"]
    assert timeout_arg == 45


def test_run_in_image_passes_code():
    """_run_in_image forwards code parameter to _run_container."""
    import docker_server
    with patch.object(docker_server, "_run_container", return_value="ok") as mock_run:
        docker_server._run_in_image(
            image="golang:1.23",
            command=["go", "run", "/tmp/script"],
            code="package main\nfunc main() {}",
        )
    code_arg = mock_run.call_args.kwargs.get("code") or (mock_run.call_args.args[2] if len(mock_run.call_args.args) > 2 else "")
    assert "package main" in (code_arg or "")


# ---------------------------------------------------------------------------
# call_tool dispatcher tests
# ---------------------------------------------------------------------------

async def test_call_tool_dispatches_run_python():
    """call_tool routes 'run_python' to _run_python and wraps in TextContent."""
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
