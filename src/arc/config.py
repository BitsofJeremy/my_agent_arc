"""ARC configuration — loads settings from environment variables and .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path
from typing import get_type_hints

from dotenv import load_dotenv

# Project root is three levels up from this file:
#   src/arc/config.py  →  src/arc  →  src  →  project root
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent

# Load .env from the project root (no-op when file is absent).
load_dotenv(PROJECT_ROOT / ".env")


def _resolve_path(raw: str) -> str:
    """Resolve a relative path against *PROJECT_ROOT*, leave absolutes untouched."""
    p = Path(raw)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return str(p)


# ---------------------------------------------------------------------------
# Mapping from dataclass field name → environment variable name.
# Convention: upper-case the field name and prefix with ``ARC_``.
# ---------------------------------------------------------------------------

_ENV_PREFIX = "ARC_"

# Fields whose resolved values are filesystem paths.
_PATH_FIELDS: frozenset[str] = frozenset(
    {"sqlite_db_path", "chromadb_path", "soul_path", "heartbeat_path"},
)


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable, typed application settings."""

    telegram_bot_token: str = ""
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "minimax-m2.5:cloud"
    ollama_embed_model: str = "nomic-embed-text"
    sqlite_db_path: str = "data/arc.db"
    chromadb_path: str = "data/chromadb"
    context_window_tokens: int = 8192
    compaction_threshold: float = 0.5
    heartbeat_interval_minutes: int = 15
    admin_host: str = "0.0.0.0"
    admin_port: int = 8080
    soul_path: str = "data/soul.md"
    heartbeat_path: str = "data/heartbeat.md"
    max_agent_iterations: int = 10


def load_settings() -> Settings:
    """Build a :class:`Settings` instance from environment variables.

    Each field is read from ``ARC_<FIELD_NAME>`` (upper-cased).  If the
    variable is unset the dataclass default is used.  Values are coerced to the
    declared type (``int``, ``float``, ``str``).  Path fields are resolved
    relative to the project root.
    """
    hints = get_type_hints(Settings)
    kwargs: dict[str, str | int | float] = {}

    for f in fields(Settings):
        env_key = f"{_ENV_PREFIX}{f.name.upper()}"
        raw = os.environ.get(env_key)

        if raw is None:
            continue  # fall back to the dataclass default

        target_type = hints[f.name]
        try:
            value: str | int | float = target_type(raw)
        except (ValueError, TypeError) as exc:
            msg = (
                f"Cannot convert env var {env_key}={raw!r} "
                f"to {target_type.__name__}: {exc}"
            )
            raise ValueError(msg) from exc

        # Resolve relative paths against the project root.
        if f.name in _PATH_FIELDS and isinstance(value, str):
            value = _resolve_path(value)

        kwargs[f.name] = value

    # Also resolve path defaults that were *not* overridden by env vars.
    field_defaults: dict[str, str] = {
        f.name: f.default  # type: ignore[misc]
        for f in fields(Settings)
        if f.name in _PATH_FIELDS
    }
    defaults: dict[str, str] = {}
    for name, default_val in field_defaults.items():
        if name not in kwargs:
            defaults[name] = _resolve_path(default_val)

    return Settings(**defaults, **kwargs)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a module-level singleton :class:`Settings` instance."""
    return load_settings()
