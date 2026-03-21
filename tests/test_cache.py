"""Tests for cache.py — CacheManager."""

import json
from pathlib import Path

import pytest

from agents_md_mcp.cache import (
    get_current_commit,
    is_cache_valid,
    load_cache,
    make_empty_cache,
    save_cache,
)
from agents_md_mcp.models import CacheData, CachedFile, FileAnalysis


def _make_file_analysis(path: str = "src/foo.py") -> FileAnalysis:
    return FileAnalysis(path=path, language="python")


def test_load_cache_missing(tmp_path: Path) -> None:
    assert load_cache(tmp_path) is None


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    cache = make_empty_cache(base_commit="abc123")
    cache.files["src/foo.py"] = CachedFile(
        hash="deadbeef",
        analysis=_make_file_analysis("src/foo.py"),
    )
    save_cache(tmp_path, cache)

    loaded = load_cache(tmp_path)
    assert loaded is not None
    assert loaded.base_commit == "abc123"
    assert "src/foo.py" in loaded.files
    assert loaded.files["src/foo.py"].hash == "deadbeef"


def test_load_cache_corrupt(tmp_path: Path) -> None:
    (tmp_path / ".agents-cache.json").write_text("{ broken", encoding="utf-8")
    assert load_cache(tmp_path) is None


def test_is_cache_valid_no_commit(tmp_path: Path) -> None:
    cache = make_empty_cache()
    assert is_cache_valid(cache, tmp_path)


def test_is_cache_valid_bad_commit(tmp_path: Path) -> None:
    """A non-existent commit hash → invalid cache."""
    cache = make_empty_cache(base_commit="0000000000000000000000000000000000000000")
    # Not a real git repo in tmp_path, git will fail → returns False
    assert not is_cache_valid(cache, tmp_path)


def test_make_empty_cache() -> None:
    cache = make_empty_cache(base_commit="abc")
    assert cache.version == "1.0"
    assert cache.base_commit == "abc"
    assert cache.files == {}
