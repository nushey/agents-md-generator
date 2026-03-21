"""Tests for gitignore.py — load_gitignore_spec + is_gitignored."""

from pathlib import Path

import pytest

from agents_md_mcp.gitignore import is_gitignored, load_gitignore_spec


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_no_gitignore_returns_none(tmp_path: Path) -> None:
    spec = load_gitignore_spec(tmp_path)
    assert spec is None


def test_is_gitignored_with_none_spec() -> None:
    assert not is_gitignored("anything/foo.py", None)


def test_simple_directory_pattern(tmp_path: Path) -> None:
    _write(tmp_path / ".gitignore", ".venv/\nnode_modules/\n")
    spec = load_gitignore_spec(tmp_path)
    assert spec is not None

    assert is_gitignored(".venv/lib/foo.py", spec)
    assert is_gitignored(".venv/lib/python3.12/site-packages/bar.py", spec)
    assert is_gitignored("node_modules/react/index.js", spec)
    assert not is_gitignored("src/main.py", spec)


def test_file_extension_pattern(tmp_path: Path) -> None:
    _write(tmp_path / ".gitignore", "*.pyc\n*.egg-info/\n")
    spec = load_gitignore_spec(tmp_path)

    assert is_gitignored("src/__pycache__/foo.pyc", spec)
    assert is_gitignored("mypackage.egg-info/SOURCES.txt", spec)
    assert not is_gitignored("src/main.py", spec)


def test_specific_file_ignored(tmp_path: Path) -> None:
    _write(tmp_path / ".gitignore", ".agents-cache.json\n.env\n")
    spec = load_gitignore_spec(tmp_path)

    assert is_gitignored(".agents-cache.json", spec)
    assert is_gitignored(".env", spec)
    assert not is_gitignored(".envrc", spec)


def test_nested_gitignore(tmp_path: Path) -> None:
    """Patterns from nested .gitignore files are loaded too."""
    _write(tmp_path / ".gitignore", ".venv/\n")
    _write(tmp_path / "frontend" / ".gitignore", "dist/\nbuild/\n")
    spec = load_gitignore_spec(tmp_path)

    assert is_gitignored(".venv/lib/foo.py", spec)
    assert is_gitignored("frontend/dist/bundle.js", spec)
    assert not is_gitignored("src/main.py", spec)


def test_comments_and_blank_lines_ignored(tmp_path: Path) -> None:
    _write(tmp_path / ".gitignore", "# This is a comment\n\n.venv/\n  \n")
    spec = load_gitignore_spec(tmp_path)
    assert spec is not None
    assert is_gitignored(".venv/foo.py", spec)
