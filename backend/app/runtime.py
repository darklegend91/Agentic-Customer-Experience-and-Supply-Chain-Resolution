"""Runtime environment checks shared by HTTP and MCP entry points."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_ENVIRONMENTS = {"local", "dev", "development"}


class LocalDevelopmentOnly(RuntimeError):
    """Raised when a development-only interface is used outside local scope."""


def load_project_environment() -> None:
    """Load project and workspace environment files without overriding process env."""
    for path in (PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env"):
        if path.exists():
            load_dotenv(path, override=False)


def require_local_development() -> str:
    """Fail closed unless this development fixture is explicitly enabled."""
    load_project_environment()
    environment = os.getenv("APP_ENV", "").strip().lower()
    if environment not in LOCAL_ENVIRONMENTS:
        raise LocalDevelopmentOnly(
            "This investigation interface is disabled outside local development"
        )
    return environment
