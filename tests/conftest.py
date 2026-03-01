"""Pytest configuration: add tools/ directory to sys.path so docker_server
can be imported directly (it lives in tools/, not in a Python package)."""

import sys
from pathlib import Path

# Allow `import docker_server` in tests
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
