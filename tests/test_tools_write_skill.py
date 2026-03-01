"""Tests for write_skill template and PEP 723 compliance."""
import json
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from arc.tools import _SKILL_TEMPLATE, _ARC_GENERATED_MARKER


def run(coro):
    return asyncio.run(coro)


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


def test_write_skill_uses_uv_run_in_config(tmp_path):
    """Generated mcp_servers.json entry must use uv run, not python."""
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text('{"servers": {}}')
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    with (
        patch("arc.tools._MCP_CONFIG_PATH", config_path),
        patch("arc.tools._TOOLS_DIR", tools_dir),
        patch("arc.mcp_client.reload_mcp_manager", new_callable=AsyncMock, return_value=None),
    ):
        from arc.tools import tool_write_skill
        run(tool_write_skill(
            name="myskill",
            description="does stuff",
            code="# empty",
        ))

    config = json.loads(config_path.read_text())
    entry = config["servers"]["myskill"]
    assert entry["command"] == "uv"
    assert entry["args"] == ["run", "tools/myskill_server.py"]


def test_write_skill_default_deps_in_file(tmp_path):
    """Generated file must contain mcp in the PEP 723 block when no deps given."""
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text('{"servers": {}}')
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    with (
        patch("arc.tools._MCP_CONFIG_PATH", config_path),
        patch("arc.tools._TOOLS_DIR", tools_dir),
        patch("arc.mcp_client.reload_mcp_manager", new_callable=AsyncMock, return_value=None),
    ):
        from arc.tools import tool_write_skill
        run(tool_write_skill(
            name="myskill",
            description="does stuff",
            code="# empty",
        ))

    content = (tools_dir / "myskill_server.py").read_text()
    assert '#   "mcp"' in content


def test_write_skill_extra_deps_in_file(tmp_path):
    """Extra dependencies must appear in the PEP 723 block."""
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text('{"servers": {}}')
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    with (
        patch("arc.tools._MCP_CONFIG_PATH", config_path),
        patch("arc.tools._TOOLS_DIR", tools_dir),
        patch("arc.mcp_client.reload_mcp_manager", new_callable=AsyncMock, return_value=None),
    ):
        from arc.tools import tool_write_skill
        run(tool_write_skill(
            name="myskill",
            description="does stuff",
            code="import requests",
            dependencies=["requests", "pytz"],
        ))

    content = (tools_dir / "myskill_server.py").read_text()
    assert '#   "requests"' in content
    assert '#   "pytz"' in content


def test_write_skill_mcp_not_duplicated(tmp_path):
    """If caller lists mcp in dependencies, it must not appear twice."""
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text('{"servers": {}}')
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    with (
        patch("arc.tools._MCP_CONFIG_PATH", config_path),
        patch("arc.tools._TOOLS_DIR", tools_dir),
        patch("arc.mcp_client.reload_mcp_manager", new_callable=AsyncMock, return_value=None),
    ):
        from arc.tools import tool_write_skill
        run(tool_write_skill(
            name="myskill",
            description="does stuff",
            code="# empty",
            dependencies=["mcp"],  # mcp listed explicitly
        ))

    content = (tools_dir / "myskill_server.py").read_text()
    assert content.count('"mcp"') == 1
