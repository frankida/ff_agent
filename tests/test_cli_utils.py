"""Tests for fantasy_agent.cli.utils — project root discovery and env loading."""

from pathlib import Path

from fantasy_agent.cli.utils import find_project_root, get_config_dir


def test_find_project_root_returns_directory_with_pyproject():
    root = find_project_root()
    assert (root / "pyproject.toml").exists(), (
        f"Expected pyproject.toml in {root}"
    )


def test_find_project_root_is_stable():
    """Calling twice should give the same answer."""
    assert find_project_root() == find_project_root()


def test_get_config_dir_under_project_root():
    config = get_config_dir()
    assert config == find_project_root() / "config"
