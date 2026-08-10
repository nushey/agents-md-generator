"""Tests for change_detector.py (git-based)."""

import subprocess
from pathlib import Path

import pytest

from agents_md_mcp.cache import make_empty_cache
from agents_md_mcp.change_detector import (
    NotAGitRepositoryError,
    _filter_paths,
    _is_excluded,
    detect_changes,
    git_file_hashes,
    git_list_all_files,
)
from agents_md_mcp.config import load_config
from agents_md_mcp.models import CachedFile


# ── Helpers ───────────────────────────────────────────────────────────────────

def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, check=True,
    )
    return result.stdout


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test.local")
    _git(root, "config", "user.name", "test")


def _write(path: Path, content: str = "hello") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _commit_all(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "test", "--no-verify")


def _blob_sha(root: Path, rel: str) -> str:
    return _git(root, "hash-object", rel).strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _init_repo(tmp_path)
    return tmp_path


# ── git_file_hashes ──────────────────────────────────────────────────────────

def test_git_file_hashes_not_a_repo(tmp_path: Path) -> None:
    assert git_file_hashes(tmp_path) is None


def test_git_file_hashes_tracked(repo: Path) -> None:
    _write(repo / "src" / "app.py", "print('hi')")
    _commit_all(repo)
    hashes = git_file_hashes(repo)
    assert hashes == {"src/app.py": _blob_sha(repo, "src/app.py")}


def test_git_file_hashes_untracked(repo: Path) -> None:
    _write(repo / "new.py", "pass")
    hashes = git_file_hashes(repo)
    assert "new.py" in hashes
    assert hashes["new.py"] == _blob_sha(repo, "new.py")


def test_git_file_hashes_dirty_file_gets_worktree_hash(repo: Path) -> None:
    f = _write(repo / "app.py", "v1")
    _commit_all(repo)
    f.write_text("v2", encoding="utf-8")
    hashes = git_file_hashes(repo)
    assert hashes["app.py"] == _blob_sha(repo, "app.py")  # hash of v2, not the index


def test_git_file_hashes_worktree_deleted(repo: Path) -> None:
    f = _write(repo / "gone.py", "x")
    _commit_all(repo)
    f.unlink()
    assert "gone.py" not in git_file_hashes(repo)


def test_git_file_hashes_respects_gitignore(repo: Path) -> None:
    _write(repo / ".gitignore", "secret.py\n")
    _write(repo / "secret.py", "x")
    _write(repo / "app.py", "y")
    hashes = git_file_hashes(repo)
    assert "secret.py" not in hashes
    assert "app.py" in hashes


def test_git_list_all_files(repo: Path) -> None:
    _write(repo / ".gitignore", "ignored.txt\n")
    _write(repo / "tracked.py", "x")
    _commit_all(repo)
    _write(repo / "untracked.md", "y")
    _write(repo / "ignored.txt", "z")
    files = git_list_all_files(repo)
    assert "tracked.py" in files
    assert "untracked.md" in files
    assert "ignored.txt" not in files


def test_git_list_all_files_not_a_repo(tmp_path: Path) -> None:
    assert git_list_all_files(tmp_path) is None


# ── _is_excluded: ** patterns ─────────────────────────────────────────────────

def test_excluded_dotenv_dir() -> None:
    """**/.venv/** must exclude .venv/lib/foo.py even without leading slash."""
    cfg = load_config("/tmp")
    assert _is_excluded(".venv/lib/python3.12/site-packages/foo.py", cfg)


def test_excluded_node_modules() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("node_modules/lib/index.js", cfg)
    assert _is_excluded("frontend/node_modules/react/index.js", cfg)


def test_excluded_dist() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("dist/bundle.js", cfg)
    assert _is_excluded("packages/app/dist/main.js", cfg)


def test_excluded_min_js() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("static/vendor.min.js", cfg)
    assert _is_excluded("assets/js/app.min.js", cfg)


def test_not_excluded_src() -> None:
    cfg = load_config("/tmp")
    assert not _is_excluded("src/main.py", cfg)
    assert not _is_excluded("app/services/user.go", cfg)


def test_excluded_vendor_windows_backslash_paths() -> None:
    cfg = load_config("/tmp")
    assert _is_excluded("MyApp\\app\\lib\\angular\\angular.js", cfg)
    assert _is_excluded("MyApp\\wwwroot\\lib\\jquery.js", cfg)
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


# ── detect_changes ────────────────────────────────────────────────────────────

def test_detect_changes_requires_git(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "x")
    cfg = load_config(tmp_path)
    with pytest.raises(NotAGitRepositoryError):
        detect_changes(tmp_path, cfg, cache=None)


