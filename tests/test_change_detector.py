"""Tests for change_detector.py."""

import hashlib
from pathlib import Path

import pytest

from agents_md_mcp.cache import make_empty_cache
from agents_md_mcp.change_detector import (
    _filter_paths,
    _hash_file,
    _is_excluded,
    detect_changes,
)
from agents_md_mcp.config import load_config
from agents_md_mcp.models import CachedFile, FileAnalysis


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write(path: Path, content: str = "hello") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _analysis(path: str) -> FileAnalysis:
    return FileAnalysis(path=path, language="python")


# ── Unit: _hash_file ──────────────────────────────────────────────────────────

def test_hash_file(tmp_path: Path) -> None:
    f = _write(tmp_path / "foo.py", "hello")
    assert _hash_file(f) == _sha256("hello")


def test_hash_file_changes(tmp_path: Path) -> None:
    f = _write(tmp_path / "foo.py", "hello")
    h1 = _hash_file(f)
    f.write_text("world", encoding="utf-8")
    assert _hash_file(f) != h1


# ── Unit: _is_excluded ────────────────────────────────────────────────────────

def test_is_excluded_node_modules() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("node_modules/lib/index.js", cfg)


def test_is_excluded_dist() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("dist/bundle.js", cfg)


def test_is_not_excluded_src() -> None:
    cfg = load_config("/tmp")
    assert not _is_excluded("src/main.py", cfg)


# ── Unit: _filter_paths ───────────────────────────────────────────────────────

def test_filter_removes_excluded(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    paths = ["src/app.py", "node_modules/lib/index.js", "dist/bundle.js"]
    result = _filter_paths(paths, cfg)
    assert result == ["src/app.py"]


def test_filter_removes_unsupported_extensions(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    paths = ["src/app.py", "README.md", "styles.css", "main.go"]
    result = _filter_paths(paths, cfg)
    assert set(result) == {"src/app.py", "main.go"}


def test_filter_include_pattern(tmp_path: Path) -> None:
    import json
    (tmp_path / ".agents-config.json").write_text(
        json.dumps({"include": ["src/**"]}), encoding="utf-8"
    )
    cfg = load_config(tmp_path)
    paths = ["src/app.py", "tests/test_app.py"]
    result = _filter_paths(paths, cfg)
    assert result == ["src/app.py"]


# ── Integration: detect_changes (filesystem, no git) ─────────────────────────

def test_cold_start_no_cache(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "app.py", "print('hi')")
    _write(tmp_path / "src" / "utils.py", "pass")
    cfg = load_config(tmp_path)

    changes = detect_changes(tmp_path, cfg, cache=None)
    paths = {c.path for c in changes}
    # Both .py files should be "new"
    assert any("app.py" in p for p in paths)
    assert all(c.status == "new" for c in changes)
    assert all(c.new_hash is not None for c in changes)


def test_incremental_no_changes(tmp_path: Path) -> None:
    content = "print('hi')"
    f = _write(tmp_path / "src" / "app.py", content)
    cfg = load_config(tmp_path)

    cache = make_empty_cache()
    cache.files["src/app.py"] = CachedFile(
        hash=_sha256(content),
        analysis=_analysis("src/app.py"),
    )
    changes = detect_changes(tmp_path, cfg, cache=cache)
    # No changes → empty list
    assert changes == []


def test_incremental_detects_modification(tmp_path: Path) -> None:
    f = _write(tmp_path / "src" / "app.py", "v1")
    cfg = load_config(tmp_path)

    cache = make_empty_cache()
    cache.files["src/app.py"] = CachedFile(
        hash=_sha256("v1"),
        analysis=_analysis("src/app.py"),
    )
    # Now change the file
    f.write_text("v2", encoding="utf-8")
    changes = detect_changes(tmp_path, cfg, cache=cache)

    assert len(changes) == 1
    assert changes[0].status == "modified"
    assert changes[0].old_hash == _sha256("v1")
    assert changes[0].new_hash == _sha256("v2")


def test_incremental_detects_deletion(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    cache = make_empty_cache()
    cache.files["src/gone.py"] = CachedFile(
        hash="abc",
        analysis=_analysis("src/gone.py"),
    )
    # File does NOT exist on disk
    changes = detect_changes(tmp_path, cfg, cache=cache)

    assert len(changes) == 1
    assert changes[0].status == "deleted"
    assert changes[0].path == "src/gone.py"


def test_incremental_detects_new_file(tmp_path: Path) -> None:
    # Cache has no files, but there's a .py on disk
    _write(tmp_path / "src" / "new_feature.py", "# new")
    cfg = load_config(tmp_path)
    cache = make_empty_cache()

    changes = detect_changes(tmp_path, cfg, cache=cache)
    assert len(changes) == 1
    assert changes[0].status == "new"
    assert "new_feature.py" in changes[0].path
