"""Tests for write_skill template and PEP 723 compliance."""
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
