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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write(path: Path, content: str = "hello") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _analysis(path: str) -> FileAnalysis:
    return FileAnalysis(path=path, language="python")


# ── _hash_file ────────────────────────────────────────────────────────────────

def test_hash_file(tmp_path: Path) -> None:
    f = _write(tmp_path / "foo.py", "hello")
    assert _hash_file(f) == _sha256("hello")


def test_hash_file_changes(tmp_path: Path) -> None:
    f = _write(tmp_path / "foo.py", "hello")
    h1 = _hash_file(f)
    f.write_text("world", encoding="utf-8")
    assert _hash_file(f) != h1


# ── _is_excluded: ** patterns ─────────────────────────────────────────────────

def test_excluded_dotenv_dir() -> None:
    """**/.venv/** must exclude .venv/lib/foo.py even without leading slash."""
    cfg = load_config("/tmp")
    assert _is_excluded(".venv/lib/python3.12/site-packages/foo.py", cfg)


def test_excluded_venv_dir() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("venv/lib/python3.12/foo.py", cfg)


def test_excluded_node_modules() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("node_modules/lib/index.js", cfg)
    assert _is_excluded("frontend/node_modules/react/index.js", cfg)


def test_excluded_dist() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("dist/bundle.js", cfg)
    assert _is_excluded("packages/app/dist/main.js", cfg)


def test_excluded_pycache() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("src/__pycache__/foo.cpython-312.pyc", cfg)


def test_excluded_min_js() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("static/vendor.min.js", cfg)
    assert _is_excluded("assets/js/app.min.js", cfg)


def test_excluded_git_dir() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded(".git/config", cfg)
    assert _is_excluded(".git/objects/pack/pack-abc.idx", cfg)


def test_not_excluded_src() -> None:
    cfg = load_config("/tmp")
    assert not _is_excluded("src/main.py", cfg)
    assert not _is_excluded("app/services/user.go", cfg)


def test_not_excluded_regular_js() -> None:
    """bundle.js (not .min.js) must NOT be excluded."""
    cfg = load_config("/tmp")
    assert not _is_excluded("src/bundle.js", cfg)


# ── _is_excluded: vendor directories ─────────────────────────────────────────

def test_excluded_bower_components() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("bower_components/angular/angular.js", cfg)
    assert _is_excluded("app/bower_components/lodash/lodash.js", cfg)


def test_excluded_app_lib() -> None:
    """AngularJS vendor pattern: app/lib/."""
    cfg = load_config("/tmp")
    assert _is_excluded("MyApp/app/lib/angular/angular.js", cfg)
    assert _is_excluded("frontend/app/lib/bootstrap/bootstrap.js", cfg)


def test_excluded_wwwroot_lib() -> None:
    """ASP.NET vendor pattern: wwwroot/lib/."""
    cfg = load_config("/tmp")
    assert _is_excluded("MyApp/wwwroot/lib/jquery/jquery.js", cfg)
    assert _is_excluded("MyApp/wwwroot/libs/bootstrap/bootstrap.js", cfg)


def test_excluded_bundle_js() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("dist/app.bundle.js", cfg)
    assert _is_excluded("static/vendor.bundle.js", cfg)


def test_excluded_site_packages() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("lib/python3.12/site-packages/requests/__init__.py", cfg)
    assert _is_excluded("some/deep/site-packages/foo.py", cfg)


def test_excluded_static_public_vendor() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("static/vendor/jquery.js", cfg)
    assert _is_excluded("public/vendor/bootstrap.js", cfg)
    assert _is_excluded("assets/vendor/moment.js", cfg)


def test_excluded_vendor_windows_backslash_paths() -> None:
    """Windows backslash paths must be excluded correctly (normalization fix)."""
    cfg = load_config("/tmp")
    assert _is_excluded("MyApp\\app\\lib\\angular\\angular.js", cfg)
    assert _is_excluded("MyApp\\wwwroot\\lib\\jquery.js", cfg)
    assert _is_excluded("frontend\\bower_components\\react\\index.js", cfg)
    assert _is_excluded("src\\__pycache__\\foo.pyc", cfg)


def test_not_excluded_app_services() -> None:
    """app/services/ must NOT be excluded — only app/lib/ is vendor."""
    cfg = load_config("/tmp")
    assert not _is_excluded("app/services/user.go", cfg)
    assert not _is_excluded("app/controllers/home.cs", cfg)


