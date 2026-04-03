"""Shared CLI utilities — env loading, project root discovery."""

from pathlib import Path


def find_project_root() -> Path:
    """Walk up from this file looking for pyproject.toml."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise FileNotFoundError(
        "Could not find project root (no pyproject.toml in any parent directory)"
    )


def load_env() -> None:
    """Load .env with priority: shell env vars > project root .env > config/.env.

    Uses ``override=False`` so that variables already present in the
    environment (e.g. exported in the shell) are never overwritten.
    The root-level ``.env`` is loaded first; ``config/.env`` acts as a
    fallback for any variables not yet set.
    """
    from dotenv import load_dotenv

    root = find_project_root()

    # Primary location — project root .env
    root_env = root / ".env"
    if root_env.is_file():
        load_dotenv(root_env, override=False)

    # Fallback — config/.env (legacy location)
    config_env = root / "config" / ".env"
    if config_env.is_file():
        load_dotenv(config_env, override=False)


def get_config_dir() -> Path:
    """Return the config/ directory under the project root."""
    return find_project_root() / "config"
