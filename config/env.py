"""Environment variable loading from .env file."""

from __future__ import annotations

from pathlib import Path

_ENV_LOADED = False


def load_env(env_file: str = ".env") -> bool:
    """Load .env from project root or cwd; does not override existing env vars."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return False

    from dotenv import load_dotenv

    project_root = Path(__file__).resolve().parent.parent
    candidates = [
        Path.cwd() / env_file,
        project_root / env_file,
    ]
    for path in candidates:
        if path.is_file():
            load_dotenv(path, override=False)
            _ENV_LOADED = True
            return True
    return False


def reset_env_loaded() -> None:
    """Reset load flag (for tests)."""
    global _ENV_LOADED
    _ENV_LOADED = False
