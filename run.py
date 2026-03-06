#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "python-telegram-bot>=21.0",
#   "ollama>=0.4.0",
#   "chromadb>=0.5.0",
#   "fastapi>=0.115.0",
#   "uvicorn[standard]>=0.32.0",
#   "jinja2>=3.1.0",
#   "apscheduler>=3.10.0",
#   "python-dotenv>=1.0.0",
#   "aiosqlite>=0.20.0",
#   "python-multipart>=0.0.9",
#   "mcp[cli]>=1.0.0",
#   "docker>=7.0.0",
# ]
# ///
"""ARC entry point for ``uv run run.py``."""

import sys
from pathlib import Path

# Ensure src/ is on the import path so ``arc`` is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from arc.main import main

if __name__ == "__main__":
    main()