def test_cold_start_no_cache(repo: Path) -> None:
    _write(repo / "src" / "app.py", "print('hi')")
    _write(repo / "src" / "utils.py", "pass")
    _commit_all(repo)
    cfg = load_config(repo)

    changes = detect_changes(repo, cfg, cache=None)
    assert all(c.status == "new" for c in changes)
    assert all(c.new_hash is not None for c in changes)
    assert any("app.py" in c.path for c in changes)


def test_cold_start_includes_untracked(repo: Path) -> None:
    _write(repo / "src" / "app.py", "code")
    cfg = load_config(repo)
    changes = detect_changes(repo, cfg, cache=None)
    assert [c.path for c in changes] == ["src/app.py"]


def test_cold_start_respects_gitignore(repo: Path) -> None:
    _write(repo / ".gitignore", "generated/\n")
    _write(repo / "src" / "app.py", "code")
    _write(repo / "generated" / "out.py", "gen")
    cfg = load_config(repo)

    paths = [c.path for c in detect_changes(repo, cfg, cache=None)]
    assert paths == ["src/app.py"]


def test_cold_start_exclude_patterns(repo: Path) -> None:
    """Config exclude patterns apply even to committed files."""
    _write(repo / "src" / "app.py", "code")
    _write(repo / "dist" / "bundle.js", "built")
    _commit_all(repo)
    cfg = load_config(repo)

    paths = [c.path for c in detect_changes(repo, cfg, cache=None)]
    assert not any("dist" in p for p in paths)


def test_incremental_no_changes(repo: Path) -> None:
    _write(repo / "src" / "app.py", "print('hi')")
    _commit_all(repo)
    cfg = load_config(repo)

    cache = make_empty_cache()
    cache.files["src/app.py"] = CachedFile(hash=_blob_sha(repo, "src/app.py"))
    assert detect_changes(repo, cfg, cache=cache) == []


def test_incremental_detects_modification(repo: Path) -> None:
    f = _write(repo / "src" / "app.py", "v1")
    _commit_all(repo)
    old_sha = _blob_sha(repo, "src/app.py")
    cfg = load_config(repo)

    cache = make_empty_cache()
    cache.files["src/app.py"] = CachedFile(hash=old_sha)
    f.write_text("v2", encoding="utf-8")

    changes = detect_changes(repo, cfg, cache=cache)
    assert len(changes) == 1
    assert changes[0].status == "modified"
    assert changes[0].old_hash == old_sha
    assert changes[0].new_hash == _blob_sha(repo, "src/app.py")


def test_incremental_detects_deletion(repo: Path) -> None:
    _write(repo / "keep.py", "x")
    _commit_all(repo)
    cfg = load_config(repo)
    cache = make_empty_cache()
    cache.files["keep.py"] = CachedFile(hash=_blob_sha(repo, "keep.py"))
    cache.files["src/gone.py"] = CachedFile(hash="abc")

    changes = detect_changes(repo, cfg, cache=cache)
    assert len(changes) == 1
    assert changes[0].status == "deleted"
    assert changes[0].path == "src/gone.py"


def test_incremental_detects_new_file(repo: Path) -> None:
    _write(repo / "src" / "new_feature.py", "# new")
    cfg = load_config(repo)
    cache = make_empty_cache()

    changes = detect_changes(repo, cfg, cache=cache)
    assert len(changes) == 1
    assert changes[0].status == "new"
    assert "new_feature.py" in changes[0].path


def test_committed_modification_detected_without_rehash(repo: Path) -> None:
    """A committed change is caught purely via index SHAs (no file reads)."""
    f = _write(repo / "app.py", "v1")
    _commit_all(repo)
    old_sha = _blob_sha(repo, "app.py")
    cache = make_empty_cache()
    cache.files["app.py"] = CachedFile(hash=old_sha)

    f.write_text("v2", encoding="utf-8")
    _commit_all(repo)

    cfg = load_config(repo)
    changes = detect_changes(repo, cfg, cache=cache)
    assert len(changes) == 1
    assert changes[0].status == "modified"


# ── auto profile resolution ──────────────────────────────────────────────────

def test_auto_profile_resolved_during_detect(repo: Path) -> None:
    _write(repo / "app.py", "x")
    cfg = load_config(repo)
    assert cfg.project_size == "auto"
    detect_changes(repo, cfg, cache=None)
    assert cfg.project_size == "small"


def test_explicit_profile_not_overridden(repo: Path) -> None:
    _write(repo / ".agents-config.json", '{"project_size": "large"}')
    _write(repo / "app.py", "x")
    cfg = load_config(repo)
    detect_changes(repo, cfg, cache=None)
    assert cfg.project_size == "large"
