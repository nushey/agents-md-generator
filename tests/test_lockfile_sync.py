"""Regression checks for dependency lockfile consistency."""

from pathlib import Path
import tomllib


def test_uv_lock_matches_project_version() -> None:
    """uv.lock must track the same project version as pyproject.toml."""
    repo_root = Path(__file__).resolve().parents[1]

    pyproject_data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    lockfile_data = tomllib.loads((repo_root / "uv.lock").read_text(encoding="utf-8"))

    expected_version = pyproject_data["project"]["version"]
    lockfile_version = next(
        package["version"]
        for package in lockfile_data["package"]
        if package["name"] == pyproject_data["project"]["name"]
    )
    assert lockfile_version == expected_version