# ── _filter_paths ─────────────────────────────────────────────────────────────

def test_filter_removes_excluded(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    paths = ["src/app.py", "node_modules/lib/index.js", "dist/bundle.js",
             ".venv/lib/foo.py", "__pycache__/bar.pyc"]
    result = _filter_paths(paths, cfg)
    assert result == ["src/app.py"]


def test_filter_removes_unsupported_extensions(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    paths = ["src/app.py", "README.md", "styles.css", "main.go"]
    assert set(_filter_paths(paths, cfg)) == {"src/app.py", "main.go"}


def test_filter_with_gitignore_spec(tmp_path: Path) -> None:
    """Paths matched by a pathspec are filtered out."""
    import pathspec
    spec = pathspec.PathSpec.from_lines("gitignore", [".venv/", "dist/"])
    cfg = load_config(tmp_path)
    paths = ["src/app.py", ".venv/lib/foo.py", "dist/bundle.js"]
    result = _filter_paths(paths, cfg, gitignore_spec=spec)
    assert result == ["src/app.py"]


# ── detect_changes (filesystem, no git) ──────────────────────────────────────

def test_cold_start_no_cache(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "app.py", "print('hi')")
    _write(tmp_path / "src" / "utils.py", "pass")
    cfg = load_config(tmp_path)

    changes = detect_changes(tmp_path, cfg, cache=None)
    assert all(c.status == "new" for c in changes)
    assert all(c.new_hash is not None for c in changes)
    assert any("app.py" in c.path for c in changes)


def test_cold_start_respects_gitignore(tmp_path: Path) -> None:
    """Files in .gitignore are NOT returned in cold start (non-git repo)."""
    _write(tmp_path / "src" / "app.py", "code")
    _write(tmp_path / ".venv" / "lib" / "site.py", "venv stuff")
    _write(tmp_path / ".gitignore", ".venv/\n")
    cfg = load_config(tmp_path)

    changes = detect_changes(tmp_path, cfg, cache=None)
    paths = [c.path for c in changes]
    assert not any(".venv" in p for p in paths)
    assert any("app.py" in p for p in paths)


def test_cold_start_exclude_patterns(tmp_path: Path) -> None:
    """Config exclude patterns work regardless of gitignore."""
    _write(tmp_path / "src" / "app.py", "code")
    _write(tmp_path / "dist" / "bundle.js", "built")
    cfg = load_config(tmp_path)

    changes = detect_changes(tmp_path, cfg, cache=None)
    paths = [c.path for c in changes]
    assert not any("dist" in p for p in paths)


def test_incremental_no_changes(tmp_path: Path) -> None:
    content = "print('hi')"
    _write(tmp_path / "src" / "app.py", content)
    cfg = load_config(tmp_path)

    cache = make_empty_cache()
    cache.files["src/app.py"] = CachedFile(hash=_sha256(content), analysis=_analysis("src/app.py"))
    assert detect_changes(tmp_path, cfg, cache=cache) == []


def test_incremental_detects_modification(tmp_path: Path) -> None:
    f = _write(tmp_path / "src" / "app.py", "v1")
    cfg = load_config(tmp_path)

    cache = make_empty_cache()
    cache.files["src/app.py"] = CachedFile(hash=_sha256("v1"), analysis=_analysis("src/app.py"))
    f.write_text("v2", encoding="utf-8")

    changes = detect_changes(tmp_path, cfg, cache=cache)
    assert len(changes) == 1
    assert changes[0].status == "modified"
    assert changes[0].old_hash == _sha256("v1")
    assert changes[0].new_hash == _sha256("v2")


def test_incremental_detects_deletion(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    cache = make_empty_cache()
    cache.files["src/gone.py"] = CachedFile(hash="abc", analysis=_analysis("src/gone.py"))

    changes = detect_changes(tmp_path, cfg, cache=cache)
    assert len(changes) == 1
    assert changes[0].status == "deleted"


def test_incremental_detects_new_file(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "new_feature.py", "# new")
    cfg = load_config(tmp_path)
    cache = make_empty_cache()

    changes = detect_changes(tmp_path, cfg, cache=cache)
    assert len(changes) == 1
    assert changes[0].status == "new"
    assert "new_feature.py" in changes[0].path
